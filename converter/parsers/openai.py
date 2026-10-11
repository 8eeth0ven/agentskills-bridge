"""OpenAI/Codex agent 目录 → AgentIR 解析器。

root 指向 openai_agents emitter 产出的目录:
    instructions.md      完整 system_prompt(缺失抛 FileNotFoundError)
    agents/openai.yaml   interface: display_name/short_description/default_prompt
    knowledge/*.md       collect_knowledge 回收

openai.yaml 是嵌套结构(interface.display_name),与 skill_loader 读取
agents/*.yaml 的场景同源,故直接复用其 extract_interface_fields()。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Union

try:
    from converter.ir import AgentIR, ToolSpec, slugify
    from converter.parsers.knowledge import collect_knowledge
    from converter.skill_loader import extract_interface_fields
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, ToolSpec, slugify  # type: ignore
    from ..skill_loader import extract_interface_fields  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore


def _first_body_line(text: str) -> str:
    """取首个非标题、非空行并单行化(description 兜底)。"""
    for line in (text or "").splitlines():
        flat = " ".join(line.split())
        if flat and not flat.startswith("#"):
            return flat
    return ""


_XSKILL_NAME_RE = re.compile(r"^\s*name:\s*[\"']?([^\"'\n#]+?)[\"']?\s*$", re.MULTILINE)
_XSKILL_DESC_RE = re.compile(r"^\s*description:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)
# x-source-skill 段内的 tools: 单行 JSON 数组(emitter 写出的流式序列)
_XSKILL_TOOLS_RE = re.compile(r"^\s*tools:\s*(\[.*\])\s*$", re.MULTILINE)


def _x_source_skill(yaml_text: str) -> dict:
    """提取 x-source-skill: 段下的 name/description(转换器私有扩展)。"""
    out: dict = {}
    m = re.search(r"^x-source-skill:\s*$", yaml_text, re.MULTILINE)
    if not m:
        return out
    section = yaml_text[m.end():]
    stop = re.search(r"^\S", section, re.MULTILINE)
    if stop:
        section = section[: stop.start()]
    m = _XSKILL_NAME_RE.search(section)
    if m:
        out["name"] = m.group(1).strip()
    m = _XSKILL_DESC_RE.search(section)
    if m:
        out["description"] = m.group(1).strip()
    m = _XSKILL_TOOLS_RE.search(section)
    if m:
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            out["tools"] = data
    return out


def _x_tools_to_specs(raw: object) -> List[ToolSpec]:
    """x-source-skill.tools(JSON 数组)→ ToolSpec 列表;形态非法时空列表。"""
    if not isinstance(raw, list):
        return []
    return [ToolSpec.from_dict(t) for t in raw if isinstance(t, dict)]


def parse_openai(root: Union[str, Path]) -> AgentIR:
    """解析 OpenAI/Codex agent 定义目录为 AgentIR。

    name = slugify(display_name 或目录名);description = short_description
    或 instructions.md 首个非标题非空行;interface 字段容忍 openai.yaml 缺失。
    """
    base = Path(root)
    instructions = base / "instructions.md"
    if not instructions.is_file():
        raise FileNotFoundError(f"missing instructions.md: {instructions}")
    system_prompt = instructions.read_text(encoding="utf-8").strip()

    display_name = ""
    short_description = ""
    default_prompt = ""
    xskill: dict = {}
    yaml_file = base / "agents" / "openai.yaml"
    if yaml_file.is_file():
        yaml_text = yaml_file.read_text(encoding="utf-8")
        fields = extract_interface_fields(yaml_text)
        display_name = fields.get("display_name", "")
        short_description = fields.get("short_description", "")
        default_prompt = fields.get("default_prompt", "")
        xskill = _x_source_skill(yaml_text)

    name = slugify(xskill.get("name") or display_name or base.name)
    description = (
        xskill.get("description")
        or short_description
        or _first_body_line(system_prompt)
    )

    return AgentIR(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=system_prompt,
        default_prompt=default_prompt,
        tools=_x_tools_to_specs(xskill.get("tools")),
        knowledge=collect_knowledge(base),
        metadata={
            "source_format": "openai",
            "source_path": str(base.resolve()),
            "short_description": short_description,
        },
    )
