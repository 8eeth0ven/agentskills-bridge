# OpenAI 形态(openai.yaml + Agents SDK)

"OpenAI 形态"在本项目里指两种东西:a) **Codex / ChatGPT 的 skill 接入形态**——`agents/openai.yaml` 元数据 + `instructions.md` 全文指令;b) **OpenAI Agents SDK(Python)**——`Agent(name/instructions/handoffs/tools)` 纯 Python dataclass,无官方 YAML 形态。前者是纯声明式接入,后者是可执行程序。OpenAI 已正式采纳 **Agent Skills 开放规范**(agentskills.io;官方文档原话 "Skills build on the open agent skills standard",developers.openai.com/codex/skills/;Codex 与 ChatGPT 均在规范官网 Client Showcase 收录;2026-10-11 调研核实,Codex rust-v0.162.0 时代)。支持面:ChatGPT 桌面 App/Chat/Work、Codex CLI(`/skills`、`$skill` mention)、Codex IDE 扩展;上层分发格式是 plugins(`.codex-plugin/plugin.json` + 可选 `skills/`,官方 openai/skills 仓库已废弃迁移至 openai/plugins)。

## 最小可用示例

### 形态 a:agents/openai.yaml + instructions.md

目录结构:

```text
note-assistant/
├── agents/
│   └── openai.yaml       # UI 注册元数据
├── instructions.md       # 完整 system prompt
├── knowledge/
│   └── agentir.md        # 参考文档,LLM 按需读取
└── README.md             # Codex/ChatGPT UI 用法说明
```

`agents/openai.yaml`:

```yaml
interface:
  display_name: "Note Assistant"
  short_description: "Turn any topic into a structured Markdown note"
  default_prompt: "Use $note-assistant to turn my topic into a Markdown note with overview, key points, and examples."
```

`instructions.md`:

```markdown
# Note Assistant

你是一名技术笔记助手。

## 角色

把用户给的任何主题整理成结构化笔记,供后续直接使用。

## 规则

1. 只回答与笔记主题相关的问题
2. 涉及背景知识时先读 knowledge/ 目录下的参考文档
3. 输出使用 Markdown,含概述、要点、示例三节
```

仓库样例(完整字段同上):`examples/agent-fullcycle-engineering/agents/openai.yaml`:

```yaml
interface:
  display_name: "Agent Fullcycle Engineering"
  short_description: "Build agents with delegation and adaptive optimization"
  default_prompt: "Use $agent-fullcycle-engineering to design, delegate, build, test, observe, deploy, and adaptively optimize an AI agent from requirements to release."
```

要点:`default_prompt` 里的 `$note-assistant` / `$agent-fullcycle-engineering` 是 agent 引用名,必须与目录名(slug)一致,UI 靠它路由。

`agents/openai.yaml` 的出处与完整结构(2026-10-11 调研核实):它是 **OpenAI Codex skills 的可选元数据 sidecar**,由 Codex 源码常量定义(`SKILLS_METADATA_DIR="agents"` + `SKILLS_METADATA_FILENAME="openai.yaml"`),不是 agentskills.io 开放规范也不是第三方规范。完整三段为 `interface` / `policy` / `dependencies`:

```yaml
policy:
  allow_implicit_invocation: false   # 默认 true;false = 仅显式 $ 调用

dependencies:
  tools:
    - type: "mcp"
      value: "openaiDeveloperDocs"
      description: "OpenAI Docs MCP server"
      transport: "streamable_http"
      url: "https://developers.openai.com/mcp"
```

本项目目前只生成 `interface` 段;其余客户端安全忽略该文件,Codex 解析失败也 fail-open(仅告警)。历史沿革:曾为 `SKILL.json`(rust-v0.92.0,2026-01-27),后迁移为 `agents/openai.yaml`。

### 形态 b:OpenAI Agents SDK(Python)

`Agent()` 是纯 Python dataclass,一切配置走代码;**没有官方 YAML/JSON agent 定义形态**,SDK 本身也不读 SKILL.md(2026-10-11 源码核实)。单文件 `note_agent.py`:

```python
#!/usr/bin/env python3
"""note_agent —— OpenAI Agents SDK 最小实现。

依赖: pip install -U openai-agents
运行: 配置 OPENAI_API_KEY 环境变量后运行 python note_agent.py
"""
from agents import Agent, Runner, function_tool


@function_tool
def lookup_note(keyword: str) -> str:
    """按关键词查询本地知识库笔记,返回笔记摘要或「未找到」。"""
    notes = {
        "agentir": "AgentIR 是 skill 与 agent 之间的中间表示,"
        "字段含 name/display_name/system_prompt/tools/knowledge/tasks 等。",
        "openai": "OpenAI Agents SDK 由 openai-agents 包提供,import 名为 agents。",
    }
    return notes.get(keyword.lower(), "未找到")


note_agent = Agent(
    name="Note Assistant",
    instructions="""你是一名技术笔记助手。

## 角色
把用户给的任何主题整理成结构化笔记。

## 规则
1. 只回答与笔记主题相关的问题
2. 涉及背景知识时先调用 lookup_note 工具
3. 输出使用 Markdown""",
    handoffs=[],               # 多 agent 时把子 Agent 对象放这里,构成交接图
    tools=[lookup_note],
    # model="gpt-4o-mini",    # 缺省用环境配置的默认模型
)

if __name__ == "__main__":
    result = Runner.run_sync(note_agent, "什么是 AgentIR?")
    print(result.final_output)
```

多 agent 交接的最小骨架(说明 handoffs 语义):

```python
writer = Agent(name="writer", instructions="写笔记草稿,写完交给 reviewer。", handoffs=[])
reviewer = Agent(
    name="reviewer",
    instructions="评审草稿,通过则输出终稿。",
    handoffs=[writer],   # reviewer 可把活交回 writer
)
# Runner.run_sync(reviewer, "...") 时 SDK 按 LLM 决定在 agent 间交接
```

## Skills 目录与加载(Codex)

Codex 加载本地 skills 的目录约定(官方文档 "Where Codex loads local skills" + 源码 `codex-rs/ext/skills/src/`,2026-10-11 核实):

| Scope | 位置 | 说明 |
|---|---|---|
| REPO | `.agents/skills`(repo 级) | CWD 向上到 repo root 逐级扫描 |
| USER | `~/.agents/skills`(用户级,新) | 旧 `~/.codex/skills`(即 `$CODEX_HOME/skills`)已弃用,仅向后兼容 |
| ADMIN | `/etc/codex/skills` | 机器/容器级 |
| SYSTEM | `$CODEX_HOME/skills/.system` | Codex 内置(skill-creator、skill-installer 等) |

每个 skill 目录 = `SKILL.md`(必需)+ `scripts/`/`references/`/`assets/`(可选)+ `agents/openai.yaml`(可选)。Codex 只消费 frontmatter 的 `name`(≤64 字符,缺省回退目录名)/`description`(必填,空则拒载)/`metadata.short-description`(私有扩展),其余字段宽容忽略。初始列表预算:最多 2% 上下文窗口或 8000 字符;隐式触发可被 `policy.allow_implicit_invocation: false` 关闭。

## 字段说明

`agents/openai.yaml`:

| 字段 | 说明 |
|---|---|
| `interface.display_name` | UI 上显示的名称(≤64) |
| `interface.short_description` | 一句话用途,UI 列表展示,过长会被截断(≤1024) |
| `interface.default_prompt` | 默认调用话术;`$slug` 引用 agent 本身,slug 须与目录名一致(≤1024) |
| `interface.icon_small` / `icon_large` / `brand_color` | 可选:图标(须位于 skill 的 `assets/` 下相对路径)与品牌色(`#RRGGBB`) |
| `policy.allow_implicit_invocation` | 可选段;默认 true,false = 仅显式 `$skill` 调用 |
| `dependencies.tools[]` | 可选段;外部依赖(如 MCP server:`type`/`value`/`description`/`transport`/`url`) |

`instructions.md`:整个正文即 system prompt,无 frontmatter;建议首行 `# 标题`。

Agents SDK `Agent(...)`:

| 参数 | 类型 | 说明 |
|---|---|---|
| `name` | str | agent 名(交接时 LLM 看到的标识) |
| `instructions` | str 或 `(RunContext) -> str` | system prompt;传函数可按上下文动态生成 |
| `handoffs` | list[Agent] | 允许交接的下游 agent,构成有向交接图 |
| `tools` | list | `@function_tool` 函数,或 SDK 内置 `WebSearchTool` / `FileSearchTool` / `CodeInterpreterTool` |
| `model` | str | 模型名,缺省走全局默认 |
| `model_settings` | — | temperature、max_tokens 等 |
| `output_type` | type | 结构化输出(Pydantic 模型) |

`Runner`:`Runner.run_sync(agent, input)`(同步)/ `Runner.run(...)`(async)/ `Runner.run_streamed(...)`(流式);结果取 `.final_output`;`max_turns` 控制工具/交接轮数上限。

`@function_tool`:函数名即工具名,docstring 即描述,参数类型注解即 JSON Schema——与 LangChain `@tool` 同思路,导入路径为 `agents`。

## 与 AgentIR 的映射

| AgentIR 字段 | openai.yaml 形态 | Agents SDK 形态 |
|---|---|---|
| `name` | 目录名 / `$` 引用 slug | (文件与模块命名) |
| `display_name` | `interface.display_name` | `Agent(name=...)` |
| `description` | `interface.short_description` | 模块 docstring |
| `system_prompt` | `instructions.md 全文` | `instructions=...` 字符串字面量 |
| `default_prompt` | `interface.default_prompt` | README 示例输入 |
| `tools` | 无对应(README 说明) | `tools=[...]`(emit 生成 stub) |
| `knowledge` | `knowledge/*.md` 原样拷贝 | 同左(运行时需人工接 `FileSearchTool` 才可检索) |
| `tasks` / `scripts` / `metadata` | README 记录 | README 记录 |

## 转换注意事项

1. **yaml 形态零执行语义**:`agents/openai.yaml` 是 OpenAI Codex 的 skill 元数据 sidecar(interface/policy/dependencies 三段,本项目生成 interface 段),不是 agent 定义;agent 的全部行为都在 `instructions.md`——emit 时 system_prompt 必须完整落入 instructions.md,截断即丢行为。Agents SDK 侧无官方 YAML(`Agent()` 为纯 Python dataclass),SDK 也不读 SKILL.md——instructions 一次性全量进 system prompt,长文需自行截断/分层。
2. **short_description 要压缩**:Codex/ChatGPT UI 列表只显示很短的一行,AgentIR 的 `description` 往往过长,emit 时需裁剪,裁剪策略(取首句/首行)可能丢"何时用"信息。
3. **`$slug` 一致性**:default_prompt 中的引用名必须与 emit 出的目录名/slug 完全一致,否则 UI 无法路由。
4. **handoff 树无法还原**:SDK 形态的 `handoffs` 是有向图,AgentIR 是单 agent;反向解析 SDK 工程只能取主 Agent,交接结构与其余 agent 全部丢失;正向 emit 时 handoffs 恒为空。
5. **动态 instructions 解析不到**:`instructions` 支持传函数,`parse` 只认字符串字面量,函数生成的 prompt 丢失。
6. **工具 stub 不可用**:ToolSpec 无实现,emit 的 `@function_tool` 函数体是占位;内置工具(WebSearchTool 等)在 AgentIR 无对应概念。
7. **knowledge 双形态都不自动加载**:yaml 形态靠 UI 侧约定读取,SDK 形态要人工挂 `FileSearchTool`(还需先建 vector store),纯拷贝只是"文件在场"。
