"""CrewAI Agent Skills 项目 → AgentIR 解析器。

root 指向 crewai-skills emitter 产出的项目根:
    skills/<name>/SKILL.md         合法 Anthropic 风格技能(frontmatter + 正文)
    skills/<name>/references/*.md  知识文档(渐进披露资源层)
    config/tasks.yaml              任务定义(可选)

skills/ 下的技能目录本身就是合法 skill,直接复用 skill_loader.load_skill
读出近乎完整的 IR(name/description/system_prompt/knowledge),再用
config/tasks.yaml(若在)覆盖 tasks。skills/*/SKILL.md 缺失抛 FileNotFoundError。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

try:
    from converter.ir import AgentIR, TaskStep
    from converter.parsers.crewai import _load_yaml_text
    from converter.skill_loader import load_skill
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, TaskStep  # type: ignore
    from ..skill_loader import load_skill  # type: ignore
    from .crewai import _load_yaml_text  # type: ignore


def _first_skill_dir(root: Path) -> Path:
    """取 skills/ 下第一个含 SKILL.md 的子目录;无则抛 FileNotFoundError。"""
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if (child / "SKILL.md").is_file():
                return child
    raise FileNotFoundError(f"missing skills/*/SKILL.md under {root}")


def _load_tasks(tasks_file: Path) -> List[TaskStep]:
    """读 tasks.yaml:每个顶层 key(任务名)→ TaskStep(description 等字段容忍缺失)。"""
    data = _load_yaml_text(tasks_file.read_text(encoding="utf-8"))
    tasks: List[TaskStep] = []
    if isinstance(data, dict):
        for key, body in data.items():
            body = body if isinstance(body, dict) else {}
            tasks.append(
                TaskStep(
                    name=str(key),
                    description=str(body.get("description") or ""),
                    expected_output=str(body.get("expected_output") or ""),
                    agent=str(body.get("agent") or ""),
                )
            )
    return tasks


def parse_crewai_skills(root: Union[str, Path]) -> AgentIR:
    """解析 CrewAI Agent Skills 项目根为 AgentIR(取第一个技能目录)。

    技能目录即合法 skill,load_skill 直接产出近乎完整的 IR;
    config/tasks.yaml 存在时其任务列表覆盖 ir.tasks。
    """
    base = Path(root)
    skill_dir = _first_skill_dir(base)
    ir = load_skill(skill_dir)

    tasks_file = base / "config" / "tasks.yaml"
    if tasks_file.is_file():
        ir.tasks = _load_tasks(tasks_file)

    ir.metadata["source_format"] = "crewai-skills"
    ir.metadata["source_path"] = str(base.resolve())
    return ir
