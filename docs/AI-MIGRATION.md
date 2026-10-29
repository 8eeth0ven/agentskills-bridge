# AI 语义迁移

`migrate` 在现有解析与资产保全层上增加模型分析、实现生成、独立执行和修复循环。规则 `convert` 仍用于格式适配；两者不能以同一个成功标准解释。

## 模型配置

模型客户端直接调用 HTTP API，无强制 SDK 依赖，不从本机文件发现凭据。

| provider | 协议 | 凭据环境变量 | 模型环境变量 |
| --- | --- | --- | --- |
| `anthropic` | Anthropic Messages | `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_MODEL` |
| `openai` | OpenAI Responses | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| `openai-chat` | 兼容 Chat Completions | `OPENAI_API_KEY` | `OPENAI_MODEL` |

`--model` 优先；也可设置统一的 `MIGRATION_MODEL`。不提供模型时不会猜测默认型号。`--provider auto` 按已有凭据选择协议；多套凭据同时存在时宜明确指定 provider。

```bash
export OPENAI_API_KEY='<your-api-key>'
export MIGRATION_MODEL='<model-id>'
python3 cli.py migrate path/to/skill --target langchain \
  --provider openai --execute \
  --python .venv-runtime/bin/python --out out/migrated
```

自定义兼容服务使用 `--base-url '<provider-endpoint>'`，或 `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`。`--api-key-env NAME` 指定包含凭据的进程环境变量名称，参数本身不接受密钥值。模型支持的上下文、输出长度和结构化能力仍由所选服务决定；响应必须通过本地 JSON 契约检查。

## 分析、生成、验收

分析计划包含原文证据对应的要求、目标差异、真实工具契约、工作流步骤与依赖，以及冻结用例。没有足够依据实现的要求会成为 blocker，不会用虚构服务或占位结果补齐。

模型生成的主要代码为：

- `bridge_tools.py`：真实工具实现；可复用 `source/` 中允许使用的源脚本。
- `bridge_workflow.py`：`run(request)` 执行实际依赖、分支、错误路径和输出规则。
- 目标原生产物：Python agent、Crew 配置、流程图或技能宿主配置。

Python agent 入口约定为 `agent.py:build_agent(model=None)`；AutoGen 可使用 `model_client` 注入参数，CrewAI 使用 `build_crew(llm=None)`。注入的模型必须原样接入真实框架，不能通过伪造依赖、替代框架或捕获导入错误来假装运行成功。

独立验证器先检查文件、Python 语法和 JSON，再在子进程中运行冻结用例；原生适配器单独执行目标框架工具循环。确定性模型事件只替代模型决策，实际运行的框架和工具仍必须是真实实现。它不检验生产模型的泛化表现或任意业务等价性。

## 自定义冻结用例

`--acceptance` 接受 JSON 数组。额外用例不会作为验收数组交给首次生成器，失败反馈可以进入后续修复；期望结果始终由调用者决定。声明的验收文件会从源上下文和执行工作区排除；建议仍将它放在源目录之外，避免混入其他工具的输入。下面演示用例形状，函数名和输出应与具体源要求一致：

```json
[
  {
    "id": "shipping-boundary",
    "requirement_id": "external-user-acceptance",
    "kind": "function",
    "module": "bridge_workflow.py",
    "callable": "run",
    "input": {"request": {"subtotal": "100.00"}},
    "expected": {"shipping": "0.00"}
  }
]
```

`function` 的 input 是函数关键字参数；结果按 JSON 值比较。期望值只留在父进程，执行子进程只接收模块、函数名和输入；父进程核对实际结果，不接受生成代码自报通过。`cli_json` 用例则执行所指 Python 文件，以 JSON 标准输入提供 input，并检查 JSON 标准输出。用例可以放在仓库外，不必作为产品源文件提交。

## 修复与发布状态

每次修复只能修改允许的项目实现文件；源资料、冻结计划、验收期望、验证器和结果记录不由生成器改写。`--max-repairs 3` 表示首次生成后最多修复三次。

| 状态 | 含义 |
| --- | --- |
| `verified` | 静态、冻结行为用例和原生运行时验收均通过 |
| `unverified` | 已生成并静态检查，但没有请求执行 |
| `needs_input` | 源要求或外部服务行为等资料不足，存在分析 blocker |
| `needs_configuration` | 缺少目标依赖或实际宿主运行方式 |
| `failed` | 生成、行为或运行时仍失败，修复次数用尽 |

CLI 仅在 verified 时返回成功。默认只有通过的项目发布到 `--out`；`--keep-failed` 允许保留未验证代码供检查，不改变其状态。输出目录必须为空或不存在。配置、鉴权与传输错误同样会失败，不会被当作模型代码修复成功。

通过或显式保留的项目包含 `migration.json`，记录计划、验收指纹、实现尝试、实际观察与模型用量；`--report` 可另存可用的迁移报告。若配置、鉴权或传输错误发生在计划形成之前，可能只有错误诊断，没有迁移报告。报告会遮盖当前凭据与本机路径。模型调用次数与执行结果分开记录。

## 原生运行宿主

LangChain、Deep Agents、AutoGen AgentChat、CrewAI 及 CrewAI Skills 使用独立 Python 适配器。`--python` 选择已安装真实目标依赖的解释器；模型生成的 requirements 不会自动安装。缺依赖时先检查生成文件和要求，再自行安装所需依赖，并使用新的空输出目录重跑。

其他格式需要 `--runtime-command` 指定真实宿主适配程序，参数是 JSON argv 数组，不经过 shell：

```bash
python3 cli.py migrate path/to/skill --target n8n \
  --provider anthropic --model "$ANTHROPIC_MODEL" --execute \
  --runtime-command '["python", "host_adapter.py"]' \
  --out out/n8n
```

适配程序必须由你提供，实际加载目标项目、运行目标引擎并在结果不满足验收时返回非零。上面的 `host_adapter.py` 只是程序名示例，不随项目提供。`python` 会替换为 `--python` 解释器；命令在生成项目目录中运行。运行器检查该进程退出状态，不能自行识别一个任意用户命令是否真正调用了外部引擎，因此命令本身是用户信任的验收边界。

对于 Codex 界面配置、Claude subagent、通用 JSON、Mermaid 和 skill，文档或数据解析不等于宿主执行。没有实际宿主命令时，即使 Python 工具用例通过，也不会把迁移标为 verified。

## 上下文与隐私

发送给模型的内容为便携 IR 和允许的可读源文件：指令、参考内容与代码。原始二进制只登记资源信息；常见凭据文件名会排除，当前进程凭据值、常见密钥模式、私钥片段及本机来源路径会遮盖。它不是对任意商业秘密的自动识别器；只选择准备交给模型处理的资料。

`--context-chars` 控制源和原生产物上下文，默认 500000 字符。超过限制时失败并要求调整，而不是无声截断源要求。`--max-output-tokens` 控制模型输出上限，`--model-timeout` 与 `--runtime-timeout` 分别限制模型请求和单次执行。较大的计划或代码响应可以显式增加模型超时；兼容的 Anthropic 接口还可用 `--thinking disabled` 关闭扩展思考。

capsule 保存本地完整源普通文件，它不以模型上下文过滤结果替代原始资料。分享生成包前，按原资料的可分享范围处理；完整性校验也不提供来源签名。

`--execute` 的子进程使用受控环境、超时和输出限制，模型凭据不传入生成代码。它不是操作系统沙箱，不能约束所有文件或网络操作；对不可信来源和生成代码，应使用自己选择的隔离执行环境。

`--report` 必须位于 `--out` 之外，且不能覆盖源输入文件。工程内部已经包含 `migration.json`，额外报告不会在发布后破坏 capsule 的文件清单。行为用例和原生探针在独立临时项目副本中运行；原有实现文件被改写或删除会判失败，新增业务产物不随工程发布。

Anthropic 模式使用仅用于返回数据的 `migration_output` 结构化工具，再由本地规则校验 JSON；这个工具不会在模型端执行项目代码。OpenAI Responses 使用原生 JSON Schema，兼容 Chat 模式使用 JSON 对象并进行本地校验。

冻结前还会进行独立源码审阅，重新核算模型提出的预期结果、金额与边界条件，不把第一份计划直接当作正确答案。该步骤看不到生成实现或执行结果；冻结后修复只能改实现。
