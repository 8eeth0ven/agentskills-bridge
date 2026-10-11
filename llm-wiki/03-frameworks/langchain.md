# LangChain

LangChain 的 agent 由三部分组成:模型(`init_chat_model` 统一入口)、提示词(`ChatPromptTemplate` / `SystemMessagePromptTemplate`)、工具(`@tool` 装饰器或 `StructuredTool`)。构建 agent 的标准 API 是 langchain 1.x 的 `langchain.agents.create_agent(model, tools, *, system_prompt, ...)`(基于 langgraph,返回 `CompiledStateGraph`);langgraph 的 `create_react_agent` **已废弃**(`langgraph-prebuilt` 1.1.0 起 `@deprecated` 装饰,导入即告警,引导迁移到 `create_agent`);旧 0.x 生态用 `AgentExecutor`。版本快照:langchain 1.4.4 / langgraph 1.2.14 / langgraph-prebuilt 1.1.0 / deepagents 0.7.23(PyPI,2026-10-11 核实)。

## 最小可用示例

单文件 `agent.py`(内嵌 system prompt + 一个示例工具 + main 循环,可直接复制运行):

```python
#!/usr/bin/env python3
"""note_agent —— 最小 LangChain agent。

依赖: pip install -U langchain langchain-openai
运行: export OPENAI_API_KEY=sk-... && python agent.py
"""
import os

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

SYSTEM_PROMPT = """你是一名技术笔记助手。

## 角色
把用户给的任何主题整理成结构化笔记。

## 规则
1. 只回答与笔记主题相关的问题
2. 涉及背景知识时先调用 lookup_note 工具
3. 输出使用 Markdown
"""

# 知识清单(knowledge/ 目录内容的索引注释):
#   agentir.md   —— AgentIR 字段与辅助方法
#   notes.md     —— 笔记写作规范


@tool
def lookup_note(keyword: str) -> str:
    """按关键词查询本地知识库笔记,返回笔记摘要或"未找到"。"""
    notes = {
        "agentir": "AgentIR 是 skill 与 agent 之间的中间表示,"
        "字段含 name/display_name/system_prompt/tools/knowledge/tasks 等。",
        "langchain": "LangChain 1.0 用 create_agent 统一 agent 构建,底层基于 langgraph。",
    }
    return notes.get(keyword.lower(), "未找到")


def main() -> None:
    llm = init_chat_model(os.environ.get("MODEL", "openai:gpt-4o-mini"))
    agent = create_agent(
        llm,
        tools=[lookup_note],
        system_prompt=SYSTEM_PROMPT,
    )
    print("note_agent 就绪(输入 exit 退出)")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text or text.lower() in {"exit", "quit"}:
            break
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
        print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
```

langgraph `create_react_agent` 形态(**已废弃**,新代码不要生成;langgraph-prebuilt 1.1.0 起导入即弃用告警,官方引导改用 `langchain.agents.create_agent`;参数名也不同,`prompt` vs `system_prompt`):

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    llm,                        # init_chat_model(...) 或 ChatOpenAI 实例
    tools=[lookup_note],
    prompt=SYSTEM_PROMPT,       # 注意参数名是 prompt,不是 system_prompt
)
result = agent.invoke({"messages": [("user", "什么是 AgentIR?")]})
print(result["messages"][-1].content)
```

AgentExecutor 兼容写法(0.x 老工程,新代码不建议):

```python
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder("chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),   # 工具调用中间态,必填
])

llm = ChatOpenAI(model="gpt-4o-mini")
agent = create_tool_calling_agent(llm, [lookup_note], prompt)
executor = AgentExecutor(agent=agent, tools=[lookup_note], verbose=True, max_iterations=10)
print(executor.invoke({"input": "什么是 AgentIR?"})["output"])
```

提示词模板与工具定义的底层写法:

```python
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.tools import StructuredTool

# 单独构造 system 消息模板(支持 {variable} 占位)
system = SystemMessagePromptTemplate.from_template("你是一名{role},输出 Markdown。")
prompt = ChatPromptTemplate([system, ("human", "{input}")])
messages = prompt.invoke({"role": "技术笔记助手", "input": "你好"}).to_messages()


# 不用装饰器时,把普通函数包装成工具
def lookup_note(keyword: str) -> str:
    """按关键词查询本地知识库笔记。"""
    return "..."


note_tool = StructuredTool.from_function(func=lookup_note, name="lookup_note")
```

## 字段说明

`create_agent`(langchain 1.0,`from langchain.agents import create_agent`):

| 参数 | 类型 | 说明 |
|---|---|---|
| `model` | str / BaseChatModel | 模型或 `init_chat_model` 描述串(如 `openai:gpt-4o-mini`) |
| `tools` | list[BaseTool] | 工具列表 |
| `system_prompt` | str | 系统提示词,整段文本 |
| `middleware` | list | 1.0 中拦截/改写行为的中间件(记忆、人审等) |
| `response_format` | type | 结构化输出(如 Pydantic 模型) |
| `checkpointer` | — | 会话持久化(langgraph 侧配置) |

`create_react_agent`(langgraph,已废弃告警):`model` / `tools` / `prompt`(对应 system_prompt);`pre_model_hook`/`post_model_hook` 已被 langchain 1.x 的 middleware 体系取代。

工具定义:

| 方式 | 要点 |
|---|---|
| `@tool`(langchain) | 函数名即工具名;docstring 即工具描述,必写;参数类型注解即 JSON Schema |
| `StructuredTool.from_function` | 显式传 `name`/`description`/`func`/`args_schema`,适合已有函数 |
| `@function_tool`(openai-agents) | 同思路但属 OpenAI Agents SDK,导入路径为 `agents`,见 openai-agents 章 |

提示词:

| 组件 | 说明 |
|---|---|
| `ChatPromptTemplate.from_messages([...])` | 角色元组序列:`("system", ...)`/`("human", ...)`/`("ai", ...)` |
| `SystemMessagePromptTemplate` | 单独构造 system 消息,支持 `{variable}` 占位 |
| `MessagesPlaceholder("chat_history", optional=True)` | 注入历史消息列表;`agent_scratchpad` 在 AgentExecutor 形态必填 |

AgentExecutor(0.x):`agent`(由 create_tool_calling_agent 等构造)、`tools`、`verbose`、`max_iterations`、`handle_parsing_errors`。

## deepagents:官方 skills 运行时

LangChain 生态对 Agent Skills(agentskills.io 规范)的官方运行时落在 **deepagents** 包(仓库 langchain-ai/deepagents;`deepagents.middleware.skills` docstring 自述 "implements Anthropic's agent skills pattern with progressive disclosure";2026-10-11 源码调研核实):

```python
# pip install "deepagents>=0.7"  (当前 0.7.23)
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=FilesystemBackend(root_dir="./my-project"),
    skills=["./my-project/skills/"],   # 指向包含 skill 子目录的源目录
)
```

机制(与 Claude Agent SDK 一致的三级渐进披露):`SkillsMiddleware` 启动时把每个 `SKILL.md` frontmatter 的 name/description 注入系统提示;agent 判定匹配后用内置 `read_file` 读完整 SKILL.md 正文;`scripts/`/`references/`/`assets/` 仅在被引用时再读。

扩展能力:

- `metadata.include_tools`(空格分隔)声明 skill 专属工具,配 `SkillsMiddleware(backend=..., sources=[...], tools=[...])`;工具在 agent 读 SKILL.md 前被门控不可调用;支持 resolver `(name, Runtime) -> list[BaseTool]`(可映射 MCP 生成的工具名);
- 源分层 last-one-wins:`/skills/base/ → /skills/user/ → /skills/project/`,source 也可直接挂 `~/.claude/skills` 与 Claude Code 共用一套 SKILL.md;
- `FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")` 可做只读技能库。

注意:`create_agent` 本身**无 skills 参数**——官方文档给的方案是手工 `@tool load_skill` 工具 + system_prompt 里列技能清单;要标准 SKILL.md 加载就走 deepagents(`SkillsMiddleware` 是 langchain middleware,理论上也能挂到裸 `create_agent`,但官方文档把它归在 deepagents 产品线)。另:`langchain-ai/langchain-skills` 官方仓库是"给编码 agent 用的 SKILL.md 技能库"(21 个技能,`npx skills add` 安装),**是技能库不是运行时**。

### langgraph.json:部署清单而非 agent 定义

`langgraph.json` 存在,但是 LangGraph Server / `langgraph dev` / `langgraph build` 的**部署清单**,不是 agent 的 YAML/JSON 定义(agent 逻辑仍在 Python 代码里)。核心字段(源码 `langgraph_cli/schemas.py::Config`,2026-10-11 核实):

```json
{
  "dependencies": ["."],
  "graphs": { "my_agent": "./src/agent.py:agent" },
  "env": ".env"
}
```

`graphs` 是核心键(名字 → `"path/to/file.py:object"`,对象须是编译图,`create_agent`/`create_deep_agent` 返回值即符合);其余可选键:`python_version`(≥3.11)、`node_version`、`dockerfile_lines`、`base_image`、`store`、`checkpointer`、`auth`、`http`、`webhooks` 等;旧 `nodes` 键已移除,当前 Python CLI schema **无 `agents` 键**。

## 与 AgentIR 的映射

| AgentIR 字段 | LangChain 落点 |
|---|---|
| `system_prompt` | `create_agent(system_prompt=...)`;AgentExecutor 形态为 `("system", ...)` 元素;create_react_agent 形态为 `prompt=` |
| `tools` | `@tool` 函数(emit 只生成 stub:函数名、docstring、参数签名,函数体为占位) |
| `name` / `display_name` | 模块 docstring 与 `agent.py` 文件名(kebab→snake) |
| `description` | 模块 docstring 的"何时用"一句 |
| `knowledge` | 代码内注释清单 + 同目录 `knowledge/*.md`(运行时不自动加载) |
| `default_prompt` | README 中的示例输入 |
| `tasks` | 无对应,折进 system_prompt 或丢弃 |
| `scripts` / `metadata` | 不映射,README 记录 |

## 转换注意事项

1. **两代 API 并存,新代码一律 `create_agent`**:`create_agent`(langchain 1.x 标准 API,参数 `system_prompt`)与 `create_react_agent`(langgraph,参数 `prompt`;langgraph-prebuilt 1.1.0 起 `@deprecated` 装饰,导入即告警"moved to `langchain.agents`")签名不同。转换前必须确认目标环境版本,写错参数名会直接 TypeError。
2. **AgentExecutor 兼容路径有依赖成本**:需要 langchain 0.x 或 `langchain-agents` 兼容包,requirements.txt 必须写对版本线,否则 `agent_scratchpad` 那套模板跑不起来。
3. **parse 是 best-effort**:`parse_langchain` 用 AST/正则提取 `SYSTEM_PROMPT` 常量与 `@tool` 函数;动态构造的 prompt(lambda、f-string 拼接、外部注入)、运行时注册的工具都会丢失。
4. **工具 stub 不可用**:AgentIR 的 ToolSpec 只有名字与描述、没有实现,emit 出的 `@tool` 函数体是占位,必须人工补逻辑,否则一调用就报错。
5. **知识进不了运行时**:knowledge 内容以注释/同目录文件存在,agent 无法检索,除非人工接 RAG 或把内容塞进 system_prompt(注意上下文长度)。
6. **模型选择不落盘**:`init_chat_model("openai:gpt-4o-mini")` 里的 provider/model 串 AgentIR 不存,emit 默认写一个占位值,需人工改。
7. **记忆/多轮状态**:main 循环里每轮 `invoke` 默认不带 `chat_history`,AgentIR 也没有记忆概念;要连续对话需人工加 `middleware` 或消息列表累加。
