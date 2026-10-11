"""deepagents 运行时项目 → AgentIR 解析器。

path 指向 deepagents emitter 产出的项目目录(agent.py + skills/),也接受
agent.py 文件本身:
- 目录且存在 skills/*/SKILL.md:技能目录即合法 skill,load_skill 读出基础
  IR(name/description/system_prompt/knowledge),再从 agent.py 提取
  @tool 装饰函数 / StructuredTool(name=...) 工具(复用 langchain parser
  的 _extract_tools)按名去重合并进 IR.tools;
- 否则回退 parse_langchain(agent.py)。

metadata: source_format="deepagents"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

try:
    from converter.ir import AgentIR
    from converter.parsers.langchain import _extract_tools, parse_langchain
    from converter.skill_loader import load_skill
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR  # type: ignore
    from ..skill_loader import load_skill  # type: ignore
    from .langchain import _extract_tools, parse_langchain  # type: ignore


def _first_skill_dir(root: Path) -> Optional[Path]:
    """取 skills/ 下第一个含 SKILL.md 的子目录;无则 None。"""
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if (child / "SKILL.md").is_file():
                return child
    return None


def _merge_tools(ir: AgentIR, agent_py: Path) -> None:
    """把 agent.py 中提取到的 @tool/StructuredTool 工具按名去重合并进 ir.tools。"""
    if not agent_py.is_file():
        return
    seen = {t.name for t in ir.tools}
    for tool in _extract_tools(agent_py.read_text(encoding="utf-8")):
        if tool.name not in seen:
            ir.tools.append(tool)
            seen.add(tool.name)


def parse_deepagents(path: Union[str, Path]) -> AgentIR:
    """解析 deepagents 项目(agent.py + skills/)为 AgentIR。

    有 skills/*/SKILL.md 时以技能目录为基础 IR 并合并 agent.py 工具;
    否则回退 parse_langchain(agent.py)(文件缺失由其抛 FileNotFoundError)。
    """
    base = Path(path)
    skill_dir = _first_skill_dir(base) if base.is_dir() else None
    agent_py = base / "agent.py" if base.is_dir() else base

    if skill_dir is not None:
        ir = load_skill(skill_dir)
        _merge_tools(ir, agent_py)
    else:
        ir = parse_langchain(agent_py)

    ir.metadata["source_format"] = "deepagents"
    ir.metadata["source_path"] = str(base.resolve())
    return ir
