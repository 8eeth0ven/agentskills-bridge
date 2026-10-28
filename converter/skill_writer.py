"""AgentIR → skill 目录写出层。

生成完整 skill 目录(覆盖式写文件):
    SKILL.md            frontmatter(name/description)+ system_prompt 正文
    agents/openai.yaml  interface 三字段
    references/*.md     每个 KnowledgeDoc 一个文件
    scripts/...         可选:按 ir.scripts 从 copy_scripts_from 拷贝

SKILL.md frontmatter 写出前按 agentskills.io 开放规范规范化:
name 归一为合法 kebab-case 且 ≤64 字符;description 展平为单行、非空且
≤1024 字符(空白兜底、超长截断到 1021 加 "...")。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Union

try:
    from converter.ir import AgentIR, slugify
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from .ir import AgentIR, slugify  # type: ignore

# agentskills.io 开放规范对 SKILL.md frontmatter 的硬约束
_MAX_NAME_LEN = 64    # name: 1-64 字符,仅小写字母/数字/连字符
_MAX_DESC_LEN = 1024  # description: 1-1024 字符,非空


def _first_sentence(text: str, max_chars: int = 120) -> str:
    """取首句并裁剪到 max_chars 内(short_description 兜底)。"""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    m = re.match(r"^[^.!?]*[.!?]", flat)
    snippet = (m.group(0) if m else flat).strip()
    return snippet[:max_chars].rstrip()


def _yaml_str(value: str) -> str:
    """生成合法的 YAML 双引号标量(JSON 转义是 YAML 双引号子集)。"""
    return json.dumps(value or "", ensure_ascii=False)


def _normalize_skill_name(raw: str) -> str:
    """规范成 agentskills.io 合法 name:kebab-case、1-64 字符。

    slugify 产物本身满足 `^[a-z0-9]+(-[a-z0-9]+)*$`(连续非法字符归一为
    单连字符、strip 首尾、lower);截断到 64 只可能引入尾部连字符,
    再 strip 即回到合法形态。全空时兜底 "agent"。
    """
    name = slugify(raw or "").strip("-")
    if len(name) > _MAX_NAME_LEN:
        name = name[:_MAX_NAME_LEN].strip("-")
    return name or "agent"


def _normalize_skill_description(ir: AgentIR) -> str:
    """规范成 agentskills.io 合法 description:非空、≤1024 字符、单行。

    空白(含换行)展平为空格分隔的单行;strip 后为空则用
    ``Agent skill for {title}`` 兜底;超 1024 截断到 1021 再补 "..."
    (共 1024 字符)。
    """
    desc = " ".join((ir.description or "").split())  # 换行 → 空格
    if not desc:
        desc = f"Agent skill for {ir.title()}"
    if len(desc) > _MAX_DESC_LEN:
        desc = desc[: _MAX_DESC_LEN - 3] + "..."
    return desc


def _safe_rel(rel: str) -> Union[Path, None]:
    """把 ir.scripts 里的相对路径规范成安全 Path(拒绝绝对路径/越界)。"""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return None
    return p


def _frontmatter_metadata(ir) -> dict:
    """挑 ir.metadata 中可进 frontmatter 的子集(单行 JSON,agentskills.io
    允许的 metadata 扩展对象)。

    排除:本机绝对路径(source_path)与下划线私有键;保留拓扑/角色等
    语义键(graph_edges / agents / agents_all / agents_count /
    steps_extracted / model / source_format)。值不可 JSON 序列化时跳过。

    另把 ir.tools 序列化为 ``tools`` 键([{name,description,input_schema,
    side_effects}] 列表)—— 修复 agent→skill 反向时 tools 契约被静默丢弃
    的缺陷;input_schema 再大也只是单行 JSON 变长,frontmatter 仍合法。
    """
    keep = ("graph_edges", "agents", "agents_all", "agents_count",
            "steps_extracted", "model", "source_format", "chain")
    out: dict = {}
    for key in keep:
        if key in (ir.metadata or {}):
            try:
                json.dumps(ir.metadata[key])
                out[key] = ir.metadata[key]
            except (TypeError, ValueError):
                continue
    tools = list(getattr(ir, "tools", None) or [])
    if tools:
        try:
            payload = [t.to_dict() for t in tools]
            json.dumps(payload)
            out["tools"] = payload
        except (TypeError, ValueError):
            pass
    return out


def _write_skill_native(
    ir: AgentIR,
    out_dir: Union[str, Path],
    copy_scripts_from: Union[str, Path, None] = None,
) -> Path:
    """把 AgentIR 写成 skill 目录,返回 out_dir(Path)。

    copy_scripts_from 提供时,把 ir.scripts 列出的相对路径文件从
    `<copy_scripts_from>/<相对路径>` 拷到 `<out_dir>/<相对路径>`;
    源缺失则静默跳过该条。已存在的目标文件直接覆盖。
    """
    out = Path(out_dir)
    (out / "agents").mkdir(parents=True, exist_ok=True)
    (out / "references").mkdir(parents=True, exist_ok=True)

    # SKILL.md:frontmatter + system_prompt 正文
    # frontmatter 先按 agentskills.io 开放规范规范化(name kebab ≤64、
    # description 非空 ≤1024),再拼正文。metadata 键是规范允许的扩展对象:
    # 单行 JSON 序列化 ir.metadata 的可保留子集(graph_edges 等)+ ir.tools
    # 契约(tools 键),让分支 DAG 拓扑与工具 input_schema 经 skill 形态
    # 中转不丢(语义审计 P2 的 skill 侧补全)。
    name = _normalize_skill_name(ir.name)
    desc = _normalize_skill_description(ir)
    metadata = _frontmatter_metadata(ir)
    meta_line = ""
    if metadata:
        compact = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        meta_line = "\nmetadata: " + compact
    skill_md = f"---\nname: {name}\ndescription: {_yaml_str(desc)}{meta_line}\n---\n\n{ir.system_prompt or ''}"
    if not skill_md.endswith("\n"):
        skill_md += "\n"
    (out / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # agents/openai.yaml:interface 三字段
    short_description = ir.metadata.get("short_description") or _first_sentence(
        ir.description or ""
    )
    openai_yaml = (
        "interface:\n"
        f"  display_name: {_yaml_str(ir.title())}\n"
        f"  short_description: {_yaml_str(str(short_description))}\n"
        f"  default_prompt: {_yaml_str(ir.default_prompt or '')}\n"
    )
    (out / "agents" / "openai.yaml").write_text(openai_yaml, encoding="utf-8")

    # references/:每个 KnowledgeDoc 一个文件
    for doc in ir.knowledge:
        from converter.preservation import safe_path
        filename = safe_path(doc.filename or "reference.md")
        content = doc.content or ""
        if content and not content.endswith("\n"):
            content += "\n"
        dst = out / "references" / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

    # 可选拷贝 scripts
    if copy_scripts_from is not None:
        src_root = Path(copy_scripts_from)
        for rel in ir.scripts:
            safe = _safe_rel(str(rel))
            if safe is None:
                continue
            src = src_root / safe
            if not src.is_file():
                continue
            dst = out / safe
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    return out


def write_skill(ir: AgentIR, out_dir: Union[str, Path],
                copy_scripts_from: Union[str, Path, None] = None) -> Path:
    """Write a verified portable skill package, restoring original files if held.

    Output must be new/empty. For native external inputs without source_files,
    generate a normalized SKILL.md and preserve the full IR in its capsule.
    """
    from converter.preservation import package_output, project_source_skill

    def emit(value, out):
        if value.source_files:
            project_source_skill(value, out)
        else:
            _write_skill_native(value, out, copy_scripts_from)
    return package_output(ir, out_dir, "skill", emit)
