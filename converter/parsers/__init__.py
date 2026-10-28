"""parsers 包:外部 agent 格式 → AgentIR。

用法:
    from converter.parsers import PARSERS
    ir = PARSERS["crewai"](config_dir)
    # 键 ∈ crewai / crewai-skills / deepagents / langchain / langflow /
    #     openai / claude-subagent / generic / n8n / mermaid-workflow
"""

from __future__ import annotations

from .autogen import parse_autogen
from .claude_subagent import parse_claude_subagent
from .crewai import parse_crewai
from .crewai_skills import parse_crewai_skills
from .deepagents import parse_deepagents
from .generic import parse_generic
from .langchain import parse_langchain
from .langflow import parse_langflow
from .openai import parse_openai

try:  # 并行线程产物:未落盘时跳过该键,不影响其余 parser
    from .n8n import parse_n8n  # type: ignore
except Exception:  # pragma: no cover - n8n 未落盘
    parse_n8n = None  # type: ignore
from .mermaid_workflow import parse_mermaid_workflow

PARSERS = {
    "autogen": parse_autogen,
    "crewai": parse_crewai,
    "crewai-skills": parse_crewai_skills,
    "deepagents": parse_deepagents,
    "langchain": parse_langchain,
    "langflow": parse_langflow,
    "openai": parse_openai,
    "claude-subagent": parse_claude_subagent,
    "generic": parse_generic,
}
if parse_n8n is not None:
    PARSERS["n8n"] = parse_n8n
PARSERS["mermaid-workflow"] = parse_mermaid_workflow

from converter.preservation import preserving_parser
PARSERS = {fmt: preserving_parser(fmt, parse) for fmt, parse in PARSERS.items()}

__all__ = [
    "PARSERS",
    "parse_autogen",
    "parse_claude_subagent",
    "parse_crewai",
    "parse_crewai_skills",
    "parse_deepagents",
    "parse_generic",
    "parse_langchain",
    "parse_langflow",
    "parse_openai",
    "parse_mermaid_workflow",
]
