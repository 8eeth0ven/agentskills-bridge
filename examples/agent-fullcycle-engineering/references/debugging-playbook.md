# Agent 调试手册

## 1. 先收证据

不要先猜。先收集：

- 用户输入、期望结果、实际结果。
- request id、trace id、任务 id。
- prompt 版本、模型、温度、输出 schema。
- 工具调用参数、工具返回、错误码、延迟。
- RAG 检索 query、top_k、命中文档、权限过滤结果。
- 环境变量是否存在，避免打印密钥值。
- 最近代码 diff 和依赖版本变化。

CrewAI 项目可优先尝试：

```bash
crewai log-tasks-outputs
crewai run
crewai test
crewai replay -t <task_id>
crewai traces status
crewai deploy --status
crewai config show
```

如果命令不可用，说明当前项目不是 CrewAI CLI 项目或环境未安装，改用项目本身的 test、run、log 命令。

## 2. 失败分层

把失败归到一层，不要一次改多层：

- Requirement：目标或验收标准不清。
- Prompt：指令含糊、上下文缺失、输出格式不明确。
- Schema：模型输出结构不符合下游代码。
- Tool：工具参数错、权限错、超时、外部系统失败。
- RAG：检索不到、召回错、权限过滤错、上下文过长。
- Planning：步骤过多、停止条件缺失、循环。
- State：状态字段名不一致、持久化失败、恢复逻辑错。
- Memory：记忆未启用、污染、过期或权限不当。
- Flow：路由条件、监听关系、分支状态、并发依赖错误。
- Runtime：依赖、环境变量、版本、网络、限流。
- Observability：trace 缺失、日志不够、成本/延迟不可见。

## 3. 症状到根因

| Symptom | Likely layer | First checks |
| --- | --- | --- |
| 回答泛泛而谈 | Prompt/RAG | 上下文是否进入 prompt，检索结果是否正确 |
| 工具没有被调用 | Tool/Prompt | 工具是否注册，工具描述是否明确，权限是否允许 |
| 工具参数乱填 | Schema/Tool | 参数 schema、枚举、示例、校验错误是否返回给模型 |
| Agent 一直循环 | Planning/State | 最大步数、停止条件、任务是否可完成 |
| 输出格式不稳定 | Schema/Prompt | structured output、parser、重试和失败提示 |
| RAG 幻觉引用 | RAG/Eval | 来源是否强制引用，证据不足是否允许拒答 |
| Flow 卡住 | Flow/State | `@listen` 连接、router 条件、state 字段名、异常吞没 |
| 部署后才失败 | Runtime/Deploy | 环境变量、依赖版本、权限、网络、密钥 |
| trace 看不到 | Observability | tracing 开关、初始化顺序、认证、collector endpoint |

## 4. 修复流程

1. 复现最小失败输入。
2. 定位失败层并写下证据。
3. 给该失败添加一个最小回归 case。
4. 修改最窄层：prompt、schema、tool、RAG、state、flow 或 runtime。
5. 跑相关测试和一小组 eval。
6. 查看 trace，确认失败路径消失且没有新副作用。
7. 更新 runbook 或 checklist，防止同类问题重复发生。

## 5. CrewAI 常见检查点

Agent 问题：

- `role` 和 `goal` 是否具体。
- `tools` 是否真正导入并传给 agent。
- `verbose=True` 是否开启以便调试。
- `max_iter`、reasoning、delegation 是否符合任务复杂度。

Task 问题：

- `expected_output` 是否足够具体。
- `context` 是否引用正确上游 task。
- guardrail 是否过严或过松。
- output file 路径是否存在且可写。

Flow 问题：

- `@start` 是否只有合理入口。
- `@listen` 是否连接到正确方法。
- `@router` 是否覆盖默认或失败分支。
- Flow state 字段名是否和 inputs 一致。
- 持久化或恢复是否需要显式开启。

Deploy/Chat/Trace 问题：

- 是否登录 CLI。
- `.env.example` 是否覆盖必要变量。
- tracing 是否被环境变量覆盖。
- 观测 SDK 是否在 CrewAI import 前初始化。
- 生产依赖是否和本地一致。

## 6. Debug 报告模板

```markdown
## Diagnostic Summary
- Symptom:
- Root cause:
- Failed layer:
- Affected files:

## Evidence
- Repro command:
- Relevant trace/log:
- Failing test or eval:

## Fix
- Change:
- Why it works:

## Verification
- Commands run:
- Results:

## Prevention
- Regression case added:
- Checklist/runbook update:
```
