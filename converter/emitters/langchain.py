"""LangChain emitter:AgentIR -> 可独立阅读/运行的 agent.py(纯文本生成,不需要真跑 langchain)。

产出:
    <out>/agent.py          生成代码:SYSTEM_PROMPT 常量 + KNOWLEDGE 清单 + @tool stub
                            + create_agent 主流程(langchain>=1.0,注释给出两种替代写法)
    <out>/requirements.txt  langchain>=1.0 / langchain-openai
    <out>/knowledge/*.md    知识文档按 filename 拷贝
    <out>/README.md         安装与运行说明
"""

from __future__ import annotations

import json
import keyword
import re
from pathlib import Path
from typing import List, Optional, Tuple

from converter.ir import AgentIR, ToolSpec

_PY_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def emit_langchain(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 LangChain agent 脚本目录,返回 out_dir。"""
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
    return "\n\n".join(sections)


def _header(ir: AgentIR) -> str:
    title = ir.title()
    return (
        "#!/usr/bin/env python3\n"
        f'"""{title} —— LangChain agent。\n\n'
        "本文件由 agentskills-bridge 转换引擎自 AgentIR 生成,可独立阅读与修改:\n"
        "- SYSTEM_PROMPT:源 agent 的完整系统提示词;\n"
        "- KNOWLEDGE:随附知识文档清单(文件在同目录 knowledge/ 下);\n"
        "- 工具:均为 stub 实现,接入真实后端前请补全函数体;\n"
        '- 主流程:langchain>=1.0 的 create_agent(注释中给出 langgraph 与旧版替代写法)。\n'
        '"""\n\n'
        "from langchain.agents import create_agent\n"
        "from langchain.chat_models import init_chat_model\n"
        "from langchain_core.tools import tool\n"
        + ("from typing import Any\n" if _needs_any(ir) else "")
    )


def _prompt_section(ir: AgentIR) -> str:
    # AGENT_NAME/SKILL_DESCRIPTION 是自描述元数据:parse_langchain 优先
    # 提取它们,保证 roundtrip 不把 name 退化成文件名词干。
    desc = " ".join((ir.description or "").split()) or ir.title()
    desc = desc.replace("\\", "/").replace(chr(34), chr(39))
    return (
        "# ---------- 元数据与系统提示词(源自 AgentIR) ----------\n\n"
        f'AGENT_NAME = "{ir.name}"\n'
        f'SKILL_DESCRIPTION = "{desc.replace(chr(34), chr(39))}"\n\n'
        f"SYSTEM_PROMPT = {_py_triple(ir.system_prompt)}\n"
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
            "@tool\n"
            "def echo_tool(text: str) -> str:\n"
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
    # langchain 1.x 实测约束:create_agent(model, tools=*, system_prompt=*)
    # 首个位置参数名为 model(str | BaseChatModel);init_chat_model 需要
    # 具体 provider 包(langchain-openai 等)+ API key,故模块顶层只定义
    # 常量与工厂函数,导入零副作用,真实初始化推迟到 build_agent()/main。
    return (
        "# ---------- Agent 组装与入口 ----------\n\n"
        'DEFAULT_MODEL = "openai:gpt-4o-mini"  # 换模型改这里,如 "anthropic:claude-sonnet-4-5"\n'
        "\n"
        "\n"
        "def build_agent(model=None):\n"
        '    """组装 agent:model 缺省时按 DEFAULT_MODEL 用 init_chat_model 初始化。\n'
        "\n"
        "    model 也可直接传 BaseChatModel 实例(如测试注入 fake model),\n"
        "    天然支持任意 OpenAI 兼容 / Anthropic 兼容端点。\n"
        "    示例(GLM 双协议 + Claude 官方;密钥一律经环境变量注入,勿硬编码):\n"
        "\n"
        "        # 1) OpenAI 兼容端点(GLM v4 / DeepSeek / vLLM 等):\n"
        "        #    pip install langchain-openai\n"
        "        import os\n"
        "        from langchain_openai import ChatOpenAI\n"
        '        llm = ChatOpenAI(model="glm-4-flash", api_key=os.environ["GLM_API_KEY"],\n'
        '                         base_url="https://open.bigmodel.cn/api/paas/v4/")\n'
        "\n"
        "        # 2) Anthropic 兼容端点(GLM anthropic 路径等):\n"
        "        #    pip install langchain-anthropic\n"
        "        from langchain_anthropic import ChatAnthropic\n"
        '        llm = ChatAnthropic(model="glm-5.3-flash", api_key=os.environ["GLM_API_KEY"],\n'
        '                            base_url="https://open.bigmodel.cn/api/anthropic")\n'
        "\n"
        "        # 3) Claude 官方(不传 base_url 即默认官方端点):\n"
        '        llm = ChatAnthropic(model="claude-sonnet-4-5",\n'
        '                            api_key=os.environ["ANTHROPIC_API_KEY"])\n'
        "\n"
        "    然后 build_agent(model=llm) 即可换到对应端点。\n"
        '    """\n'
        "    llm = model if model is not None else init_chat_model(DEFAULT_MODEL)\n"
        "    return create_agent(llm, tools=TOOLS, system_prompt=SYSTEM_PROMPT)\n"
        "\n"
        "# 替代写法 A —— langgraph 的 create_react_agent:\n"
        "#   from langgraph.prebuilt import create_react_agent\n"
        "#   agent = create_react_agent(llm, tools=TOOLS, prompt=SYSTEM_PROMPT)\n"
        "# 替代写法 B —— 旧版 AgentExecutor(langchain<1.0):\n"
        "#   from langchain.agents import AgentExecutor, create_tool_calling_agent\n"
        "#   from langchain_core.prompts import ChatPromptTemplate\n"
        '#   prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("placeholder", "{messages}")])\n'
        "#   agent = AgentExecutor(agent=create_tool_calling_agent(llm, TOOLS, prompt), tools=TOOLS, verbose=True)\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    agent = build_agent()\n"
        "    # 读一次用户输入,跑一轮 agent。\n"
        '    user_input = input("你: ")\n'
        '    result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})\n'
        '    print("Agent:", result["messages"][-1].content)\n'
    )


# ---------- 工具 stub 生成 ----------

def _tool_stub(tool: ToolSpec) -> str:
    ident = _identifier(tool.name, "tool")
    params, _ = _params_from_schema(tool.input_schema)
    doc = (tool.description or f"工具 {tool.name or ident} 的 stub。").strip()
    return (
        "@tool\n"
        f"def {ident}({params}) -> str:\n"
        f"    {_py_triple(doc)}\n"
        "    # TODO(stub): 按 input_schema 接入真实实现,替换下面的占位返回。\n"
        f'    return "[stub] {ident} 尚未接入真实实现"\n'
    )


def _params_from_schema(schema: dict) -> Tuple[str, bool]:
    """把 JSON Schema properties 变成 Python 形参列表;返回 (参数串, 是否需要 Any)。"""
    props = (schema or {}).get("properties") or {}
    parts: List[str] = []
    needs_any = False
    for pname, pschema in props.items():
        ptype = _PY_TYPES.get(str((pschema or {}).get("type", "")).lower(), "Any")
        if ptype == "Any":
            needs_any = True
        parts.append(f"{_identifier(str(pname), 'arg')}: {ptype}")
    return ", ".join(parts), needs_any


def _needs_any(ir: AgentIR) -> bool:
    for t in ir.tools:
        props = (t.input_schema or {}).get("properties") or {}
        for pschema in props.values():
            if str((pschema or {}).get("type", "")).lower() not in _PY_TYPES:
                return True
    return False


def _identifier(name: str, fallback: str = "arg") -> str:
    """把任意名字规范成合法 Python 标识符。"""
    ident = re.sub(r"[^0-9A-Za-z_]+", "_", (name or "").strip())
    ident = re.sub(r"_+", "_", ident).strip("_")
    if not ident:
        return fallback
    if ident[0].isdigit():
        ident = "_" + ident
    if keyword.iskeyword(ident):
        ident += "_"
    return ident


def _py_triple(text: str) -> str:
    """把文本嵌成 Python 三引号字面量;含 \"\"\" 时改用 ''' 并处理冲突。"""
    if not text:
        return '""'
    delim = '"""'
    if delim in text:
        delim = "'''"
    body = text.replace("\\", "\\\\")
    if delim in body:
        body = body.replace(delim, "\\" + delim)
    if body.endswith(delim[0]):
        body = body[:-1] + "\\" + delim[0]
    return delim + body + delim


# ---------- 知识文档拷贝 ----------

def _safe_filename(filename: str) -> Optional[str]:
    """过滤非法路径名:为空、. / ..、含 / 或 \\ 或 .. 的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _write_knowledge(ir: AgentIR, out: Path) -> List[str]:
    written: List[str] = []
    for doc in ir.knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        kdir = out / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(doc.content or "", encoding="utf-8")
        written.append(name)
    return written


# ---------- 附带产物 ----------

def _requirements() -> str:
    return (
        "langchain>=1.0\n"
        "langchain-openai>=1.0    # OpenAI 兼容端点:gpt-4o / glm-4-flash / DeepSeek / vLLM ...\n"
        "langchain-anthropic>=1.0  # Anthropic 兼容端点:Claude 官方 / glm-5.3-flash(anthropic 路径)\n"
        "# 若改用替代写法 A(langgraph create_react_agent),请额外安装:\n"
        "# langgraph>=0.2\n"
    )


def _readme(ir: AgentIR) -> str:
    docs = [d for d in ir.knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 agent 未附带知识文档)"
    return f"""# {ir.title()} —— LangChain Agent(由 agentskills-bridge 生成)

## 文件

- agent.py —— 可运行的 agent 脚本(系统提示词 + 工具 stub + create_agent 主流程)
- requirements.txt —— Python 依赖
- knowledge/ —— 参考知识文档(清单与 agent.py 的 KNOWLEDGE 对应):
{listing}

## 运行

1. 安装依赖:`pip install -r requirements.txt`
2. 配置密钥:`export OPENAI_API_KEY=sk-...`(模型在 agent.py 中 `init_chat_model(...)` 处可换)
3. 运行:`python agent.py` —— 输入一句话,agent 执行一轮并打印回答

## 换任意 OpenAI / Anthropic 兼容端点

`build_agent(model=None)` 接受任意 `BaseChatModel` 实例,agent.py 的
`build_agent` docstring 内附三份可直接照抄的示例(GLM OpenAI 兼容路径 /
GLM Anthropic 兼容路径 / Claude 官方)。要点:

- OpenAI 兼容端点(GLM v4、DeepSeek、vLLM 等):
  `ChatOpenAI(model=..., api_key=..., base_url="https://open.bigmodel.cn/api/paas/v4/")`
- Anthropic 兼容端点(GLM anthropic 路径):
  `ChatAnthropic(model=..., api_key=..., base_url="https://open.bigmodel.cn/api/anthropic")`
- Claude 官方:`ChatAnthropic(model="claude-sonnet-4-5", api_key=...)`(不传 base_url)

密钥经环境变量注入,不要写进代码或仓库。

## 说明

- 工具均为 stub,返回占位文本;请把 agent.py 中各 `@tool` 函数体替换为真实实现。
- agent.py 注释里给出了两种替代组装写法:langgraph `create_react_agent` 与旧版 `AgentExecutor`(langchain<1.0)。
- 若想让 agent 使用 knowledge/ 文档,请自行接入检索(如 Retrieval 工具/RAG),文档清单已在 KNOWLEDGE 中列出。
"""
