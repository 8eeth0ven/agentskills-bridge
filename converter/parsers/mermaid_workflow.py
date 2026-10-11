"""mermaid workflow.md → AgentIR 解析器(best-effort,正则提取)。

提取目标:
    frontmatter name/description → name(slugify)/description
    首个 `# ` 标题               → display_name
    ```mermaid 块                 → 节点 `id["name"]` 与边 `a --> |label| b`
                                   (仅作图信息,记入 metadata["chain"])
    `## Step N: name` 小节        → 步骤正文(到下一个 `## ` 头或文末)
    多步合并规则                  → 同 WorkflowIR.to_agent_ir:
                                   单步 → system_prompt=正文;
                                   多步 → "# {display}\\n\\n" + "\\n\\n".join(
                                   "## Step {i}: {name}\\n{正文}")
    解析不出 mermaid 块/步骤时     → 回退:整个正文(frontmatter 之后)作为 system_prompt
    knowledge/                    → collect_knowledge 回收
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

try:
    from converter.ir import AgentIR, TaskStep, parse_frontmatter, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, TaskStep, parse_frontmatter, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore

__all__ = ["parse_mermaid_workflow"]

_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_NODE_DEF_RE = re.compile(r'^\s*([A-Za-z0-9_-]+)\["([^"]*)"\]\s*$')
_EDGE_RE = re.compile(
    r'^\s*([A-Za-z0-9_-]+)(?:\["[^"]*"\])?\s*-->\s*(?:\|([^|]*)\|\s*)?'
    r'([A-Za-z0-9_-]+)(?:\["[^"]*"\])?\s*$'
)
_STEP_HEAD_RE = re.compile(r"^## (?:Step\s+)?(\d+):\s*(.+)$", re.MULTILINE)
_ANY_H2_RE = re.compile(r"^## ", re.MULTILINE)
_CONTEXT_HEAD_RE = re.compile(r"^## Source Context\s*$", re.MULTILINE)
# Source Context 的边界:原文内嵌任意 H2 标题(如 "## Overview"),不能用
# _ANY_H2_RE 截断——只认紧随其后的 Knowledge Files 节头或文件尾。
_CONTEXT_END_RE = re.compile(r"^## Knowledge Files\s*$", re.MULTILINE)
_H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def _parse_graph(block: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, str]]]:
    """解析 mermaid 块:返回 ([(node_id, node_name)], [(source, target, label)])。"""
    nodes: List[Tuple[str, str]] = []
    edges: List[Tuple[str, str, str]] = []
    for line in block.splitlines():
        m = _NODE_DEF_RE.match(line)
        if m:
            label = m.group(2).replace("\\\\", "\\").replace("#quot;", '"')
            nodes.append((m.group(1), label))
            continue
        m = _EDGE_RE.match(line)
        if m:
            edges.append((m.group(1), m.group(3), (m.group(2) or "").strip()))
    return nodes, edges


def _split_steps(body: str) -> List[Tuple[str, str]]:
    """按 `## Step N: name` 切步骤;内容截至下一个任意 `## ` 头(排掉知识清单节)。"""
    steps: List[Tuple[str, str]] = []
    heads = list(_STEP_HEAD_RE.finditer(body))
    for i, m in enumerate(heads):
        start = m.end()
        nxt_any = _ANY_H2_RE.search(body, start)
        end = nxt_any.start() if nxt_any else len(body)
        content = body[start:end].strip()
        steps.append((m.group(2).strip(), content))
    return steps


def parse_mermaid_workflow(path: Union[str, Path]) -> AgentIR:
    """解析 mermaid workflow 目录/workflow.md 为 AgentIR。

    传目录时自动定位 workflow.md;文件不存在抛 FileNotFoundError。
    """
    p = Path(path)
    if p.is_dir():
        cand = p / "workflow.md"
        if not cand.is_file():
            raise FileNotFoundError(f"missing workflow.md under: {p}")
        p = cand
    if not p.is_file():
        raise FileNotFoundError(f"missing mermaid workflow file: {p}")
    text = p.read_text(encoding="utf-8")

    meta, body = parse_frontmatter(text)
    raw_name = (meta.get("name") or "").strip() or p.stem
    name = slugify(raw_name) or "workflow"
    description = (meta.get("description") or "").strip()

    h1 = _H1_RE.search(body)
    display_name = h1.group(1).strip() if h1 else ""

    nodes: List[Tuple[str, str]] = []
    edges: List[Tuple[str, str, str]] = []
    block_m = _MERMAID_BLOCK_RE.search(text)
    if block_m:
        nodes, edges = _parse_graph(block_m.group(1))

    steps = _split_steps(body)

    # Source Context 节优先:本工具产物的原文全文回源节(步骤链只是骨架);
    # 有它则 system_prompt 取全文,Step 分节仅作 tasks 保留。
    ctx_m = _CONTEXT_HEAD_RE.search(body)
    source_context = ""
    if ctx_m:
        nxt = _CONTEXT_END_RE.search(body, ctx_m.end())
        end = nxt.start() if nxt else len(body)
        source_context = body[ctx_m.end():end].strip()

    if steps:
        if len(steps) == 1:
            system_prompt = steps[0][1]
        else:
            title = display_name or name
            system_prompt = f"# {title}\n\n" + "\n\n".join(
                f"## Step {i}: {step_name}\n{content}"
                for i, (step_name, content) in enumerate(steps, 1)
            )
        tasks = [TaskStep(name=n, description=c, agent=name) for n, c in steps]
    else:
        system_prompt = body.strip()
        tasks = []
    if source_context:
        system_prompt = source_context

    metadata: Dict[str, Any] = {
        "source_format": "mermaid-workflow",
        "source_path": str(p.resolve()),
    }
    if nodes:
        metadata["mermaid_nodes"] = [nid for nid, _ in nodes]
    if edges:
        metadata["chain"] = [
            f"{src} -> {tgt}" + (f" [{label}]" if label else "")
            for src, tgt, label in edges
        ]

    return AgentIR(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=system_prompt,
        tasks=tasks,
        knowledge=collect_knowledge(p.parent),
        metadata=metadata,
    )
