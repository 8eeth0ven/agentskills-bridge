"""LangChain .py 文件 → AgentIR 解析器(AST literal 优先,正则容错)。

提取目标:
    SYSTEM_PROMPT / system_prompt / SYSTEM_MESSAGE 字符串常量 → system_prompt
    @tool 装饰函数名 / StructuredTool(name=...) → ToolSpec(docstring 首段)
        docstring 内的 `schema: {单行 JSON}` / `side-effects: true|false`
        元数据行 → ToolSpec.input_schema / side_effects(emitter 侧
        _tool_docstring 的落点;没有元数据行时保持 name+description 现状)
找不到 prompt 常量时回退:全文第一个 >50 字符的三引号字符串。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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
# 工具 docstring 内的元数据行(与 emitters/langchain._tool_docstring 对应):
# schema 行是单行 JSON;side-effects 行是 true|false 字面量。
_TOOL_SCHEMA_LINE_RE = re.compile(r"^[ \t]*schema:[ \t]*(\{.*\})[ \t]*$", re.MULTILINE)
_TOOL_SIDEEFFECT_LINE_RE = re.compile(
    r"^[ \t]*side-effects:[ \t]*(true|false)[ \t]*$", re.MULTILINE
)


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
    """无执行地解码 Python literal,失败回退已有三引号容错提取。"""
    constants = _module_constants(text)
    for key in ("SYSTEM_PROMPT", "system_prompt", "SYSTEM_MESSAGE"):
        if isinstance(constants.get(key), str):
            return constants[key]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        # A comment or dynamic f-string is not a decoded prompt. For valid
        # modules, the only fallback is an actual module docstring.
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(target, ast.Name) and target.id in ("SYSTEM_PROMPT", "system_prompt", "SYSTEM_MESSAGE") for target in targets):
                return ""
        doc = ast.get_docstring(tree, clean=False) or ""
        return doc.strip() if len(doc.strip()) > 50 else ""
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


def _module_constants(text: str) -> Dict[str, Any]:
    """只读取模块顶层 literal 常量,不执行源文件或导入其中依赖。"""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    constants: Dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            names, value = [node.target], node.value
        else:
            continue
        try:
            literal = ast.literal_eval(value)
        except (TypeError, ValueError, SyntaxError):
            continue
        for name in names:
            if isinstance(name, ast.Name):
                constants[name.id] = literal
    return constants


def _docstring_value(raw: str, delim: str) -> str:
    """docstring 源码捕获组 → 运行时值(经 _literal_eval 还原转义)。"""
    if not raw:
        return ""
    return _literal_eval(raw, delim)


def _tool_meta_from_docstring(doc_value: str) -> Tuple[Dict[str, Any], bool]:
    """从 docstring 运行时值提取 schema:/side-effects: 元数据行。

    与 emitters/langchain._tool_docstring 互逆:返回 (input_schema,
    side_effects);没有对应行时 schema 为空 dict、side_effects 为 False,
    即 name-only 工具保持现状。JSON 非法时同样按缺省处理(best-effort)。
    """
    schema: Dict[str, Any] = {}
    m = _TOOL_SCHEMA_LINE_RE.search(doc_value or "")
    if m:
        try:
            loaded = json.loads(m.group(1))
        except ValueError:
            loaded = None
        if isinstance(loaded, dict):
            schema = loaded
    se = _TOOL_SIDEEFFECT_LINE_RE.search(doc_value or "")
    return schema, bool(se and se.group(1) == "true")


def _extract_tools(text: str) -> List[ToolSpec]:
    """@tool 装饰函数 + StructuredTool(name=...) → ToolSpec(按名去重)。"""
    tools: List[ToolSpec] = []
    seen = set()

    # Literal AST decoding avoids regex quote truncation and fixed docstring windows.
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tool_name = None
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call is not None else decorator
                leaf = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
                if leaf != "tool":
                    continue
                tool_name = node.name
                if call is not None and call.args:
                    if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                        tool_name = call.args[0].value
                if call is not None:
                    for kw in call.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            tool_name = kw.value.value
            if tool_name is None or tool_name in seen:
                continue
            doc_value = ast.get_docstring(node, clean=False) or ""
            schema, side_effects = _tool_meta_from_docstring(doc_value)
            seen.add(tool_name)
            tools.append(ToolSpec(name=tool_name, description=_first_paragraph(doc_value),
                                  input_schema=schema, side_effects=side_effects))

    for m in (() if tree is not None else _TOOL_DEF_RE.finditer(text)):
        name = m.group(1)
        if name in seen:
            continue
        doc = re.search(r"\"\"\"(.*?)\"\"\"|'''(.*?)'''", text[m.end(): m.end() + 2000], re.DOTALL)
        desc = ""
        schema: Dict[str, Any] = {}
        side_effects = False
        if doc:
            if doc.group(1) is not None:
                value = _docstring_value(doc.group(1), '"""')
            else:
                value = _docstring_value(doc.group(2), "'''")
            desc = _first_paragraph(value)
            schema, side_effects = _tool_meta_from_docstring(value)
        seen.add(name)
        tools.append(
            ToolSpec(name=name, description=desc, input_schema=schema, side_effects=side_effects)
        )

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

    constants = _module_constants(text)
    try:
        ast.parse(text)
        valid_python = True
    except (SyntaxError, ValueError):
        valid_python = False
    m_name = None if valid_python else _AGENT_NAME_CONST_RE.search(text)
    m_desc = None if valid_python else _SKILL_DESC_CONST_RE.search(text)
    raw_name = constants.get("AGENT_NAME")
    name = slugify(raw_name) if isinstance(raw_name, str) else slugify(m_name.group(1)) if m_name else slugify(path.stem)
    title = " ".join(p.capitalize() for p in name.split("-") if p) or path.stem
    if isinstance(constants.get("SKILL_DESCRIPTION"), str):
        first_sentence = constants["SKILL_DESCRIPTION"]
    elif m_desc:
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
