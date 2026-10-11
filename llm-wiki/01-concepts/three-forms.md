# 三种形态:Skill、Agent 与 Workflow

skill ↔ agent 双向转换是本项目的基础;现在 workflow 提升为第三种一等形态,形成 **Skill / Agent / Workflow 三形态互转**。转换枢纽从单个 AgentIR 扩展为 **AgentIR + WorkflowIR 双枢纽**,两枢纽之间由 `WorkflowIR.from_agent_ir` / `to_agent_ir` 桥接:

```
skill ──skill_loader──▶ AgentIR ──from_agent_ir──▶ WorkflowIR ──workflow emitters──▶ n8n / mermaid-workflow
n8n / mermaid-workflow ──workflow parsers──▶ WorkflowIR ──to_agent_ir──▶ AgentIR ──skill_writer──▶ skill
```

判断规则一句话:**IR.tasks 丰富(多步)时自然成为多步 workflow,反之塌缩为单 agent**。skill / agent 两形态的深入对照见 [skill-vs-agent](skill-vs-agent.md),AgentIR 逐字段规范见 [intermediate-representation](intermediate-representation.md)。

## 三种形态

| 形态 | 本质 | 最小构成 | 典型载体 |
|------|------|----------|----------|
| skill | **声明式知识包**:自身不运行,宿主 agent 命中触发条件后按需加载 | 触发元数据(name / description)+ 正文(主指令)+ 资源(references / scripts) | SKILL.md 目录 |
| agent | **可执行运行时定义**:自己持有模型调用与工具执行 | 单角色 system_prompt + tools 契约 | agents.yaml / agent.py / openai.yaml |
| workflow | **多步骤编排**:显式 DAG | 节点(步骤 / 子 agent)+ 边(依赖顺序),至少一个入口节点 | workflow.json(n8n)/ workflow.md(mermaid)/ tasks.yaml(CrewAI) |

三者是同一份能力定义的三个投影:skill 把编排写成正文里的流程描述(给宿主读),agent 把编排折叠进单角色 prompt(运行时执行),workflow 把编排展开为显式图(结构化执行 + 可视化)。

## 三形态互转表(3×3)

行 = 源形态,列 = 目标形态;对角线为同形态,不需要转换:

| from \ to | skill | agent | workflow |
|-----------|-------|-------|----------|
| **skill** | —— | 已有:skill_loader → AgentIR → 9 个 target 的 emitters,见 [skill-to-agent](../04-conversion/skill-to-agent.md) | SKILL.md 步骤语义提取(`workflow_extract`)或直接取 AgentIR.tasks → WorkflowIR → workflow emitters |
| **agent** | 已有:8 入口 parsers → AgentIR → skill_writer,见 [agent-to-skill](../04-conversion/agent-to-skill.md) | —— | AgentIR.tasks 逐条展开为节点链;tasks 为空 / 单条时为平凡单节点 |
| **workflow** | 节点按分节进正文 + 步骤写回 IR.tasks → skill_writer | 节点合并为分节 system_prompt(`## Step N: <name>`)→ AgentIR → 各 agent target | —— |

六条转换边全部经 **AgentIR / WorkflowIR 双枢纽**,不允许格式间点对点直转(与 AgentIR 的使用约束一致)。两枢纽间的桥梁:

- `WorkflowIR.from_agent_ir(agent_ir)`:agent → workflow 方向。IR.tasks 非空时逐条 TaskStep 展开为节点、按列表顺序连成链;tasks 为空时以 system_prompt 造单节点。knowledge / metadata 原样携带。
- `WorkflowIR.to_agent_ir()`:workflow → agent 方向。节点按拓扑顺序合并为分节 system_prompt(每节点一节 `## Step N: <name>`),knowledge / metadata 原样带回。

## WorkflowIR 契约规范

WorkflowIR(`converter/wir.py` 中的 `WorkflowIR` dataclass)是 workflow 形态的枢纽。本节字段名与类型**与 `converter/wir.py` 严格一致**;修改任一侧必须同步另一侧。

### WorkflowNode(节点)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 节点 id,图内唯一;边的 source / target 引用它 |
| `name` | `str` | 节点名,人类可读 |
| `kind` | `str` | 节点类型标记,区分普通步骤节点与子 agent 节点(emitter 按此映射目标格式) |
| `prompt` | `str` | 该节点的指令正文 |
| `description` | `str` | 节点用途描述 |

### WorkflowEdge(边)

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `str` | 起点(WorkflowNode.id) |
| `target` | `str` | 终点(WorkflowNode.id) |
| `label` | `str` | 边标注(依赖说明,可空) |

### WorkflowIR(顶层)

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | kebab-case id(同 AgentIR.name 约定,`slugify()` 生成) |
| `display_name` | `str` | 人类可读名 |
| `description` | `str` | 何时使用(触发条件描述) |
| `system_prompt` | `str` | workflow 级总指令:节点之外的公共上下文 |
| `nodes` | `List[WorkflowNode]` | 节点列表 |
| `edges` | `List[WorkflowEdge]` | 边列表,合起来构成 DAG |
| `knowledge` | `List[KnowledgeDoc]` | 知识文档,与 `AgentIR.knowledge` 同构(定义见 [intermediate-representation](intermediate-representation.md)) |
| `metadata` | `Dict[str, Any]` | 杂项,至少含 `source_format` |

## workflow 格式族

workflow 形态的 target 家族现有四个成员,其中两个为本轮新增(`python3 cli.py skill2agent <skill-dir> --target n8n | mermaid-workflow`):

| target | 产物 | 结构 | 状态 |
|--------|------|------|------|
| crewai | `config/tasks.yaml` | 多任务列表(name / description / expected_output / agent) | 既有——tasks.yaml 多任务本身就是 workflow 形态的成员 |
| langflow | `flow.json` | 节点图(nodes / edges) | 既有——flow.json 节点图本身是 workflow 形态的成员 |
| n8n | `workflow.json` | `nodes` 数组 + `connections` 映射 | 本轮新增 |
| mermaid-workflow | `workflow.md` | mermaid `flowchart TD` 图 + Step 分节正文 | 本轮新增 |

### n8n(workflow.json)

- 节点数组 `nodes` + 连线映射 `connections`(源节点 → 输出 → 目标节点列表);
- AI Agent 节点:type `@n8n/n8n-nodes-langchain.agent`,主指令写进 `options.systemMessage`(多步内容按 Step 分节写入);
- 入口:chatTrigger 节点(`@n8n/n8n-nodes-langchain.chatTrigger`)连向首个步骤节点;
- `settings.executionOrder: "v1"`(n8n 现行执行顺序声明)。

### mermaid-workflow(workflow.md)

- 头部 mermaid `flowchart TD` 代码块:节点 = 步骤(id / name),边 = 依赖(`A --> B`,可带 label);
- 其后每个节点一节 `## Step N: <name>`,承载 prompt / description 正文;
- 单文件纯 markdown,GitHub 原生渲染图;知识文档落同目录 `knowledge/`。

n8n 与 mermaid-workflow 的格式说明先记于本章「workflow 格式族」,后续独立成章;crewai / langflow 详见 [03-frameworks](../03-frameworks/crewai.md) 对应章节。

## 有损点

三形态互转中信息不守恒的位置,与 skill ↔ agent 的既有有损方向(agent 的 tools / tasks 在 skill 侧无落点)同源:

- **workflow → agent**:多节点合并为分节 system_prompt 时**丢图拓扑**——分支 / 汇聚 / 并行塌缩为线性文本,仅保拓扑顺序(`## Step N` 编号即序)。
- **agent → workflow**:单 agent 展开是**平凡单节点**(一步图),无实际编排语义;只有 IR.tasks 丰富时才产生真正的多步 workflow。
- **workflow → skill**:节点分节进正文 + 步骤成 tasks,与 agent → skill 同构——编排退化为正文里的流程描述,tasks 名单留在 IR,回程可恢复。
- **→ n8n**:tools / 凭据(credential)节点**不自动生成**——工具契约留在 IR,需人工在 n8n 界面为 AI Agent 节点补挂 tool 子节点与凭据;mermaid-workflow 为纯文本格式,无工具挂载点。
