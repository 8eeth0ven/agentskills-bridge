"""Emitter 注册表:AgentIR -> 各目标框架产物。

用法:
    from converter.emitters import EMITTERS
    EMITTERS["crewai-skills"](ir, out_dir)
    # 键 ∈ crewai / crewai-skills / deepagents / langchain / langflow /
    #     openai / claude-subagent / generic

注意 "openai" 键指向 openai_agents 模块的 emit_openai_agents;
"crewai-skills" 产出 CrewAI 原生 Agent Skills(skills/ 目录 + agents.yaml 挂载),
"deepagents" 产出 LangChain 官方 deepagents 运行时(create_deep_agent + SkillsMiddleware),
"claude-subagent" 产出 Claude Code 子代理定义(.claude/agents/<name>.md)。
"""

from .autogen import emit_autogen
from .claude_subagent import emit_claude_subagent
from .crewai import emit_crewai
from .crewai_skills import emit_crewai_skills
from .deepagents import emit_deepagents
from .generic import emit_generic
from .langchain import emit_langchain
from .langflow import emit_langflow
from .openai_agents import emit_openai_agents

EMITTERS = {
    "autogen": emit_autogen,
    "crewai": emit_crewai,
    "crewai-skills": emit_crewai_skills,
    "deepagents": emit_deepagents,
    "langchain": emit_langchain,
    "langflow": emit_langflow,
    "openai": emit_openai_agents,
    "claude-subagent": emit_claude_subagent,
    "generic": emit_generic,
}

__all__ = [
    "EMITTERS",
    "emit_autogen",
    "emit_crewai",
    "emit_crewai_skills",
    "emit_deepagents",
    "emit_langchain",
    "emit_langflow",
    "emit_openai_agents",
    "emit_claude_subagent",
    "emit_generic",
]
