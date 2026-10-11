"""Claude Code subagent 目录 → AgentIR 解析器。

root 指向 claude_subagent emitter 产出的目录:
    .claude/agents/<name>.md  subagent 定义:frontmatter(name/description/
                              tools/model)+ 正文 system_prompt
    knowledge/*.md            collect_knowledge 回收

frontmatter 的 tools 是多行 YAML 列表(`- "Read"` 逐行),ir.parse_frontmatter
只支持平面字符串(会把列表项折叠进 meta["tools"]),故另写 _parse_tools_list
从原始 frontmatter 文本用正则提取列表项。.claude/agents/ 无 md 抛 FileNotFoundError。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Union

try:
    from converter.ir import AgentIR, ToolSpec, parse_frontmatter, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, ToolSpec, parse_frontmatter, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore

_KEY_LINE_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:")
_LIST_ITEM_RE = re.compile(r"^-\s*(.+?)\s*$")


def _raw_frontmatter(text: str) -> str:
    """取 frontmatter 原始文本(首行 --- 到下一个 --- 之间);无则空串。"""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    return text[3:end]


def _unquote(value: str) -> str:
    """去掉列表项两侧成对的引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_tools_list(meta_text: str) -> List[str]:
    """从原始 frontmatter 文本提取 tools: 列表项。

    支持三种真实写法:块式(`tools:` 之下逐行 `- "X"`/`- X`,容忍缩进与
    注释)、行内方括号(`tools: ["X", "Y"]`)、行内逗号串或单值
    (`tools: Read, Grep, Glob` / `tools: mcp__x__y` —— 真实社区 subagent
    如 wshobson/agents 的常见形态);其余键的取值不会误入列表。
    """
    names: List[str] = []
    in_tools = False
    for line in meta_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key_m = _KEY_LINE_RE.match(stripped)
        if key_m:
            in_tools = key_m.group(1) == "tools"
            if not in_tools:
                continue
            rest = stripped.split(":", 1)[1].strip()
            if not rest or rest in (">", "|", ">-", "|-", ">+", "|+"):
                continue  # 块式:值在后续 - 项
            if rest.startswith("[") and rest.endswith("]"):
                rest = rest[1:-1]
            # 行内形态:方括号展开后 / 裸逗号串 / 单值,统一逗号切分
            names += [
                _unquote(item.strip()) for item in rest.split(",") if item.strip()
            ]
            continue
        if not in_tools:
            continue
        item_m = _LIST_ITEM_RE.match(stripped)
        if item_m:
            name = _unquote(item_m.group(1))
            if name:
                names.append(name)
    return names


_BLOCK_SCALAR_RE = re.compile(r"^(?:[|>][+-]?\d*|[|>])\s+")


def _yaml_unescape(text: str) -> str:
    """还原 YAML 双引号标量的转义(\\ → \\、\\" → "、\\n → 换行)。

    subagent md 的 description 惯用双引号标量;真实文件(如 anthropics/
    skills pptx)值内含 \\" 转义时,emitter 再转义(\\\\"),parser 不反转义
    会逐次漂移(\\" → \\\\\\")。claude-subagent 链 F_desc 的外部真实损耗
    即来源于此。plain 标量(无引号)不含这些序列,单趟扫描对其是恒等变换。
    """
    out: List[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt in ('"', "\\"):
                out.append(nxt)
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _clean_scalar(text: str) -> str:
    """frontmatter 标量清理:剥离块标量前缀 + 还原双引号转义。

    ir.parse_frontmatter 把 `description: >-` 的块标记当作首行值拼进结果
    (真实社区 subagent 的折叠 description 会得到 ">- Image ..."),且不做
    YAML 反转义;两者都在 parser 层修(ir.py 按契约不可改)。
    """
    return _yaml_unescape(_BLOCK_SCALAR_RE.sub("", text, count=1).strip())


def parse_claude_subagent(root: Union[str, Path]) -> AgentIR:
    """解析 Claude Code subagent 目录为 AgentIR(取 .claude/agents/ 第一个 md)。

    frontmatter name/description/model 由 ir.parse_frontmatter 提取(容忍
    额外键如 color:,块标量前缀由 _clean_scalar 剥离);tools 走
    _parse_tools_list(块式/行内方括号/行内逗号);display_name 为 name 的
    title 化;model 存在时写入 metadata["model"]。
    """
    base = Path(root)
    agents_dir = base / ".claude" / "agents"
    agent_md = None
    if agents_dir.is_dir():
        for md in sorted(agents_dir.glob("*.md")):
            if md.is_file():
                agent_md = md
                break
    if agent_md is None:
        raise FileNotFoundError(f"missing .claude/agents/*.md under {base}")

    text = agent_md.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    name = slugify((meta.get("name") or "").strip() or base.name)
    display_name = " ".join(p.capitalize() for p in name.split("-") if p)
    tools = [ToolSpec(name=t) for t in _parse_tools_list(_raw_frontmatter(text))]

    metadata = {
        "source_format": "claude-subagent",
        "source_path": str(agent_md.resolve()),
    }
    model = (meta.get("model") or "").strip()
    if model:
        metadata["model"] = model

    return AgentIR(
        name=name,
        display_name=display_name,
        description=_clean_scalar(meta.get("description", "")),
        system_prompt=body.strip(),
        tools=tools,
        knowledge=collect_knowledge(base),
        metadata=metadata,
    )
