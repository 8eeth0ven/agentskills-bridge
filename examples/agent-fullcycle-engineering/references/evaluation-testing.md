# Agent 测试与评估

## 1. 测试金字塔

### Unit Tests

测试普通代码：

- schema 校验
- 工具参数转换
- 权限判断
- 文档切分
- 检索过滤
- 成本计算

### Tool Contract Tests

测试工具契约：

- 合法参数能成功。
- 非法参数被拒绝。
- 超时和外部错误有稳定返回。
- 副作用操作有幂等键或确认机制。

### Prompt and Output Tests

测试模型输出是否满足格式和约束：

- JSON/schema 是否有效。
- 必填字段是否存在。
- 禁止内容是否缺失。
- 不确定时是否会澄清或拒绝。

### Integration Tests

测试完整 Agent loop：

- happy path
- 工具失败
- 用户输入含糊
- 权限不足
- 证据不足
- 多轮中断和恢复

### CrewAI Configuration Tests

测试 CrewAI 或类似配置：

- `agents.yaml` 中的 agent 名称被 task 正确引用。
- `tasks.yaml` 的 context 不引用不存在的任务。
- Flow state 字段和输入字段一致。
- router 每个分支都有测试。
- output file 路径可写，guardrail 失败时有清晰错误。

### Offline Evals

用固定数据集衡量质量。每条 case 应包含：

- id
- user_input
- context_or_fixture
- expected_behavior
- allowed_tools
- disallowed_tools
- scoring_notes
- risk_level

### Red Team and Safety Tests

覆盖：

- prompt injection
- 数据泄露
- 越权工具调用
- 幻觉引用
- 隐私信息处理
- 危险或不可逆操作

## 2. 常用指标

- Task success rate：任务完成率。
- Tool accuracy：工具选择和参数是否正确。
- Groundedness：回答是否基于证据。
- Refusal correctness：该拒绝时是否拒绝，不该拒绝时是否过度拒绝。
- Latency：端到端耗时。
- Cost：token 和工具调用成本。
- Human intervention rate：需要人工介入的比例。
- Regression rate：新版本相对旧版本变差的比例。
- Trace completeness：关键 span 是否完整。
- Recovery success rate：失败后重试、回放或人工接管是否成功。

## 3. 处理非确定性

Agent 测试不能只比较完整字符串。优先：

- 比较结构化字段。
- 用规则检查关键事实。
- 用 rubric 评分。
- 对高风险任务使用人工抽检。
- 固定模型、温度、prompt 版本和工具 fixture。

## 4. Release Gate

上线前至少满足：

- 所有单元测试和集成测试通过。
- 核心 eval 集未回退。
- 高风险 case 有人工确认或拒绝策略。
- 日志和 trace 可定位一次失败运行。
- 成本和延迟在预算内。
- 回滚方式明确。
- Debug runbook 可用。
- PR 或变更说明包含测试证据。

## 5. Debug 流程

当 Agent 表现异常：

1. 复现用户输入和环境。
2. 查看 prompt 版本、模型、工具参数和 tool result。
3. 判断失败发生在理解、检索、规划、工具、权限、输出格式还是最终表达。
4. 添加一个最小回归 case。
5. 修复最窄的一层。
6. 跑相关测试和 eval。

## 6. Review Gate

代码评审时只报告有明确证据的问题，优先级：

- Critical：确定会造成错误、安全问题、数据损坏、越权或生产事故。
- Warning：很可能造成质量、性能、维护性或可观测性问题。
- Note：风格或改进建议，除非用户要求全面 review，否则不要占据主要输出。

每个问题都要包含文件位置、证据、影响和可执行修复建议。
