"""SKILL.md 正文 → 工作流步骤提取器(skill→workflow 转换的语义层)。

extract_workflow_steps():纯函数,从 markdown 正文识别"工作流步骤"。识别优先级:
    a. 标题含 workflow/流程/工作流/生命周期/lifecycle 的 ##(或更深)节下的
       编号列表项(1. / 1、 / 1) / （1） / 步骤一 / 一、)
    b. 无上述节:全文任何连续 ≥3 项、编号从 0/1 起连续递增的编号列表
    c. `### Step N: xxx` / `## Step N` 形态的标题序列
    d. 都没有 → []

健壮性:fenced code block(``` / ~~~)内的行一律跳过,不参与编号识别;
中英编号、全半角括号/数字、嵌套子列表(缩进更深)都按原意归属。

skill_to_workflow_ir():skill 目录 → load_skill → AgentIR → 步骤 → WorkflowIR。
converter/wir.py 由并行线程提供,未就绪时抛 ImportError("wir pending")。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

try:
    from converter.ir import slugify
    from converter.skill_loader import load_skill
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from .ir import slugify  # type: ignore
    from .skill_loader import load_skill  # type: ignore

__all__ = ["extract_workflow_steps", "skill_to_workflow_ir"]

# ---------------------------------------------------------------------------
# 常量与正则
# ---------------------------------------------------------------------------

#: workflow 关键词(标题命中即认定该节为工作流节)
_WORKFLOW_HEADING_RE = re.compile(
    r"workflow|流程|工作流|生命周期|life[\s-]?cycle", re.IGNORECASE
)

#: markdown 标题(# 号后带文本)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

#: fenced code block 起始/结束(``` 或 ~~~,最多 3 空格缩进)
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")

#: `## Step N: xxx` / `### Step N` 形态的标题
_STEP_HEADING_RE = re.compile(
    r"^#{1,6}\s*step\s*(\d{1,3})\s*[\.、:：\-—－]?\s*(.*)$", re.IGNORECASE
)

#: 版本号样数字("1.5 million"),避免被当成编号列表项
_VERSION_RE = re.compile(r"^\s*\d{1,3}\s*\.\d")

#: 全角→半角(逐字符等长映射,因此正则匹配位置可回映到原文)
_FW_MAP = str.maketrans(
    {
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "（": "(", "）": ")", "．": ".",
    }
)

#: 编号列表项形态(按顺序尝试;匹配对象为全角归一化后的行)
_ITEM_PATTERNS = [
    # 1. text / 1.收集(无空格) / 1、text / 1) text / 1）text
    re.compile(r"^(\d{1,3})\s*[\.、)）]\s*(.+)$"),
    # (1) text / （1） text / (1)、text
    re.compile(r"^[（(]\s*(\d{1,3})\s*[)）]\s*[\.、]?\s*(.+)$"),
    # 步骤1: text / 步骤一:text(分隔符必写,避免误吞"步骤一样")
    re.compile(r"^步骤\s*([0-9一二三四五六七八九十]{1,3})\s*[\.、:：)）]\s*(.+)$"),
    # 一、text / 一．text
    re.compile(r"^([一二三四五六七八九十]{1,3})\s*[、．]\s*(.+)$"),
]

_ZH_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

#: title 取首句时的分隔符(冒号/句号;西文句点在 _first_sentence 里单独处理)
_TITLE_SEPARATORS = (":", "：", "。", ";", "；")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _to_int(token: str) -> Optional[int]:
    """编号 token → int;支持阿拉伯数字与一~九十九的中文数字,非法返回 None。"""
    if token.isdigit():
        return int(token)
    if len(token) == 1:
        return _ZH_DIGITS.get(token)
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _ZH_DIGITS.get(left, 1) if left else 1
        ones = _ZH_DIGITS.get(right, 0) if right else 0
        if (left and left not in _ZH_DIGITS) or (right and right not in _ZH_DIGITS):
            return None
        return tens * 10 + ones
    return None


def _match_item(raw: str) -> Optional[Tuple[int, str]]:
    """判断一行是否编号列表项。返回 (编号, 项文本);非列表项返回 None。

    匹配在全角归一化副本上进行(translate 逐字符等长,切片位置可回映原文,
    正文里的全角字符保持原样)。版本号形态("1.5 …")先被排除。
    """
    norm = raw.translate(_FW_MAP)
    if _VERSION_RE.match(norm):
        return None
    for pat in _ITEM_PATTERNS:
        m = pat.match(norm)
        if not m:
            continue
        num = _to_int(m.group(1))
        if num is None:
            return None
        # 用原文切片取正文,保留正文中的全角字符
        text = raw[m.start(2): m.end(2)].strip()
        if not text:
            return None
        return num, text
    return None


def _tag_fences(lines: List[str]) -> List[Tuple[str, bool]]:
    """给每行打 (原文, 是否在 fenced code block 内) 标记。围栏行本身算块内。"""
    tagged: List[Tuple[str, bool]] = []
    fence: Optional[str] = None
    for line in lines:
        m = _FENCE_RE.match(line)
        if fence is None:
            inside = bool(m)
            if m:
                fence = m.group(1)
        else:
            inside = True
            if m and line.lstrip().startswith(fence):
                fence = None
        tagged.append((line, inside))
    return tagged


def _first_sentence(text: str, max_chars: int = 120) -> str:
    """取首句作 step 标题:到冒号/句号为止;无分隔符则截断到 max_chars。"""
    t = re.sub(r"[*_`#]+", " ", text or "").strip()
    if not t:
        return ""
    for i, ch in enumerate(t):
        if ch in _TITLE_SEPARATORS:
            head = t[:i].strip()
            if head:
                return head
            break
    m = re.search(r"\.(?:\s|$)", t)  # 西文句点:后随空白/行尾,避开 "v1.2"
    if m:
        head = t[: m.start()].strip()
        if head:
            return head
    if len(t) > max_chars:
        return t[:max_chars].rstrip() + "…"
    return t


# ---------------------------------------------------------------------------
# 编号列表 run 收集
# ---------------------------------------------------------------------------

def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _collect_runs(tagged: List[Tuple[str, bool]]) -> List[List[Dict[str, object]]]:
    """把行流切成"编号连续递增的列表 run"。

    规则:
    - 编号项只在其缩进 <= 当前 run 首项缩进时开启新步骤;缩进更深的编号行
      (嵌套子列表)与普通缩进行都归属当前项的 extra;
    - 项与项之间只允许空行(松散列表);出现段落/标题等非缩进行即中断 run;
    - fenced 代码块:开栏线缩进比列表项更深时归属该步骤正文(步骤内代码
      示例);开栏线在列表缩进层(如列 0)则按 markdown 语义打断列表,
      块内编号一律忽略。
    每个 item: {"num": int, "text": str, "extra": [str], "base_indent": int}
    """
    runs: List[List[Dict[str, object]]] = []
    cur_run: List[Dict[str, object]] = []
    cur_item: Optional[Dict[str, object]] = None
    broken = False  # 上一项之后是否出现过硬中断(段落/标题)
    fence_attached = False  # 当前 fenced 块是否归属开放项

    def close_item() -> None:
        nonlocal cur_item
        if cur_item is not None:
            extra = cur_item["extra"]
            assert isinstance(extra, list)
            while extra and not str(extra[-1]).strip():
                extra.pop()
            cur_run.append(cur_item)
            cur_item = None

    def close_run() -> None:
        nonlocal cur_run, broken
        close_item()
        if cur_run:
            runs.append(cur_run)
        cur_run = []
        broken = False

    for idx, (raw, in_fence) in enumerate(tagged):
        if in_fence:
            prev_in = tagged[idx - 1][1] if idx > 0 else False
            next_in = tagged[idx + 1][1] if idx + 1 < len(tagged) else False
            if not prev_in:  # 开栏线
                if cur_item is not None and _indent_of(raw) > int(cur_item["base_indent"]):  # type: ignore[arg-type]
                    fence_attached = True
                    cur_item["extra"].append(raw)
                else:  # 列表缩进层上的代码块 → 打断列表
                    if cur_item is not None:
                        close_item()
                        broken = True
                    fence_attached = False
            elif fence_attached and cur_item is not None:
                cur_item["extra"].append(raw)  # 块内(含闭栏线)都是步骤正文
                if not next_in:
                    fence_attached = False
            continue
        stripped = raw.strip()
        if not stripped:
            if cur_item is not None:
                cur_item["extra"].append("")
            continue
        indent = _indent_of(raw)
        m = _match_item(raw)
        same_level_new = m is not None and (
            cur_item is None or indent <= int(cur_item["base_indent"])  # type: ignore[arg-type]
        )
        if same_level_new:
            assert m is not None
            num, text = m
            close_item()  # 把上一项落进 cur_run
            item = {"num": num, "text": text, "extra": [], "base_indent": indent}
            if not (
                cur_run
                and not broken
                and int(cur_run[-1]["num"]) == num - 1  # type: ignore[arg-type]
            ):
                close_run()  # 编号不连续或被段落中断 → 另起 run
            cur_item = item  # 开放项:close 时才进 run
            continue
        if cur_item is None:
            if cur_run:
                broken = True  # 两项之间出现了段落/标题等硬中断
            continue
        if indent > int(cur_item["base_indent"]):  # type: ignore[arg-type]
            cur_item["extra"].append(raw)  # 子项/缩进续行
        else:
            close_item()
            broken = True
    close_run()
    return runs


def _pick_run(
    runs: List[List[Dict[str, object]]], min_items: int
) -> Optional[List[Dict[str, object]]]:
    """取第一个长度达标且编号从 0/1 起的 run。"""
    for run in runs:
        if len(run) >= min_items and int(run[0]["num"]) in (0, 1):
            return run
    return None


def _run_to_steps(run: List[Dict[str, object]]) -> List[Dict[str, str]]:
    """run → [{"title", "body"}];body = 首行文本 + 子项缩进内容(原文保留)。"""
    steps: List[Dict[str, str]] = []
    for item in run:
        text = str(item["text"])
        extra = [str(x) for x in item["extra"]]  # type: ignore[arg-type]
        body = "\n".join([text] + extra).rstrip()
        steps.append({"title": _first_sentence(text), "body": body})
    return steps


# ---------------------------------------------------------------------------
# 三种识别形态
# ---------------------------------------------------------------------------

def _find_workflow_section(
    tagged: List[Tuple[str, bool]]
) -> Optional[List[Tuple[str, bool]]]:
    """返回第一个标题命中 workflow 关键词的 ##(或更深)节的正文行;无则 None。"""
    start: Optional[int] = None
    level = 0
    for idx, (line, in_fence) in enumerate(tagged):
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if not m:
            continue
        lvl = len(m.group(1))
        if start is None:
            if lvl >= 2 and _WORKFLOW_HEADING_RE.search(m.group(2)):
                start, level = idx, lvl
        elif lvl <= level:  # 同级或更高级标题 → 节结束
            return tagged[start + 1: idx]
    if start is not None:
        return tagged[start + 1:]
    return None


def _collect_step_headings(
    tagged: List[Tuple[str, bool]]
) -> List[Dict[str, str]]:
    """形态 c:`## Step N: xxx` 标题序列 → [{"title", "body"}]。

    只保留编号连续递增、从 0/1 起的子序列;不足 2 个标题不算序列。
    """
    raw_steps: List[Dict[str, object]] = []
    cur: Optional[Dict[str, object]] = None
    for line, in_fence in tagged:
        m = None if in_fence else _STEP_HEADING_RE.match(line.strip())
        if m is not None:
            if cur is not None:
                raw_steps.append(cur)
            num = int(m.group(1))
            title = m.group(2).strip() or f"Step {num}"
            cur = {"num": num, "title": title, "extra": []}
        elif cur is not None:
            cur["extra"].append(line)  # 标题下的全部内容(含代码块)都归正文
    if cur is not None:
        raw_steps.append(cur)

    # 按编号连续性切段,取第一段长度 ≥2 且从 0/1 起的
    seqs: List[List[Dict[str, object]]] = []
    seq: List[Dict[str, object]] = []
    for st in raw_steps:
        if seq and int(st["num"]) == int(seq[-1]["num"]) + 1:
            seq.append(st)
        else:
            if seq:
                seqs.append(seq)
            seq = [st]
    if seq:
        seqs.append(seq)
    for s in seqs:
        if len(s) >= 2 and int(s[0]["num"]) in (0, 1):
            return [
                {
                    "title": str(st["title"]),
                    "body": "\n".join(str(x) for x in st["extra"]).strip(),  # type: ignore[arg-type]
                }
                for st in s
            ]
    return []


def extract_workflow_steps(markdown_text: str) -> List[Dict[str, str]]:
    """从 skill 正文(markdown)识别工作流步骤,返回 [{"title", "body"}]。

    识别优先级 a(workflow 节编号列表) > b(全文编号列表 ≥3) >
    c(Step N 标题序列) > [](无形态)。顺序保留;fenced code block
    内的编号不会被误提。
    """
    if not markdown_text or not markdown_text.strip():
        return []
    tagged = _tag_fences(markdown_text.splitlines())

    # a. workflow/流程节下的编号列表
    section = _find_workflow_section(tagged)
    if section is not None:
        run = _pick_run(_collect_runs(section), min_items=2)
        if run:
            return _run_to_steps(run)

    # b. 全文任何连续 ≥3 项的编号列表
    run = _pick_run(_collect_runs(tagged), min_items=3)
    if run:
        return _run_to_steps(run)

    # c. `## Step N: xxx` 标题序列
    steps = _collect_step_headings(tagged)
    if steps:
        return steps

    # d. 无形态
    return []


# ---------------------------------------------------------------------------
# skill 目录 → WorkflowIR
# ---------------------------------------------------------------------------

def skill_to_workflow_ir(skill_dir: Union[str, Path]):
    """skill 目录 → AgentIR → 工作流步骤 → WorkflowIR。

    converter/wir.py 未就绪时抛 ImportError("wir pending")。
    有步骤:每步一个 WorkflowNode(id=slugify(title)[:40]),按顺序连边;
    无步骤:委托 WorkflowIR.from_agent_ir(ir)(单节点/tasks 兜底)。
    metadata["steps_extracted"] 记录提取到的步骤数。
    """
    try:
        from converter.wir import WorkflowEdge, WorkflowIR, WorkflowNode
    except ImportError:
        raise ImportError("wir pending")

    ir = load_skill(skill_dir)
    steps = extract_workflow_steps(ir.system_prompt)
    metadata = dict(ir.metadata or {})
    metadata["steps_extracted"] = len(steps)

    if steps:
        used: set = set()
        nodes = []
        for i, step in enumerate(steps):
            base = slugify(step["title"] or f"step {i + 1}", fallback=f"step-{i + 1}")[:40]
            node_id = base
            n = 2
            while node_id in used:  # 同名/中文空 slug 兜底去重
                node_id = f"{base}-{n}"[:44]
                n += 1
            used.add(node_id)
            nodes.append(
                WorkflowNode(
                    id=node_id,
                    name=step["title"],
                    kind="agent",
                    prompt=step["body"],
                    description=step["body"][:200],
                )
            )
        edges = [
            WorkflowEdge(source=nodes[i].id, target=nodes[i + 1].id, label="")
            for i in range(len(nodes) - 1)
        ]
        return WorkflowIR(
            name=ir.name,
            display_name=ir.display_name or ir.title(),
            description=ir.description,
            knowledge=list(ir.knowledge),
            nodes=nodes,
            edges=edges,
            metadata=metadata,
        )

    workflow = WorkflowIR.from_agent_ir(ir)
    try:
        merged = {**(getattr(workflow, "metadata", None) or {}), "steps_extracted": 0}
        workflow.metadata = merged
    except Exception:  # pragma: no cover - 冻结 dataclass 等极端情况
        pass
    return workflow
