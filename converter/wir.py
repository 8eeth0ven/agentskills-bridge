"""WorkflowIR —— skill / agent / workflow 三形态互转的 workflow 形态中间表示。

数据流(第三形态):
    AgentIR ──WorkflowIR.from_agent_ir──▶ WorkflowIR ──emitters──▶ n8n / mermaid-workflow
    n8n / mermaid-workflow ──parsers──▶ AgentIR ──skill_writer──▶ skill

与 AgentIR 的映射规则(契约,勿改语义):
    - tasks 非空:每个 TaskStep → 一个 WorkflowNode(id=slugify(name),去重),
      prompt = description(+ "\\n\\nExpected output: ..." 附言),节点按 tasks
      顺序用 WorkflowEdge 串联成链;
    - tasks 为空:单节点 workflow(id=slugify(ir.name), prompt=system_prompt);
    - 反向 to_agent_ir:单节点 → system_prompt=节点 prompt;多节点 →
      "# {display_name}\\n\\n" + "\\n\\n".join("## Step {i}: {name}\\n{prompt}")
      合并,并重建 tasks(agent 字段 = workflow name);
    - name/display_name/description/system_prompt/knowledge/metadata 全量透传,
      from_agent_ir 额外记 metadata["_workflow"]=True。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

try:
    from converter.ir import AgentIR, KnowledgeDoc, TaskStep, slugify
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from .ir import AgentIR, KnowledgeDoc, TaskStep, slugify  # type: ignore

__all__ = ["WorkflowNode", "WorkflowEdge", "WorkflowIR"]


@dataclass
class WorkflowNode:
    """工作流图中的一个执行单元(通常是一个 agent 步骤)。"""

    id: str  # kebab-case 图内唯一 id
    name: str  # 人类可读步骤名
    kind: str = "agent"  # agent / tool / condition ...
    prompt: str = ""  # 该步骤的完整提示词
    description: str = ""  # 短说明(通常来自 TaskStep.expected_output)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "agent")),
            prompt=str(data.get("prompt", "")),
            description=str(data.get("description", "")),
        )


@dataclass
class WorkflowEdge:
    """节点间的有向边(执行顺序 / 数据流)。"""

    source: str  # 源节点 id
    target: str  # 目标节点 id
    label: str = ""  # 边标注(mermaid `-->|label|`)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEdge":
        return cls(
            source=str(data.get("source", "")),
            target=str(data.get("target", "")),
            label=str(data.get("label", "")),
        )


@dataclass
class WorkflowIR:
    """规范化 workflow 表示 —— workflow 形态转换的枢纽(对齐 AgentIR 风格)。"""

    name: str  # kebab-case id
    display_name: str = ""  # 人类可读名
    description: str = ""  # 何时用
    system_prompt: str = ""  # 整体主指令(多节点时为图级背景,步骤级看节点 prompt)
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    knowledge: List[KnowledgeDoc] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------- 序列化(对齐 AgentIR) ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "knowledge": [k.to_dict() for k in self.knowledge],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowIR":
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            nodes=[WorkflowNode.from_dict(n) for n in data.get("nodes", [])],
            edges=[WorkflowEdge.from_dict(e) for e in data.get("edges", [])],
            knowledge=[KnowledgeDoc.from_dict(k) for k in data.get("knowledge", [])],
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "WorkflowIR":
        return cls.from_dict(json.loads(text))

    # ---------- AgentIR 互转 ----------

    @classmethod
    def from_agent_ir(cls, ir: AgentIR) -> "WorkflowIR":
        """AgentIR → WorkflowIR,节点来源优先级:正文步骤提取 > ir.tasks > 单节点。

        正文步骤提取(extract_workflow_steps)是 skill→workflow 的语义层:
        SKILL.md 里"## Workflow/工作流程"下的编号步骤天然就是工作流节点,
        比整篇当一个大 prompt 保真。函数内延迟 import 避免与
        workflow_extract(它 import 本模块)循环依赖。
        """
        nodes: List[WorkflowNode] = []
        used: Dict[str, int] = {}

        def _unique_id(name: str) -> str:
            base = slugify(name)
            if base not in used:
                used[base] = 1
                return base
            used[base] += 1
            return f"{base}-{used[base]}"

        steps: List[dict] = []
        try:  # workflow_extract 与本模块互为依赖方,延迟导入
            from converter.workflow_extract import extract_workflow_steps
            steps = extract_workflow_steps(ir.system_prompt or "")
        except Exception:  # noqa: BLE001 - 提取器不可用时按无步骤处理
            steps = []

        if steps:
            for step in steps:
                nodes.append(WorkflowNode(
                    id=_unique_id(step.get("title", "") or "step"),
                    name=step.get("title", "") or "Step",
                    prompt=step.get("body", ""),
                ))
        elif ir.tasks:
            # 角色挂载(语义审计 P1):crewai 多 agent 反向时,task.agent 指明
            # 承担角色的 agent 名;真实项目 tasks.yaml 常不写 agent 字段
            # (运行时分配),此时若 agent 数与 task 数相等则按序对齐(crewai
            # 常见模式)。metadata.agents 携带 role/goal,节点 prompt 前缀
            # "As <role>: <goal>" —— 否则 workflow 节点只知"做什么",
            # 不知"谁以什么角色做"。
            role_by_agent = {}
            ordered_agents: List[str] = []
            for a in (ir.metadata or {}).get("agents") or []:
                if isinstance(a, dict) and a.get("name"):
                    ordered_agents.append(str(a["name"]))
                    role_by_agent[str(a["name"])] = (
                        str(a.get("role") or ""), str(a.get("goal") or "")
                    )
            positional = (
                not any(t.agent for t in ir.tasks)
                and len(ir.tasks) == len(ordered_agents)
            )
            for idx, step in enumerate(ir.tasks):
                agent_name = step.agent or (
                    ordered_agents[idx] if positional and idx < len(ordered_agents) else ""
                )
                prompt = step.description or ""
                if agent_name and agent_name in role_by_agent:
                    role, goal = role_by_agent[agent_name]
                    role = " ".join(role.split())
                    goal = " ".join(goal.split())
                    header = "As " + (role or agent_name) + "."
                    if goal:
                        header += " Goal: " + goal
                    prompt = header + "\n\n" + prompt
                if step.expected_output:
                    prompt = f"{prompt}\n\nExpected output: {step.expected_output}"
                nodes.append(WorkflowNode(
                    id=_unique_id(step.name),
                    name=step.name,
                    prompt=prompt,
                    description=step.expected_output or "",
                ))
        else:
            nodes.append(WorkflowNode(
                id=slugify(ir.name),
                name=ir.title(),
                prompt=ir.system_prompt or "",
            ))
        edges = [
            WorkflowEdge(source=nodes[i].id, target=nodes[i + 1].id)
            for i in range(len(nodes) - 1)
        ]
        # 分支拓扑优先(parser 保留的 graph_edges):端点能对上节点 id 或
        # name 的边按原图覆盖线性链(端点是 n8n 节点名时翻译成 id)——
        # n8n 与 mermaid 两个 workflow emitter 都消费 w.edges,分支 DAG
        # 在两种格式里同时持久化(语义审计 P2 的 WIR 层收口)。
        graph_edges = (ir.metadata or {}).get("graph_edges")
        if isinstance(graph_edges, list):
            id_by_key: Dict[str, str] = {}
            for n in nodes:
                id_by_key.setdefault(n.id, n.id)
                if n.name:
                    id_by_key.setdefault(n.name, n.id)
            mapped = []
            for e in graph_edges:
                if not (isinstance(e, list) and len(e) == 2):
                    continue
                src = id_by_key.get(str(e[0]))
                tgt = id_by_key.get(str(e[1]))
                if src and tgt and src != tgt:
                    mapped.append(WorkflowEdge(source=src, target=tgt))
            if mapped:
                edges = mapped
        metadata = dict(ir.metadata)
        metadata["_workflow"] = True
        if steps:
            metadata["steps_extracted"] = len(steps)
        return cls(
            name=ir.name,
            display_name=ir.display_name,
            description=ir.description,
            system_prompt=ir.system_prompt,
            nodes=nodes,
            edges=edges,
            knowledge=list(ir.knowledge),
            metadata=metadata,
        )

    def to_agent_ir(self) -> "AgentIR":
        """WorkflowIR → AgentIR:单节点还原 prompt,多节点合并 "## Step N:" 小节。"""
        if len(self.nodes) == 1:
            system_prompt = self.nodes[0].prompt
        elif self.nodes:
            title = self.display_name or self.name
            parts = [
                f"## Step {i}: {n.name}\n{n.prompt}"
                for i, n in enumerate(self.nodes, 1)
            ]
            system_prompt = f"# {title}\n\n" + "\n\n".join(parts)
        else:
            system_prompt = self.system_prompt
        return AgentIR(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            system_prompt=system_prompt,
            tasks=[
                TaskStep(name=n.name, description=n.prompt, agent=self.name)
                for n in self.nodes
            ],
            knowledge=list(self.knowledge),
            metadata=dict(self.metadata),
        )
