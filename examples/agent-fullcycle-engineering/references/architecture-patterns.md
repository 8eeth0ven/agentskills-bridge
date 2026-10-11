# Agent 架构模式

## 1. 先判断是否真的需要 Agent

不用 Agent 的场景：

- 规则明确，普通代码可以稳定完成。
- 不需要工具调用、长期状态或多轮决策。
- 错误代价高，且无法验证模型输出。

适合 Agent 的场景：

- 用户目标多样，需要动态选择步骤。
- 需要读写多个工具或系统。
- 输入非结构化，需要模型理解。
- 可以通过测试、审批、权限和日志控制风险。

## 2. 常用架构

### Single LLM Call

适合：分类、摘要、格式转换、短文本生成。

关键点：

- 明确输入和输出 schema。
- 控制 prompt 版本。
- 用固定样例做回归测试。

### Assistant With Tools

适合：查询信息、执行有限动作、调用 API。

关键点：

- 工具名表达意图，不要过泛。
- 参数 schema 要严格。
- 工具返回结构化结果和错误码。
- 对副作用操作加确认或审批。

### RAG Agent

适合：基于私有文档、知识库、工单、代码库回答。

关键点：

- 文档清洗、切分、元数据和权限过滤比模型选择更重要。
- 评估召回和答案正确性，不能只看回答是否流畅。
- 要能在证据不足时说不知道。

### Deterministic Workflow With LLM Steps

适合：业务步骤清楚，但某些步骤需要模型判断或生成。

关键点：

- 用代码控制流程和状态机。
- 只在必要节点调用模型。
- 每个节点都有输入、输出、错误和重试策略。

### Planner Executor

适合：任务步骤不固定，需要先规划再执行。

关键点：

- 限制规划范围和最大步骤数。
- 每步执行后重新检查目标和剩余约束。
- 对计划和执行分别记录 trace。

### Multi-Agent

适合：角色边界清晰、任务可并行、需要独立审查或辩论。

关键点：

- 每个 Agent 有明确输入、输出、权限和停止条件。
- 不要让多个 Agent 同时拥有同一副作用工具。
- 需要聚合器或裁决器处理冲突。

### CrewAI Crew

适合：角色、任务和依赖能提前配置，且希望用 `agents.yaml`、`tasks.yaml`、`crew.py` 管理团队执行。

关键点：

- 每个 agent 的 role 和 goal 必须具体。
- 每个 task 的 expected_output 必须可验收。
- context 链只连接必要上游，避免无关上下文污染。
- 复杂任务使用 guardrail、结构化输出或输出文件。
- 先用 `crewai test` 和最小输入验证，再扩大任务数。

### CrewAI Flow

适合：需要状态、分支、恢复、条件路由或多个 Crew 组合。

关键点：

- State schema 是核心契约。
- `@start`、`@listen`、`@router` 要能从图上解释清楚。
- 每个分支要有默认路径和失败路径。
- Flow 节点之间只传必要字段。
- 对长流程加入 trace、timeout、重试和人工接管。

## 3. 核心组件设计

### Instructions

- 写明目标、边界、禁止事项、输出格式。
- 把不稳定的业务知识放在数据或配置中，不要硬塞进 prompt。
- Prompt 变更要像代码一样可审查、可回滚。

### Tools

- 工具只做一件清晰的事。
- 输入参数要少而明确。
- 返回值包含 `ok`、`data`、`error`、`retryable` 等字段。
- 给外部系统设置超时、重试、限流和审计。

### State

区分四类状态：

- Task state：当前任务进度。
- Conversation state：当前对话上下文。
- User memory：用户长期偏好，需要授权和可删除。
- Audit log：不可随意改写的运行记录。

### Memory

只有在确实能提升后续任务时才加长期记忆。记忆要有来源、时间、置信度和删除方式。

### Human In The Loop

这些情况应触发人工确认：

- 花钱、下单、发外部消息、删除或修改重要数据。
- 低置信度但影响较大。
- 用户身份或权限不确定。
- 模型检测到策略冲突。

### Review and Release Boundary

把“能跑”与“能上线”分开：

- Demo boundary：功能可演示，但可以缺少完整观测和回滚。
- Internal boundary：测试、eval、日志和手动恢复可用。
- Production boundary：权限、审批、告警、回滚、runbook 和安全测试完整。

## 4. 设计输出模板

架构设计至少包含：

- User goal
- Non-goals
- Agent type
- Inputs and outputs
- Tools and permissions
- State model
- Failure modes
- Evaluation plan
- Observability plan
- Debugging plan
- Rollout plan
