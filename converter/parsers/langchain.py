"""LangChain .py 文件 → AgentIR 解析器(best-effort 正则提取)。

提取目标:
    SYSTEM_PROMPT / system_prompt / SYSTEM_MESSAGE 三引号常量 → system_prompt
    @tool 装饰函数名 / StructuredTool(name=...) → ToolSpec(docstring 首段)
找不到 prompt 常量时回退:全文第一个 >50 字符的三引号字符串。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Union

try:
    from converter.ir import AgentIR, ToolSpec, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, ToolSpec, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore

_PROMPT_CONST_RE = re.compile(
    r"\b(SYSTEM_PROMPT|system_prompt|SYSTEM_MESSAGE)\s*=\s*[rbfu]{0,2}"
    r"(?:\"\"\"(.*?)\"\"\"|'''(.*?)''')",
    re.DOTALL,
)
_AGENT_NAME_CONST_RE = re.compile(r"\bAGENT_NAME\s*=\s*[\"']([^\"'\n]+)[\"']")
_SKILL_DESC_CONST_RE = re.compile(r"\bSKILL_DESCRIPTION\s*=\s*[\"']([^\"'\n]+)[\"']")
_TRIPLE_QUOTE_RE = re.compile(r"\"\"\"(.*?)\"\"\"|'''(.*?)'''", re.DOTALL)
_TOOL_DEF_RE = re.compile(
    r"@[A-Za-z_.]*tool(?:\([^)]*\))?[^\n]*\n\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
    re.IGNORECASE,
)
_STRUCTURED_TOOL_RE = re.compile(r"StructuredTool\s*\(")
_KV_NAME_RE = re.compile(r"\bname\s*=\s*[\"']([^\"']+)[\"']")
_KV_DESC_RE = re.compile(r"\bdescription\s*=\s*[\"']([^\"']*)[\"']")


def _first_paragraph(text: str) -> str:
    """docstring 首段:到第一个空行为止,换行折叠为空格。"""
    para = (text or "").split("\n\n")[0]
    return " ".join(para.split())


def _literal_eval(value: str, delim: str) -> str:
    """按 Python 字面量语义还原提取文本(`\\s` -> `\\s` 值、转义定界符等)。

    emitter 侧(_py_triple)对正文做了反斜杠双写与定界符转义,直接取正则
    捕获组会拿到"源码字面"而非"运行时值"(评测 langchain S2_cn F_prompt
    0.997 的根因);ast.literal_eval 完整还原,失败时回退原文本。
    """
    try:
        import ast

        restored = ast.literal_eval(delim + value + delim)
        return restored if isinstance(restored, str) else value
    except Exception:  # noqa: BLE001 - 非法字面量按原文处理
        return value


def _extract_system_prompt(text: str) -> str:
    """先找 prompt 常量赋值,失败回退全文第一个 >50 字符三引号字符串。"""
    for m in _PROMPT_CONST_RE.finditer(text):
        if m.group(2) is not None:
            value = _literal_eval(m.group(2), '"""')
        else:
            value = _literal_eval(m.group(3), "'''")
        if value and value.strip():
            return value.strip()
    for m in _TRIPLE_QUOTE_RE.finditer(text):
        if m.group(1) is not None:
            value = _literal_eval(m.group(1), '"""')
        else:
            value = _literal_eval(m.group(2), "'''")
        if value and len(value.strip()) > 50:
            return value.strip()
    return ""


def _extract_tools(text: str) -> List[ToolSpec]:
    """@tool 装饰函数 + StructuredTool(name=...) → ToolSpec(按名去重)。"""
    tools: List[ToolSpec] = []
    seen = set()

    for m in _TOOL_DEF_RE.finditer(text):
        name = m.group(1)
        if name in seen:
            continue
        doc = re.search(r"\"\"\"(.*?)\"\"\"|'''(.*?)'''", text[m.end(): m.end() + 2000], re.DOTALL)
        desc = ""
        if doc:
            raw = doc.group(1) if doc.group(1) is not None else doc.group(2)
            desc = _first_paragraph(raw or "")
        seen.add(name)
        tools.append(ToolSpec(name=name, description=desc))

    for m in _STRUCTURED_TOOL_RE.finditer(text):
        window = text[m.end(): m.end() + 800]
        name_m = _KV_NAME_RE.search(window)
        if not name_m or name_m.group(1) in seen:
            continue
        desc_m = _KV_DESC_RE.search(window)
        desc = _first_paragraph(desc_m.group(1)) if desc_m else ""
        seen.add(name_m.group(1))
        tools.append(ToolSpec(name=name_m.group(1), description=desc))

    return tools


def parse_langchain(py_file: Union[str, Path]) -> AgentIR:
    """best-effort 从 langchain 风格 .py 提取 AgentIR。

    文件不存在抛 FileNotFoundError;什么都没提取到时返回空壳 IR。
    """
    path = Path(py_file)
    if path.is_dir():
        # 目录形态(如 agent2skill 传产物根):自动定位 agent.py,退化到唯一 .py
        cand = path / "agent.py"
        if cand.is_file():
            path = cand
        else:
            pys = sorted(path.glob("*.py"))
            if not pys:
                raise FileNotFoundError(f"no .py under: {path}")
            path = pys[0]
    if not path.is_file():
        raise FileNotFoundError(f"missing langchain source: {path}")
    text = path.read_text(encoding="utf-8")

    system_prompt = _extract_system_prompt(text)
    tools = _extract_tools(text)

    m_name = _AGENT_NAME_CONST_RE.search(text)
    m_desc = _SKILL_DESC_CONST_RE.search(text)
    name = slugify(m_name.group(1)) if m_name else slugify(path.stem)
    title = " ".join(p.capitalize() for p in name.split("-") if p) or path.stem
    if m_desc:
        first_sentence = m_desc.group(1).strip()
    else:
        first_sentence = system_prompt.split(". ")[0].strip() if system_prompt else ""

    return AgentIR(
        name=name,
        display_name=title,
        description=first_sentence,
        system_prompt=system_prompt,
        tools=tools,
        knowledge=collect_knowledge(path.parent),
        metadata={
            "source_format": "langchain",
            "source_path": str(path.resolve()),
        },
    )
