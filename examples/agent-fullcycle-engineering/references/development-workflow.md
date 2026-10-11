# Agent 开发闭环

## 1. 目标

把 Agent 开发从“想到什么写什么”改成可复现的工程流程：

1. Brainstorm：把模糊想法变成 feature brief。
2. Plan：把 feature brief 变成架构、任务、依赖和验证策略。
3. Codegen：按任务生成或修改代码，同时补测试。
4. Debug：按证据定位失败层，做最小修复。
5. Observability：让每次运行可追踪、可度量、可复盘。
6. Review：高置信检查 bug、安全、性能、质量和项目约定。
7. Deploy：发布前 gate、上线验证、回滚计划。
8. Commit/PR：把变更整理成可审查的提交和 PR 描述。

## 2. Brainstorm 输出

当用户只有粗略想法，先输出 feature brief：

- Executive summary：要做什么，为什么做。
- User stories：3 到 5 条用户故事。
- Acceptance criteria：每条故事对应可测试验收标准。
- Technical constraints：平台、性能、安全、数据、集成约束。
- Architecture sketch：组件、数据流、工具边界。
- Agent assignments：需要哪些角色或子任务。
- Risk assessment：前三个风险和缓解方式。

不要急着写代码。先把未知项列出来，并区分 MVP 和后续增强。

## 3. Plan 输出

把 brief 转成可执行计划：

- Work streams：独立工作流和依赖关系。
- Execution order：顺序、并行、阻塞点。
- Agent or module ownership：每个任务由哪个 agent、模块或开发者负责。
- Task contract：输入、输出、验收、测试、guardrail。
- State model：任务状态、对话状态、持久化状态。
- Validation strategy：单测、集成测试、eval、安全测试。

如果是 CrewAI 项目，同时产出：

- `agents.yaml`：role、goal、backstory、tools、delegation、reasoning。
- `tasks.yaml`：description、expected_output、agent、context、output_file、guardrails。
- `crew.py`：Crew 组合和 process。
- `main.py` 或 Flow：state、`@start`、`@listen`、`@router`。

## 4. Codegen 标准

实现时优先跟随现有项目风格。没有现成风格时，采用这些默认值：

- 公共接口带类型标注。
- 外部 I/O 设置超时、重试和结构化错误。
- 模型输出进入业务逻辑前必须 schema 校验。
- 工具调用返回 `ok`、`data`、`error`、`retryable` 或等价结构。
- 对副作用操作使用确认、幂等键或 dry-run。
- 新增代码同时新增测试。
- 日志包含 request id、prompt version、model、tool、latency、status。

## 5. 自检清单

提交前检查：

- 所有 import 有用且可解析。
- happy path 和至少两个边界/错误路径有测试。
- 没有硬编码 key、token、secret、password。
- 没有把隐私数据写进日志。
- 异步代码没有阻塞 I/O。
- RAG 回答能追溯来源，证据不足会承认不知道。
- CrewAI 配置中的 agent、task、context、output 名称一致。

## 6. 交付输出格式

完成一次开发任务后，给用户：

- Changed：改了哪些文件和行为。
- Tests：运行了哪些测试，结果如何。
- Debug evidence：如果修复了问题，说明症状、根因和验证。
- Risk：剩余风险或未覆盖场景。
- Next：必要的后续动作，如部署、配置密钥、补数据集。
