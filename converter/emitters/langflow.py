"""Langflow emitter:AgentIR -> flow.json(Langflow 官方导出格式,1.12 实测)。

链路(与官方 Basic Prompting starter 同构):
    ChatInput --message--> Prompt --prompt(system_message)--> LanguageModelComponent
    LanguageModelComponent --text_output--> ChatOutput

格式要点(依据 langflow main@1.12.5 调研,/tmp/research/langflow-skills.md):
    - reactflow 外层 type="genericNode",id = "{PascalCaseType}-{5位随机}";
    - data.type 为 PascalCase 短类名(ChatInput/Prompt/LanguageModelComponent/ChatOutput);
    - handle 字符串 = json.dumps 后 '"'→'œ'(U+0153),边 data 里另附结构化对象(官方双写);
    - Prompt 的提示词文本在 data.node.template.template.value;
    - LLM 用 LanguageModelComponent(model_name/provider/api_key),Prompt 输出接 system_message。

产出:
    <out>/flow.json      可导入 Langflow 的完整 flow
    <out>/knowledge/*.md 知识文档按 filename 拷贝(不随 flow.json 导入)
    <out>/README.md      UI 导入方式 + Knowledge 两步上传 API 说明
"""

from __future__ import annotations

import json
import random
import string
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from converter.ir import AgentIR

_SUFFIX_CHARS = string.ascii_letters + string.digits
_OE = "\u0153"  # œ —— langflow 全栈约定的 handle 引号替身

_DEFAULT_MODEL_OPTIONS = [
    "gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "gpt-4.5-preview", "gpt-4-turbo", "gpt-4-turbo-preview", "gpt-4",
    "gpt-3.5-turbo",
]


def emit_langflow(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 Langflow flow 目录,返回 out_dir。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    (out / "flow.json").write_text(
        json.dumps(_flow(ir), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


# ---------- handle 字符串(œ 约定) ----------

def _handle_json(d: Dict[str, Any]) -> str:
    """官方 handle 字符串:json.dumps(默认带空格分隔)后 '"'→'œ'。"""
    return json.dumps(d, ensure_ascii=False).replace('"', _OE)


def _handle_json_compact(d: Dict[str, Any]) -> str:
    """边 id 用的紧凑形态(分隔符无空格,同样替换引号)。"""
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace('"', _OE)


def _src_handle(data_type: str, node_id: str, name: str, output_types: List[str]) -> Dict[str, Any]:
    return {"dataType": data_type, "id": node_id, "name": name, "output_types": list(output_types)}


def _tgt_handle(field_name: str, node_id: str, input_types: List[str], ftype: str) -> Dict[str, Any]:
    return {"fieldName": field_name, "id": node_id, "inputTypes": list(input_types), "type": ftype}


def _edge(src_id: str, src_handle: Dict[str, Any], tgt_id: str, tgt_handle: Dict[str, Any]) -> dict:
    """官方导出形态:handle 双写(字符串 + data 内结构化对象)。"""
    return {
        "animated": False,
        "className": "",
        "data": {"sourceHandle": src_handle, "targetHandle": tgt_handle},
        "id": (
            f"reactflow__edge-{src_id}{_handle_json_compact(src_handle)}"
            f"-{tgt_id}{_handle_json_compact(tgt_handle)}"
        ),
        "selected": False,
        "source": src_id,
        "sourceHandle": _handle_json(src_handle),
        "target": tgt_id,
        "targetHandle": _handle_json(tgt_handle),
    }


# ---------- 节点组装 ----------

def _rand_suffix(n: int = 5) -> str:
    """官方节点 id 后缀:{Type}-{5位随机字母数字}。"""
    return "".join(random.choices(_SUFFIX_CHARS, k=n))


def _field(name: str, display_name: str, ftype: str, value: Any, **extra: Any) -> Dict[str, Any]:
    """输入字段 dict:name/display_name/type/value/show/advanced/input_types/list 至少齐备。

    其余官方键(options/_input_type/multiline/fileTypes/...)通过 kwargs 原样并入。
    """
    advanced = bool(extra.pop("advanced", False))
    show = bool(extra.pop("show", True))
    required = bool(extra.pop("required", False))
    field: Dict[str, Any] = {
        "advanced": advanced,
        "display_name": display_name,
        "dynamic": False,
        "info": extra.pop("info", ""),
        "input_types": list(extra.pop("input_types", [])),
        "list": bool(extra.pop("list_", False)),
        "load_from_db": bool(extra.pop("load_from_db", False)),
        "name": name,
        "placeholder": "",
        "required": required,
        "show": show,
        "title_case": False,
        "trace_as_input": bool(extra.pop("trace_as_input", False)),
        "trace_as_metadata": bool(extra.pop("trace_as_metadata", False)),
        "type": ftype,
        "value": value,
    }
    field.update(extra)
    return field


def _output(name: str, display_name: str, method: str, types: List[str]) -> Dict[str, Any]:
    return {
        "allows_loop": False,
        "cache": True,
        "display_name": display_name,
        "group_outputs": False,
        "method": method,
        "name": name,
        "selected": types[0],
        "tool_mode": True,
        "types": list(types),
        "value": "__UNDEFINED__",
    }


def _make_node(
    node_type: str,
    display_name: str,
    description: str,
    position: Dict[str, float],
    fields: List[Dict[str, Any]],
    base_classes: List[str],
    field_order: List[str],
    outputs: List[Dict[str, Any]],
    icon: str,
    custom_fields: Optional[Dict[str, List[str]]] = None,
    selected_output: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 reactflow 节点:外层 type="genericNode",data.type=PascalCase 类名。

    id = "{node_type}-{5位随机}",data.id 与之一致;template._type="Component"。
    schema 对齐(官方 v1.9 starter fixture 实测):
      - data.display_name / data.description:官方导出把节点元数据双写到 data 层,
        前端画布节点标题显示用(运行时非必需,但对齐官方导出形态);
      - data.node.custom_fields:官方四个节点一致携带(无动态字段时为 {}),
        动态输入口注册表(仅 Prompt 用到非空值)。
    """
    node_id = f"{node_type}-{_rand_suffix()}"
    template: Dict[str, Any] = {"_type": "Component"}
    template.update({f["name"]: f for f in fields})
    data_node: Dict[str, Any] = {
        "base_classes": list(base_classes),
        "custom_fields": custom_fields if custom_fields is not None else {},
        "description": description,
        "display_name": display_name,
        "field_order": list(field_order),
        "frozen": False,
        "icon": icon,
        "outputs": outputs,
        "template": template,
    }
    data: Dict[str, Any] = {
        "description": description,
        "display_name": display_name,
        "id": node_id,
        "node": data_node,
        "type": node_type,
    }
    if selected_output:
        data["selected_output"] = selected_output
    return {
        "data": data,
        "dragging": False,
        "id": node_id,
        "position": dict(position),
        "positionAbsolute": dict(position),
        "selected": False,
        "type": "genericNode",
        "width": 320,
    }


def _chat_input_node(position: Dict[str, float]) -> Dict[str, Any]:
    fields = [
        _field(
            "input_value", "Input Text", "str", "",
            info="Message to be passed as input.", multiline=True,
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "should_store_message", "Store Messages", "bool", True,
            advanced=True, info="Store the message in the history.",
            trace_as_metadata=True, _input_type="BoolInput",
        ),
        _field(
            "sender", "Sender Type", "str", "User",
            advanced=True, info="Type of sender.",
            options=["Machine", "User"], trace_as_metadata=True,
        ),
        _field(
            "sender_name", "Sender Name", "str", "User",
            advanced=True, info="Name of the sender.", input_types=["Message"],
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "session_id", "Session ID", "str", "",
            advanced=True,
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            input_types=["Message"], trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "files", "Files", "file", [],
            advanced=True, info="Files to be sent with the message.",
            list_=True, fileTypes=[], file_path="", temp_file=True,
            trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "ChatInput", "Chat Input", "Get chat inputs from the Playground.", position,
        fields,
        ["Message"],
        ["input_value", "store_message", "sender", "sender_name", "session_id", "files"],
        [_output("message", "Chat Message", "message_response", ["Message"])],
        icon="ChatInput",
        custom_fields={},
        selected_output="message",
    )


def _prompt_node(ir: AgentIR, position: Dict[str, float]) -> Dict[str, Any]:
    """Prompt 组件:提示词全文嵌 template.template.value(type="prompt")。

    custom_fields 注册动态变量 message,使 ChatInput 的输出可接到该输入口。
    """
    fields = [
        _field(
            "template", "Template", "prompt", ir.system_prompt,
            _input_type="PromptInput", tool_mode=False, trace_as_input=True,
        ),
        # 动态字段:模板变量 {message}(形状对齐官方 starter 的动态字段)
        _field(
            "message", "message", "str", "",
            input_types=["Message", "Text"], multiline=True, field_type="str",
            fileTypes=[], file_path="",
        ),
        _field(
            "tool_placeholder", "Tool Placeholder", "str", "",
            advanced=True, info="A placeholder input for tool mode.",
            input_types=["Message"], _input_type="MessageTextInput",
            tool_mode=True, trace_as_input=True, trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "Prompt", "Prompt", "Create a prompt template with dynamic variables.", position,
        fields,
        ["Message"],
        ["template", "tool_placeholder"],
        [_output("prompt", "Prompt", "build_prompt", ["Message"])],
        icon="prompts",
        custom_fields={"template": ["message"]},
        selected_output="prompt",
    )


def _llm_node(ir: AgentIR, position: Dict[str, float]) -> Dict[str, Any]:
    model = str(ir.metadata.get("model") or "gpt-4.1")
    fields = [
        _field(
            "provider", "Model Provider", "str", "OpenAI",
            info="Select the model provider",
            options=["OpenAI", "Anthropic", "Google"],
            _input_type="DropdownInput", combobox=False, real_time_refresh=True,
            trace_as_metadata=True,
        ),
        _field(
            "model_name", "Model Name", "str", model,
            info="Select the model to use",
            options=list(_DEFAULT_MODEL_OPTIONS),
            _input_type="DropdownInput", combobox=False,
            trace_as_metadata=True,
        ),
        _field(
            "api_key", "OpenAI API Key", "str", "OPENAI_API_KEY",
            info="Model Provider API key", load_from_db=True, password=True,
            real_time_refresh=True, _input_type="SecretStrInput",
        ),
        _field(
            "input_value", "Input", "str", "",
            info="The input text to send to the model", input_types=["Message"],
            _input_type="MessageInput", trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "system_message", "System Message", "str", "",
            info="A system message that helps set the behavior of the assistant",
            input_types=["Message"], multiline=True, _input_type="MultilineInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "stream", "Stream", "bool", False,
            advanced=True, info="Whether to stream the response",
            _input_type="BoolInput", trace_as_metadata=True,
        ),
        _field(
            "temperature", "Temperature", "slider", 0.1,
            advanced=True, info="Controls randomness in responses",
            _input_type="SliderInput",
            range_spec={"min": 0, "max": 1, "step": 0.01, "step_type": "float"},
        ),
    ]
    return _make_node(
        "LanguageModelComponent", "Language Model",
        "Generates text using a Language Model.", position,
        fields,
        ["LanguageModel", "Message"],
        ["provider", "model_name", "api_key", "input_value",
         "system_message", "stream", "temperature"],
        [
            _output("text_output", "Model Response", "text_response", ["Message"]),
            _output("model_output", "Language Model", "build_model", ["LanguageModel"]),
        ],
        icon="LangChain",
        selected_output="text_output",
    )


def _chat_output_node(position: Dict[str, float]) -> Dict[str, Any]:
    fields = [
        _field(
            "input_value", "Inputs", "str", "",
            info="Message to be passed as output.", required=True,
            input_types=["Data", "DataFrame", "Message"],
            _input_type="MessageInput", trace_as_input=True,
        ),
        _field(
            "should_store_message", "Store Messages", "bool", True,
            advanced=True, info="Store the message in the history.",
            _input_type="BoolInput", trace_as_metadata=True,
        ),
        _field(
            "sender", "Sender Type", "str", "Machine",
            advanced=True, info="Type of sender.",
            options=["Machine", "User"], _input_type="DropdownInput",
            combobox=False, trace_as_metadata=True,
        ),
        _field(
            "sender_name", "Sender Name", "str", "AI",
            advanced=True, info="Name of the sender.", input_types=["Message"],
            _input_type="MessageTextInput", trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "session_id", "Session ID", "str", "",
            advanced=True,
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            input_types=["Message"], _input_type="MessageTextInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "data_template", "Data Template", "str", "{text}",
            advanced=True,
            info="Template to convert Data to Text. If left empty, it will be dynamically set to the Data's text key.",
            input_types=["Message"], _input_type="MessageTextInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "ChatOutput", "Chat Output", "Display chat messages from the Playground.", position,
        fields,
        ["Message"],
        ["input_value", "should_store_message", "sender", "sender_name",
         "session_id", "data_template"],
        [_output("message", "Output Message", "message_response", ["Message"])],
        icon="ChatOutput",
    )


# ---------- flow.json 组装 ----------

def _flow(ir: AgentIR) -> dict:
    nodes, edges = _graph(ir)
    return {
        "id": str(uuid.uuid4()),
        "name": ir.title(),
        "description": ir.description or f"Flow generated from skill '{ir.name}'.",
        "endpoint_name": None,
        "is_component": False,
        "tags": ["agents"],
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


def _graph(ir: AgentIR) -> Tuple[List[dict], List[dict]]:
    """四节点链 + 三条边;handle 内 id 与节点 id 一致。"""
    nodes = [
        _chat_input_node({"x": 0, "y": 300}),
        _prompt_node(ir, {"x": 384, "y": 300}),
        _llm_node(ir, {"x": 768, "y": 300}),
        _chat_output_node({"x": 1152, "y": 300}),
    ]
    ids = {n["data"]["type"]: n["id"] for n in nodes}
    chat_in, prompt, llm, chat_out = (
        ids["ChatInput"], ids["Prompt"], ids["LanguageModelComponent"], ids["ChatOutput"]
    )
    edges = [
        _edge(
            chat_in,
            _src_handle("ChatInput", chat_in, "message", ["Message"]),
            prompt,
            _tgt_handle("message", prompt, ["Message", "Text"], "str"),
        ),
        _edge(
            prompt,
            _src_handle("Prompt", prompt, "prompt", ["Message"]),
            llm,
            _tgt_handle("system_message", llm, ["Message"], "str"),
        ),
        _edge(
            llm,
            _src_handle("LanguageModelComponent", llm, "text_output", ["Message"]),
            chat_out,
            _tgt_handle("input_value", chat_out, ["Data", "DataFrame", "Message"], "str"),
        ),
    ]
    return nodes, edges


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


# ---------- README ----------

def _readme(ir: AgentIR) -> str:
    docs = [d for d in ir.knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 agent 未附带知识文档)"
    kb_name = (ir.name or "skill").replace("-", "_")
    return f"""# {ir.title()} —— Langflow Flow(由 agentskills-bridge 生成)

## 文件

- flow.json —— Langflow 导出格式(可导入的完整 flow)
- knowledge/ —— 参考知识文档(flow.json 不包含其内容):
{listing}

## 导入方式(UI)

- 打开 Langflow -> 左上角「+ 新建 Flow」-> 「Import JSON」(或直接把 flow.json 拖入画布),即可载入本 flow。
- 导入后在 Language Model 组件里确认 `api_key` 已选中全局变量 `OPENAI_API_KEY`(Settings -> Environment Variables 中配置),点右上角 Playground 即可对话。

## Flow 结构

ChatInput --message--> Prompt(system_prompt 内嵌源 agent 的完整系统提示词)
  --prompt(system_message)--> LanguageModelComponent(gpt-4.1 / provider=OpenAI)
  --text_output--> ChatOutput

注意:Prompt 输出接到 LanguageModelComponent 时,targetHandle 字段是 `system_message`
(接 Agent 组件才是 `system_prompt`);handle 字符串使用 Langflow 的 `œ` 引号约定。

## 知识文件挂载(Knowledge Bases 两步上传)

knowledge/ 不会随 flow.json 导入。Langflow 1.12 起 Knowledge Base 与 flow 解耦,
正确姿势是先经 REST API 上传,再在 flow 里引用:

1. 建知识库(名字最短 3 字符,空格会转下划线):

    curl -X POST http://localhost:7860/api/v1/knowledge_bases \\
      -H "Content-Type: application/json" \\
      -d {{"name": "{kb_name}"}}

2. multipart 上传知识文件(可多个;chunk_size 默认 1000,chunk_overlap 默认 200):

    curl -X POST http://localhost:7860/api/v1/knowledge_bases/{kb_name}/ingest \\
      -F "files=@knowledge/guide.md" \\
      -F "files=@knowledge/other.md"

上传完成后,在 flow 画布里添加 `Knowledge` 组件(选刚建的 KB、mode=Retrieve),
把其输出接到 Prompt 或 Agent 的输入口,模型回答即可引用知识内容。
若只是临时问答,也可退一步用 ChatInput 的 `files` 字段直接挂 txt/md/pdf 等文件。
"""
