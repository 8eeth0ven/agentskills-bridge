"""skill 目录 → AgentIR 加载层。

读取契约规定的 skill 目录结构:
    SKILL.md          frontmatter(name/description)+ 正文(system_prompt)
    agents/*.yaml     interface.display_name / short_description / default_prompt
    references/*.md   KnowledgeDoc 列表(一级目录内直接文件)
    scripts/*         相对路径列表

agents/*.yaml 是嵌套结构(interface.display_name),ir.parse_frontmatter 只支持
平面字段,故用本模块的 extract_interface_fields() 做容忍式提取。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Union

try:
    from converter.ir import AgentIR, KnowledgeDoc, parse_frontmatter, slugify
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from .ir import AgentIR, KnowledgeDoc, parse_frontmatter, slugify  # type: ignore


def _strip_quotes(value: str) -> str:
    """去掉 YAML 标量两侧成对的引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def extract_interface_fields(text: str) -> Dict[str, str]:
    """从 yaml 文本中提取 interface: 块下的三个字段。

    只识别 display_name / short_description / default_prompt,容忍字段缺失、
    注释行、空行;interface: 块本身缺失时返回空 dict。
    """
    fields: Dict[str, str] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        if not indented:
            key = line.split(":", 1)[0].strip()
            in_block = key == "interface"
            continue
        if not in_block:
            continue
        m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if key in ("display_name", "short_description", "default_prompt") and value:
            fields[key] = _strip_quotes(value)
    return fields


def _first_sentence(text: str, max_chars: int = 120) -> str:
    """取首句(用于 short_description 兜底),并裁剪到 max_chars 内。"""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    m = re.match(r"^[^.!?]*[.!?]", flat)
    snippet = (m.group(0) if m else flat).strip()
    return snippet[:max_chars].rstrip()


def load_skill(skill_dir: Union[str, Path]) -> AgentIR:
    """把 skill 目录读成 AgentIR。

    SKILL.md 缺失抛 FileNotFoundError("missing SKILL.md: ...");
    agents/ 与 references/ 与 scripts/ 缺失一律容忍(空集合)。
    """
    skill_path = Path(skill_dir)
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"missing SKILL.md: {skill_md}")

    text = skill_md.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    name = (meta.get("name") or "").strip() or slugify(skill_path.name)
    description = meta.get("description", "")

    # agents/*.yaml → interface 三字段(先到先得)
    display_name = ""
    default_prompt = ""
    short_description = ""
    agents_dir = skill_path / "agents"
    if agents_dir.is_dir():
        for yml in sorted(
            p for p in agents_dir.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml")
        ):
            try:
                fields = extract_interface_fields(yml.read_text(encoding="utf-8"))
            except OSError:
                continue
            display_name = display_name or fields.get("display_name", "")
            default_prompt = default_prompt or fields.get("default_prompt", "")
            short_description = short_description or fields.get("short_description", "")

    # references/*.md → KnowledgeDoc(一级目录内直接文件)
    knowledge = []
    refs_dir = skill_path / "references"
    if refs_dir.is_dir():
        for md in sorted(refs_dir.glob("*.md")):
            if not md.is_file():
                continue
            content = md.read_text(encoding="utf-8")
            m = re.search(r"^# (.+?)\s*$", content, re.MULTILINE)
            title = m.group(1).strip() if m else md.stem
            knowledge.append(
                KnowledgeDoc(
                    filename=md.name,
                    title=title,
                    content=content,
                    source_path=str(md.resolve()),
                )
            )

    # scripts/* → 相对路径列表(相对 skill_dir,POSIX 风格)
    scripts = []
    scripts_dir = skill_path / "scripts"
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.rglob("*")):
            if p.is_file():
                scripts.append(p.relative_to(skill_path).as_posix())

    metadata: Dict[str, Any] = {
        "source_format": "skill",
        "source_path": str(skill_path.resolve()),
        "short_description": short_description or _first_sentence(description),
    }
    # frontmatter metadata 键(agentskills.io 扩展对象,单行 JSON):还原
    # write_skill 序列化的拓扑/角色语义键(graph_edges 等),让分支 DAG
    # 经 skill 形态中转不丢。
    m_meta = re.search(r'^metadata:\s*(\{.*\})\s*$', text, re.MULTILINE)
    if m_meta:
        try:
            restored = json.loads(m_meta.group(1))
            if isinstance(restored, dict):
                for key, value in restored.items():
                    metadata.setdefault(key, value)
        except json.JSONDecodeError:
            pass
    return AgentIR(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=body,
        default_prompt=default_prompt,
        knowledge=knowledge,
        scripts=scripts,
        metadata=metadata,
    )
