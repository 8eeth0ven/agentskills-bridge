# Agent 可观测性与运维

## 1. 最小可观测性

每次 Agent 运行至少记录：

- request_id / trace_id
- user or tenant id 的脱敏标识
- model、prompt_version、temperature
- input 类型和长度，不记录敏感原文
- tool call 名称、参数摘要、状态、错误码、延迟
- RAG query、top_k、doc ids、权限过滤结果
- token、成本估算、端到端耗时
- final status：success、clarified、refused、failed、escalated

## 2. 指标

- Success rate
- Task failure rate
- Tool failure rate
- Retry count
- Human escalation rate
- Refusal correctness
- Latency p50/p95/p99
- Cost per run
- Token usage per run
- RAG hit rate and citation coverage
- Safety violation count

## 3. Trace 结构

建议 span 层级：

1. Request
2. Agent loop
3. Planning or routing
4. Retrieval
5. Tool call
6. LLM call
7. Validation
8. Final answer

这样能判断失败发生在模型、工具、检索、路由还是输出校验。

## 4. 平台选择

先用项目现有观测体系。没有现成体系时：

- 基础 CrewAI trace：使用 CrewAI AMP 或 CLI 自带 tracing。
- Eval 和实验对比：使用 Braintrust 或同类平台。
- 成本、Prompt、合规：使用 Langfuse、Langtrace、OpenLIT 或同类平台。
- 企业 APM：优先 OpenTelemetry，接入 Datadog、Grafana、New Relic 等现有平台。

选择平台时看需求，不要为了平台而平台：

- 只看执行链路：内置 tracing 足够。
- 要做 prompt A/B 和 eval：选实验平台。
- 要看安全、PII、成本异常：选安全和成本可观测工具。
- 团队已有 APM：接 OpenTelemetry。

## 5. CrewAI 观测检查

CrewAI 项目常见设置：

```python
crew = Crew(
    agents=[...],
    tasks=[...],
    process=Process.sequential,
    tracing=True,
    verbose=True,
)
```

Flow 项目检查：

```python
flow = MyFlow(tracing=True)
```

环境变量检查：

```bash
CREWAI_TRACING_ENABLED=true
```

常见问题：

- trace 看不到：确认 CLI 登录、tracing 开启、环境变量没有覆盖。
- 第三方 SDK 无 span：确认初始化发生在 CrewAI/OpenAI import 之前。
- cost 不准：确认模型价格配置或平台是否支持当前模型。
- 多平台重复 span：确认只设置一个 tracer provider 或明确 span processor 组合。

## 6. 告警与运行手册

至少设置这些告警：

- 失败率超过阈值。
- p95 延迟超过预算。
- 单次或小时成本异常。
- 工具错误率突然上升。
- 高风险拒绝/审批比例异常。
- RAG citation coverage 下降。

Runbook 至少包括：

- 如何找到一次失败运行。
- 如何重放或构造最小复现。
- 如何临时关闭高风险工具。
- 如何降级到人工处理或只读模式。
- 如何回滚 prompt、模型、依赖或部署版本。
