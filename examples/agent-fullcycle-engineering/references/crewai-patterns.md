# CrewAI 开发模式

## 1. 适用场景

使用 CrewAI 或类似 crew/flow 架构时，重点是把角色、任务、依赖、状态和验证写清楚。不要把多 Agent 当作默认方案；只有在角色边界清楚、任务可拆分、需要独立审查或并行时再使用。

## 2. 项目结构检查

常见文件：

- `src/<project>/config/agents.yaml`
- `src/<project>/config/tasks.yaml`
- `src/<project>/crew.py`
- `src/<project>/main.py`
- `.env.example`
- `pyproject.toml`
- `tests/`

先用 `rg --files` 找实际结构，不要假设路径固定。

## 3. Agent YAML 设计

每个 agent 至少明确：

```yaml
researcher:
  role: "Research specialist for current project context"
  goal: "Collect precise evidence needed by downstream tasks"
  backstory: "Focus on verified sources and concise handoff"
  tools: []
  verbose: true
  allow_delegation: false
```

设计原则：

- `role` 说明身份和范围。
- `goal` 可衡量。
- `backstory` 只放会影响行为的上下文。
- tools 越少越好，按任务授权。
- delegation 默认关闭，除非有明确管理者 agent。

## 4. Task YAML 设计

每个 task 至少明确：

```yaml
write_eval_plan:
  description: "Create an eval plan for the feature brief and architecture."
  expected_output: "Markdown with eval cases, metrics, release gates, and safety tests."
  agent: qa_engineer
  context:
    - design_architecture
  output_file: "artifacts/eval_plan.md"
```

设计原则：

- `description` 写任务和约束。
- `expected_output` 写格式和验收标准。
- `context` 只连必要上游。
- 对关键输出加 guardrail 或结构化校验。

## 5. Flow 设计

Flow 适合有分支、状态和恢复需求的流程。检查：

- State 使用 Pydantic 或等价 schema。
- `@start` 入口明确。
- `@listen` 连接表达真实依赖。
- `@router` 覆盖失败、默认和人工确认分支。
- 每个节点记录输入摘要、输出摘要、状态和错误。

## 6. 调试命令

优先按项目文档运行；无文档时可尝试：

```bash
crewai --version
crewai test
crewai run
crewai log-tasks-outputs
crewai replay -t <task_id>
crewai traces status
crewai deploy --status
```

不要打印 `.env` 中的真实密钥。检查环境变量时只确认是否存在，或过滤敏感值。

## 7. 部署前检查

- `crewai test` 或项目测试通过。
- `agents.yaml` 和 `tasks.yaml` 无悬空引用。
- `.env.example` 覆盖所需变量。
- 没有硬编码密钥。
- tracing 或日志在目标环境可用。
- 部署版本可回滚。
- 有 smoke test 输入。

## 8. 常见反模式

- 一个万能 agent 拥有所有工具。
- task 的 `expected_output` 只写“完成任务”。
- Flow router 只覆盖成功分支。
- 生产环境没有 trace，出错后只能猜。
- 先上多 Agent，再想测试和权限。
- 把记忆当数据库，缺少来源、过期和删除机制。
