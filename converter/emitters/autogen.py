"""AutoGen (AG2) emitter:AgentIR -> AssistantAgent 项目(纯文本生成,不需要真跑 autogen)。

产出:
    <out>/agent.py          生成代码:AGENT_NAME/SKILL_DESCRIPTION 自描述常量
                            + SYSTEM_MESSAGE 三引号全文 + 工具 stub + TOOLS 清单
                            + build_agent(model_client=None) 工厂(AG2 新 API:
                              AssistantAgent + OpenAIChatCompletionClient)
                            + 旧 ConversableAgent 兼容注释块 + __main__ 读输入跑一轮
    <out>/requirements.txt  autogen-agentchat / autogen-ext[openai]
    <out>/knowledge/*.md    知识文档按 filename 拷贝(复用 langchain emitter 逻辑)
    <out>/README.md         安装与运行说明

API 事实(2026-10 核对 microsoft/autogen 0.7.x / autogen-agentchat 0.7.5):
- 新 API:from autogen_agentchat.agents import AssistantAgent;
  AssistantAgent(name=..., system_message=..., model_client=..., tools=[...]);
  模型客户端用 autogen_ext.models.openai.OpenAIChatCompletionClient(model=...)。
- 旧 API(autogen<0.4 / pyautogen 兼容):autogen.ConversableAgent(
  name=..., system_message=..., llm_config={"config_list": [...]})。
- AgentChat 的 run() 是协程,__main__ 用 asyncio.run 包一层。

模块顶层只定义常量与工厂函数(导入零副作用,OpenAIChatCompletionClient
初始化需要 API key),真实组装推迟到 build_agent()/main —— 与 deepagents
emitter 修好的模式一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from converter.ir import AgentIR, ToolSpec

# 复用 langchain emitter 的成熟 helper(同包内私有导入,接口稳定)
from .langchain import (
    _identifier,
    _params_from_schema,
    _py_triple,
    _safe_filename,
    _tool_docstring,
    _write_knowledge,
)


def emit_autogen(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 AutoGen (AG2) agent 脚本目录,返回 out_dir。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    (out / "agent.py").write_text(_agent_py(ir), encoding="utf-8")
    (out / "requirements.txt").write_text(_requirements(), encoding="utf-8")
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


# ---------- agent.py 生成 ----------

def _agent_py(ir: AgentIR) -> str:
    sections = [
        _header(ir),
        _prompt_section(ir),
        _knowledge_section(ir),
        _tools_section(ir),
        _main_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _header(ir: AgentIR) -> str:
    return (
        "#!/usr/bin/env python3\n"
        f'"""{ir.title()} —— AutoGen (AG2) AssistantAgent。\n\n'
        "本文件由 agentskills-bridge 转换引擎自 AgentIR 生成,可独立阅读与修改:\n"
        "- SYSTEM_MESSAGE:源 agent 的完整系统提示词;\n"
        "- KNOWLEDGE:随附知识文档清单(文件在同目录 knowledge/ 下);\n"
        "- 工具:均为 stub 实现,接入真实后端前请补全函数体;\n"
        "- 主流程:AG2 新 API(AssistantAgent + OpenAIChatCompletionClient),\n"
        "  组装推迟到 build_agent() 工厂,顶层导入零副作用;\n"
        "- 文件末尾注释给出旧版 ConversableAgent(autogen<0.4 / pyautogen)兼容写法。\n"
        '"""\n\n'
        "import asyncio\n"
        "\n"
        "from autogen_agentchat.agents import AssistantAgent\n"
        "from autogen_ext.models.openai import OpenAIChatCompletionClient\n"
    )


def _prompt_section(ir: AgentIR) -> str:
    # AGENT_NAME/SKILL_DESCRIPTION 是自描述元数据:parse_autogen 优先提取
    # 它们,保证 roundtrip 不把 name 退化成文件名词干(与 langchain 一致)。
    desc = " ".join((ir.description or "").split()) or ir.title()
    desc = desc.replace("\\", "/").replace(chr(34), chr(39))
    return (
        "# ---------- 元数据与系统提示词(源自 AgentIR) ----------\n\n"
        f'AGENT_NAME = "{ir.name}"\n'
        f'SKILL_DESCRIPTION = "{desc}"\n\n'
        f"SYSTEM_MESSAGE = {_py_triple(ir.system_prompt)}\n"
    )


def _knowledge_section(ir: AgentIR) -> str:
    entries = []
    for doc in ir.knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        item = {"file": f"knowledge/{name}", "title": doc.title or name}
        entries.append(f"    {json.dumps(item, ensure_ascii=False)},")
    body = "\n".join(entries) if entries else "    # 源 agent 未附带知识文档。"
    return (
        "# ---------- 知识清单(内容位于同目录 knowledge/ 下) ----------\n\n"
        f"KNOWLEDGE = [\n{body}\n]\n"
    )


def _tools_section(ir: AgentIR) -> str:
    if not ir.tools:
        stubs = (
            "async def echo_tool(text: str) -> str:\n"
            '    """示例工具:原样返回输入文本(源 agent 未定义工具时的占位)。"""\n'
            "    return text\n"
        )
        tools_list = "TOOLS = [echo_tool]"
    else:
        sources = [_tool_stub(t) for t in ir.tools]
        stubs = "\n\n".join(sources)
        tools_list = "TOOLS = [" + ", ".join(_identifier(t.name, "tool") for t in ir.tools) + "]"
    return (
        "# ---------- 工具定义(均为 stub,请接入真实实现) ----------\n\n"
        f"{stubs}\n\n{tools_list}\n"
    )


def _main_section() -> str:
    # AG2 0.4+ 实测约束:AssistantAgent 组装需要 model_client 实例,
    # OpenAIChatCompletionClient 初始化需要 autogen-ext[openai] + API key,
    # 故模块顶层只定义常量与工厂函数,真实初始化推迟到 build_agent()/main
    # (与 deepagents/langchain emitter 的零副作用导入模式一致)。
    return (
        "# ---------- Agent 组装与入口 ----------\n\n"
        'DEFAULT_MODEL = "gpt-4o-mini"  # 换模型改这里,如 "gpt-4.1" / "gpt-4o"\n'
        "\n"
        "# 非官方模型名(如 GLM 的 glm-4-flash / glm-5.3-flash)不在 autogen-ext\n"
        "# 内置模型表内,必须显式声明 model_info(2026-10 实测 autogen-ext 0.7.5,\n"
        "# 缺省会 ValueError: model_info is required):\n"
        "MODEL_INFO = {\n"
        '    "function_calling": True,\n'
        '    "json_output": True,\n'
        '    "vision": False,\n'
        '    "family": "unknown",\n'
        '    "structured_output": False,\n'
        '    "multiple_system_messages": True,\n'
        "}\n"
        "\n"
        "\n"
        "def _runtime_name() -> str:\n"
        '    """AGENT_NAME(kebab-case 元数据)→ AG2 可用的 Python 标识符。\n\n'
        "    AG2 AssistantAgent 硬性要求 name 为合法 Python 标识符,\n"
        "    连字符不合法(实测 0.7.5 报 ValueError);AGENT_NAME 常量保持\n"
        "    kebab-case 供 roundtrip/展示,运行时在此归一。\n"
        '    """\n'
        "    candidate = AGENT_NAME.replace(\"-\", \"_\")\n"
        "    return candidate if candidate.isidentifier() else \"agent\"\n"
        "\n"
        "\n"
        "def build_agent(model_client=None):\n"
        '    """组装 AssistantAgent:model_client 缺省时按 DEFAULT_MODEL 新建客户端。\n\n'
        "    model_client 也可直接传已配置的 ChatCompletionClient 实例\n"
        "    (如测试注入 ReplayChatCompletionClient)。\n\n"
        "    GLM(智谱开放平台)双端点接法,2026-10 实测(autogen-ext 0.7.5):\n"
        "    - OpenAI 兼容(GLM v4,模型如 glm-4-flash):\n"
        "        OpenAIChatCompletionClient(\n"
        '            model="glm-4-flash", api_key=<GLM_API_KEY>,\n'
        '            base_url="https://open.bigmodel.cn/api/paas/v4",\n'
        "            model_info=MODEL_INFO, max_tokens=1024)\n"
        "    - Anthropic 兼容(模型如 glm-5.3-flash,需 autogen-ext[anthropic];\n"
        "      anthropic SDK 用 <1.13,1.13.0 起 messages.create 移除 temperature\n"
        "      与 autogen-ext 固定发送的参数冲突,实测 0.98.1 可用):\n"
        "        AnthropicChatCompletionClient(\n"
        '            model="glm-5.3-flash", api_key=<GLM_API_KEY>,\n'
        '            base_url="https://open.bigmodel.cn/api/anthropic",\n'
        "            model_info=MODEL_INFO, max_tokens=2048)\n"
        '    """\n'
        "    client = (\n"
        "        model_client\n"
        "        if model_client is not None\n"
        "        else OpenAIChatCompletionClient(model=DEFAULT_MODEL)\n"
        "    )\n"
        "    return AssistantAgent(\n"
        "        # AG2 硬性要求 name 为合法 Python 标识符;AGENT_NAME 是\n"
        "        # kebab-case 元数据(roundtrip 用),运行时必须归一成下划线。\n"
        "        name=_runtime_name(),\n"
        "        system_message=SYSTEM_MESSAGE,\n"
        "        model_client=client,\n"
        "        tools=TOOLS,  # 不需要工具调用可整行删除\n"
        "    )\n"
        "\n"
        "# 兼容写法 —— 旧版 ConversableAgent(autogen<0.4 / pyautogen):\n"
        "#   import os\n"
        "#   from autogen import ConversableAgent\n"
        "#   agent = ConversableAgent(\n"
        "#       name=AGENT_NAME,\n"
        "#       system_message=SYSTEM_MESSAGE,\n"
        '#       llm_config={"config_list": [{"model": DEFAULT_MODEL,\n'
        '#                                     "api_key": os.environ["OPENAI_API_KEY"]}]},\n'
        '#       human_input_mode="NEVER",\n'
        "#   )\n"
        "\n"
        "\n"
        "def _client_from_env():\n"
        '    """按环境变量组装模型客户端(main 入口的可配置接线)。\n\n'
        "    环境变量(缺省回落 DEFAULT_MODEL 与各 SDK 官方默认端点):\n"
        "    - AGENT_LLM_PROTOCOL: 协议选择,openai(默认)| anthropic\n"
        "    - AGENT_MODEL: 模型名(如 glm-4-flash / glm-5.3-flash / gpt-4o-mini)\n"
        "    - OPENAI_API_KEY / OPENAI_BASE_URL: OpenAI 协议密钥与自定义端点\n"
        "    - ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL: Anthropic 协议密钥与端点\n\n"
        "    GLM(智谱开放平台)双端点接法示例:\n"
        "      OpenAI 兼容(GLM v4,三个变量各占一行 export):\n"
        "        export AGENT_MODEL=glm-4-flash\n"
        "        export OPENAI_API_KEY=<GLM_API_KEY>\n"
        "        export OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4\n"
        "      Anthropic 兼容:\n"
        "        export AGENT_LLM_PROTOCOL=anthropic\n"
        "        export AGENT_MODEL=glm-5.3-flash\n"
        "        export ANTHROPIC_API_KEY=<GLM_API_KEY>\n"
        "        export ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic\n"
        '    """\n'
        "    import os\n"
        "\n"
        '    protocol = os.environ.get("AGENT_LLM_PROTOCOL", "openai").lower()\n'
        '    model = os.environ.get("AGENT_MODEL") or DEFAULT_MODEL\n'
        '    if protocol == "anthropic":\n'
        "        from autogen_ext.models.anthropic import AnthropicChatCompletionClient\n"
        "\n"
        "        try:\n"
        "            return AnthropicChatCompletionClient(\n"
        "                model=model,\n"
        '                api_key=os.environ.get("ANTHROPIC_API_KEY"),\n'
        '                base_url=os.environ.get("ANTHROPIC_BASE_URL"),\n'
        "                max_tokens=2048,\n"
        "            )\n"
        "        except ValueError:\n"
        "            # 非官方模型名(如 GLM glm-5.3-flash)需显式 model_info\n"
        "            return AnthropicChatCompletionClient(\n"
        "                model=model,\n"
        '                api_key=os.environ.get("ANTHROPIC_API_KEY"),\n'
        '                base_url=os.environ.get("ANTHROPIC_BASE_URL"),\n'
        "                max_tokens=2048,\n"
        "                model_info=MODEL_INFO,\n"
        "            )\n"
        "    try:\n"
        "        return OpenAIChatCompletionClient(\n"
        "            model=model,\n"
        '            api_key=os.environ.get("OPENAI_API_KEY"),\n'
        '            base_url=os.environ.get("OPENAI_BASE_URL"),\n'
        "            max_tokens=1024,\n"
        "        )\n"
        "    except ValueError:\n"
        "        # 非官方模型名(如 GLM glm-4-flash)需显式 model_info\n"
        "        return OpenAIChatCompletionClient(\n"
        "            model=model,\n"
        '            api_key=os.environ.get("OPENAI_API_KEY"),\n'
        '            base_url=os.environ.get("OPENAI_BASE_URL"),\n'
        "            max_tokens=1024,\n"
        "            model_info=MODEL_INFO,\n"
        "        )\n"
        "\n"
        "\n"
        "async def main() -> None:\n"
        '    """读一次用户输入,跑一轮 agent 并打印回答。"""\n'
        "    agent = build_agent(model_client=_client_from_env())\n"
        '    user_input = input("你: ")\n'
        "    result = await agent.run(task=user_input)\n"
        '    print("Agent:", result.messages[-1].to_text())\n'
        "\n"
        'if __name__ == "__main__":\n'
        "    asyncio.run(main())\n"
    )


# ---------- 工具 stub 生成(AG2 工具是普通函数,无装饰器) ----------

def _tool_stub(tool: ToolSpec) -> str:
    ident = _identifier(tool.name, "tool")
    params, _ = _params_from_schema(tool.input_schema)
    doc = _tool_docstring(
        (tool.description or f"工具 {tool.name or ident} 的 stub。").strip(),
        tool.input_schema,
        tool.side_effects,
    )
    return (
        f"async def {ident}({params}) -> str:\n"
        f"    {_py_triple(doc)}\n"
        "    # TODO(stub): 按 input_schema 接入真实实现,替换下面的占位返回。\n"
        f'    return "[stub] {ident} 尚未接入真实实现"\n'
    )


# ---------- 附带产物 ----------

def _requirements() -> str:
    return (
        "# AG2 新 API(AssistantAgent + OpenAIChatCompletionClient)最低 0.4,\n"
        "# 2026-10 最新为 0.7.x;旧 ConversableAgent 兼容写法见 agent.py 注释。\n"
        "autogen-agentchat>=0.4\n"
        "autogen-ext[openai]>=0.4\n"
        "# 可选:Anthropic 兼容端点(如 GLM /api/anthropic)需 anthropic 扩展;\n"
        "# 注意 anthropic SDK 需 <1.13(1.13.0 起 messages.create 移除 temperature,\n"
        "# 与 autogen-ext 0.7.5 固定发送的参数冲突;2026-10 实测 0.98.1 可用)。\n"
        "# autogen-ext[anthropic]>=0.4\n"
    )


def _readme(ir: AgentIR) -> str:
    docs = [d for d in ir.knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 agent 未附带知识文档)"
    return f"""# {ir.title()} —— AutoGen (AG2) Agent(由 agentskills-bridge 生成)

## 文件

- agent.py —— 可运行的 agent 脚本(AGENT_NAME/SKILL_DESCRIPTION/SYSTEM_MESSAGE
  常量 + 工具 stub + build_agent 工厂 + asyncio 主循环)
- requirements.txt —— Python 依赖
- knowledge/ —— 参考知识文档(清单与 agent.py 的 KNOWLEDGE 对应):
{listing}

## 运行

1. 安装依赖:`pip install -r requirements.txt`
2. 配置密钥:`export OPENAI_API_KEY=sk-...`(模型在 agent.py 中 `DEFAULT_MODEL` 处可换)
3. 运行:`python agent.py` —— 输入一句话,agent 执行一轮并打印回答

### 接入 GLM(智谱开放平台)—— 双端点任选

`main` 支持环境变量选协议与 base_url(见 agent.py `_client_from_env` 文档):
模型名、密钥、端点全部可配,零改码切换 OpenAI 兼容 / Anthropic 兼容端点。

OpenAI 兼容路径(GLM v4,模型如 glm-4-flash):

```bash
export AGENT_MODEL=glm-4-flash
export OPENAI_API_KEY=<GLM_API_KEY>
export OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
python agent.py
```

Anthropic 兼容路径(模型如 glm-5.3-flash;先 `pip install "autogen-ext[anthropic]"
"anthropic<1.13"`,1.13.0 起官方 SDK 删了 temperature 与 autogen-ext 冲突):

```bash
export AGENT_LLM_PROTOCOL=anthropic
export AGENT_MODEL=glm-5.3-flash
export ANTHROPIC_API_KEY=<GLM_API_KEY>
export ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic
python agent.py
```

程序内接线(等价写法,非官方模型名需显式 `model_info=MODEL_INFO`,常量已内置):

```python
from autogen_ext.models.openai import OpenAIChatCompletionClient
client = OpenAIChatCompletionClient(
    model="glm-4-flash", api_key="<GLM_API_KEY>",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    model_info=MODEL_INFO, max_tokens=1024)
agent = build_agent(model_client=client)
```

## 说明

- 主流程用 AG2(AutoGen 0.4+)新 API:`autogen_agentchat.agents.AssistantAgent`
  + `autogen_ext.models.openai.OpenAIChatCompletionClient`;agent 组装在
  `build_agent(model_client=None)` 工厂里完成,便于测试注入 fake client。
- 旧版兼容:agent.py 注释里给出 `autogen.ConversableAgent(name=...,
  system_message=..., llm_config=...)` 的 autogen<0.4 / pyautogen 写法。
- 工具均为 stub,返回占位文本;请把 agent.py 中各工具函数体替换为真实实现
  (AG2 工具是带类型注解的普通/异步函数,签名即 schema)。
- 若想让 agent 使用 knowledge/ 文档,请自行接入检索工具或 RAG,文档清单已在
  KNOWLEDGE 中列出。
"""
