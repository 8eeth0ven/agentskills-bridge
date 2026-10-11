"""AutoGen (AG2) .py 文件 → AgentIR 解析器(best-effort 正则提取)。

提取目标(优先级从高到低):
    AGENT_NAME / SKILL_DESCRIPTION 单行常量 → name / description
    SYSTEM_MESSAGE / SYSTEM_PROMPT / system_message 三引号常量 → system_prompt
        (复用 parsers/langchain.py 的 _extract_system_prompt + _literal_eval,
        含转义还原:反斜杠双写、定界符转义都会还原成运行时值)
    AssistantAgent(name=..) / ConversableAgent(name=..) 调用参数 → name 兜底
    system_message="..." 构造参数内联字符串 → system_prompt 兜底
    TOOLS = [...] 清单 + 对应函数 docstring → ToolSpec(best-effort)
找不到 name 时回退文件名词干;找不到 prompt 常量时回退全文第一个 >50 字符
三引号字符串。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Union

try:
    from converter.ir import AgentIR, ToolSpec, slugify
    from converter.parsers.knowledge import collect_knowledge
    from converter.parsers.langchain import _extract_system_prompt, _literal_eval
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, ToolSpec, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore
    from .langchain import _extract_system_prompt, _literal_eval  # type: ignore

_AGENT_NAME_CONST_RE = re.compile(r"\bAGENT_NAME\s*=\s*[\"']([^\"'\n]+)[\"']")
_SKILL_DESC_CONST_RE = re.compile(r"\bSKILL_DESCRIPTION\s*=\s*[\"']([^\"'\n]+)[\"']")
# AssistantAgent(...) / ConversableAgent(...) 构造调用 → 在其后窗口找 name=...
_AGENT_CTOR_RE = re.compile(r"\b(?:AssistantAgent|ConversableAgent)\s*\(")
_KV_NAME_RE = re.compile(r"\bname\s*=\s*[\"']([^\"'\n]+)[\"']")
# 构造参数里的内联 system_message 字符串(常量引用形态由 _extract_system_prompt 覆盖)
_KV_SYSMSG_INLINE_RE = re.compile(
    r"\bsystem_message\s*=\s*(?P<lit>\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*')"
)
_TOOLS_LIST_RE = re.compile(r"\bTOOLS\s*=\s*\[([^\]]*)\]")
_DEF_RE = re.compile(r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
_DOCSTRING_RE = re.compile(r"\"\"\"(.*?)\"\"\"|'''(.*?)'''", re.DOTALL)


def _first_paragraph(text: str) -> str:
    """docstring 首段:到第一个空行为止,换行折叠为空格。"""
    para = (text or "").split("\n\n")[0]
    return " ".join(para.split())


def _extract_name(text: str, fallback: str) -> str:
    """AGENT_NAME 常量 → AssistantAgent/ConversableAgent(name=..) → 文件名词干。"""
    m = _AGENT_NAME_CONST_RE.search(text)
    if m:
        return slugify(m.group(1))
    for ctor in _AGENT_CTOR_RE.finditer(text):
        window = text[ctor.end(): ctor.end() + 800]
        m = _KV_NAME_RE.search(window)
        if m:
            return slugify(m.group(1))
    return slugify(fallback)


def _extract_system_message(text: str) -> str:
    """SYSTEM_MESSAGE 等常量(含 literal_eval 转义还原)→ 内联构造参数兜底。"""
    prompt = _extract_system_prompt(text)
    if prompt:
        return prompt
    for m in _KV_SYSMSG_INLINE_RE.finditer(text):
        lit = m.group("lit")
        value = _literal_eval(lit[1:-1], lit[0])
        if value and len(value.strip()) >= 20:
            return value.strip()
    return ""


def _extract_tools(text: str) -> List[ToolSpec]:
    """TOOLS = [fn, ...] 清单里的函数 → ToolSpec(docstring 首段,按名去重)。"""
    m = _TOOLS_LIST_RE.search(text)
    if not m:
        return []
    idents = re.findall(r"[A-Za-z_]\w*", m.group(1))
    tools: List[ToolSpec] = []
    for ident in idents:
        def_m = None
        for dm in _DEF_RE.finditer(text):
            if dm.group(1) == ident:
                def_m = dm
                break
        if def_m is None:
            continue
        doc = _DOCSTRING_RE.search(text[def_m.end(): def_m.end() + 2000])
        raw = ""
        if doc:
            raw = doc.group(1) if doc.group(1) is not None else doc.group(2)
        tools.append(ToolSpec(name=ident, description=_first_paragraph(raw or "")))
    return tools


def parse_autogen(path: Union[str, Path]) -> AgentIR:
    """best-effort 从 AutoGen (AG2) 风格 .py / 产物目录提取 AgentIR。

    path 为目录时自动定位 agent.py,退化到目录下唯一 .py;文件不存在抛
    FileNotFoundError;什么都没提取到时返回空壳 IR。
    """
    src = Path(path)
    if src.is_dir():
        cand = src / "agent.py"
        if cand.is_file():
            src = cand
        else:
            pys = sorted(src.glob("*.py"))
            if not pys:
                raise FileNotFoundError(f"no .py under: {src}")
            src = pys[0]
    if not src.is_file():
        raise FileNotFoundError(f"missing autogen source: {src}")
    text = src.read_text(encoding="utf-8")

    name = _extract_name(text, src.stem)
    title = " ".join(p.capitalize() for p in name.split("-") if p) or src.stem
    system_message = _extract_system_message(text)
    tools = _extract_tools(text)

    m_desc = _SKILL_DESC_CONST_RE.search(text)
    if m_desc:
        description: Optional[str] = m_desc.group(1).strip()
    else:
        description = system_message.split(". ")[0].strip() if system_message else ""

    return AgentIR(
        name=name,
        display_name=title,
        description=description or "",
        system_prompt=system_message,
        tools=tools,
        knowledge=collect_knowledge(src.parent),
        metadata={
            "source_format": "autogen",
            "source_path": str(src.resolve()),
        },
    )
