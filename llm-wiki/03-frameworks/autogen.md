# AutoGen(AG2 / Microsoft)

> **autogen 已是正式转换目标(第 9 格式,2026-10-11 加入)**:emitter 产出 AG2 新 API(`autogen_agentchat.agents.AssistantAgent` + `build_agent(model_client=None)` 工厂)形态的 `agent.py` + `knowledge/`;parser 从 `AGENT_NAME`/`SKILL_DESCRIPTION`/`SYSTEM_MESSAGE` 自描述常量(回退 AssistantAgent/ConversableAgent 构造参数)提取。API 依据 microsoft/autogen 0.7.x(autogen-agentchat 异步 API)。

AutoGen 是微软开源的对话式多 agent 框架,经典 0.2 API(`pip install pyautogen` 或社区延续版 `pip install ag2`,import 名均为 `autogen`)以 `ConversableAgent` 对话循环为核心,`GroupChat` 负责多 agent 编排。

## 最小可用示例

最小双 agent(assistant + user_proxy)对话:

```python
#!/usr/bin/env python3
"""autogen_dual —— AutoGen 最小双 agent 示例。

依赖: pip install -U ag2        # 或 pip install pyautogen,import 名同为 autogen
运行: export OPENAI_API_KEY=sk-... && python autogen_dual.py
"""
import autogen

config_list = [{"model": "gpt-4o-mini", "api_key": "sk-..."}]

assistant = autogen.ConversableAgent(
    name="note_writer",
    system_message=(
        "你是一名技术笔记助手。"
        "完成笔记后在回复末尾输出 TERMINATE 结束对话。"
    ),
    llm_config={"config_list": config_list},
    human_input_mode="NEVER",        # 该 agent 永远不向人提问
)

user_proxy = autogen.ConversableAgent(
    name="user_proxy",
    llm_config=False,                # 不调模型,只转发消息/执行代码
    human_input_mode="TERMINATE",    # 收到 TERMINATE 才停止
    max_consecutive_auto_reply=5,
    is_termination_msg=lambda msg: msg.get("content", "").rstrip().endswith("TERMINATE"),
)

user_proxy.initiate_chat(
    assistant,
    message="把「AgentIR 字段清单」整理成一篇三节 Markdown 笔记。",
)
```

GroupChat 多 agent 编排:

```python
writer = autogen.ConversableAgent(
    name="writer",
    system_message="负责写笔记草稿,写完交给 reviewer。",
    llm_config={"config_list": config_list},
)
reviewer = autogen.ConversableAgent(
    name="reviewer",
    system_message="评审草稿;通过则输出终稿并结束(TERMINATE),否则指出问题退回 writer。",
    llm_config={"config_list": config_list},
)

groupchat = autogen.GroupChat(
    agents=[user_proxy, writer, reviewer],
    messages=[],
    max_round=12,
    speaker_selection_method="auto",   # 由 LLM 决定下一个发言者
)
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config={"config_list": config_list})
user_proxy.initiate_chat(manager, message="写一篇 AgentIR 笔记并完成评审。")
```

工具注册(caller 出 LLM 调用意图,executor 负责实际执行):

```python
def lookup_note(keyword: str) -> str:
    """按关键词查询本地知识库笔记。"""
    return "..."

autogen.register_function(
    lookup_note,
    caller=assistant,        # LLM 看到该工具的 schema
    executor=user_proxy,     # user_proxy 实际执行函数并回传结果
    description="按关键词查询本地知识库笔记",
)
```

## 字段说明

`ConversableAgent`:

| 参数 | 说明 |
|---|---|
| `name` | agent 名,对话与 GroupChat 中按此称呼 |
| `system_message` | system prompt,定义角色、行为与终止约定 |
| `llm_config` | `{"config_list": [{"model": ..., "api_key": ...}], "timeout": ...}`;传 `False` 表示不调模型(纯代理) |
| `human_input_mode` | `NEVER`(全自动)/ `ALWAYS`(每轮等人)/ `TERMINATE`(终止消息后等人) |
| `max_consecutive_auto_reply` | 自动回复轮数上限,防死循环 |
| `is_termination_msg` | 终止消息判定函数,约定俗成用 `TERMINATE` 结尾 |
| `code_execution_config` | 代码执行设置(user_proxy 常配 `work_dir`),传 `False` 关闭 |

`initiate_chat`:首条 `message` 即任务描述;`max_turns`、`summary_method` 可选。

`GroupChat` / `GroupChatManager`:

| 参数 | 说明 |
|---|---|
| `agents` | 参与对话的 agent 列表 |
| `max_round` | 最大发言轮数 |
| `speaker_selection_method` | `auto`(LLM 选)/ `round_robin` / `manual` / `random` |
| `send_introductions` | 开场互报角色 |

新一代 0.4 API(`autogen-agentchat`,异步,`AssistantAgent` + `RoundRobinGroupChat`/`SelectorGroupChat`)与上述 0.2 API 不兼容,import 路径与包名都不同,迁移时需整体重写。

## 与 AgentIR 的映射(已实现为 emitter/parser)

| AgentIR 字段 | AutoGen 落点 |
|---|---|
| `display_name` | `ConversableAgent(name=...)`(snake_case 化) |
| `system_prompt` | `system_message=...` |
| `tools` | `autogen.register_function(tool, caller=..., executor=...)`,需要一个执行方 agent |
| `tasks` | `initiate_chat` 的首条 `message`(多任务仅首条可承载,其余丢失) |
| `knowledge` / `scripts` | 侧车文件(同目录 `knowledge/`),README 说明,运行时不自动加载 |
| `name` / `description` / `default_prompt` / `metadata` | README 记录 |

## 转换注意事项(emitter 产物采用 0.4+ 新 API)

1. **多 agent 编排是核心特征**:AutoGen 的价值在对话循环与 GroupChat,AgentIR 是单 agent 中间表示——若将来支持,emit 只能生成"assistant + user_proxy"双 agent 最小形态,群聊编排需人工拆;parse 遇到 GroupChat 工程只能取主 agent 的 system_message,群结构与发言顺序全丢。
2. **终止协议必须显式写进 system_message**:AutoGen 靠 `TERMINATE` 约定结束,转换时若忘写会死循环到 `max_consecutive_auto_reply`/`max_round` 上限。
3. **两代 API 不兼容**:0.2(pyautogen/AG2,`import autogen`)与 0.4(`autogen_agentchat` 系列包)字段与心智模型都不同,parse 前必须先探测版本线。
4. **user_proxy 的代码执行能力**(`code_execution_config`)是安全敏感项,AgentIR 无对应字段,任何方向的转换都不应自动生成开启代码执行的配置。
