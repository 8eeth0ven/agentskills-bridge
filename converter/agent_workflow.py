"""AgentIR ↔ WorkflowIR 薄封装(skill / agent / workflow 三形态互转入口)。

    agent_to_workflow(ir)  == WorkflowIR.from_agent_ir(ir)
    workflow_to_agent(w)   == w.to_agent_ir()
"""

from __future__ import annotations

try:
    from converter.ir import AgentIR
    from converter.wir import WorkflowIR
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from .ir import AgentIR  # type: ignore
    from .wir import WorkflowIR  # type: ignore

__all__ = ["agent_to_workflow", "workflow_to_agent"]


def agent_to_workflow(ir: AgentIR) -> WorkflowIR:
    """AgentIR → WorkflowIR(等价 WorkflowIR.from_agent_ir)。"""
    return WorkflowIR.from_agent_ir(ir)


def workflow_to_agent(w: WorkflowIR) -> AgentIR:
    """WorkflowIR → AgentIR(等价 w.to_agent_ir())。"""
    return w.to_agent_ir()
