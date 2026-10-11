"""n8n workflow emitter:AgentIR --(WorkflowIR.from_agent_ir)--> n8n workflow 目录。

workflow 族第一个真实引擎格式(与 skill/agent 三形态互转),经 converter.wir
的 WorkflowIR 中转;wir 未落盘时本模块可 import,emit_n8n 调用时抛 ImportError。

格式要点(2026-10 实测:n8n-io/n8n master 源码 + 三份真实导出 workflow):
    - 顶层:name / nodes / connections / settings={"executionOrder": "v1"} /
      active=false / meta={"templateCredsSetupCompleted": true}(instanceId 为
      实例私有,生成文件省略;tags/pinData 为可选兼容字段,一并带上);
    - node:parameters / id(uuid4 str) / name / type / typeVersion /
      position=[x, y];chatTrigger 另带 webhookId(uuid4 str,激活时 n8n 认领);
    - AI Agent 节点:type="@n8n/n8n-nodes-langchain.agent",master
      Agent.node.ts 注册 versions 1..1.9 / 2..2.3 / 3..3.1(defaultVersion
      3.1),真实模板生态主流 1.7/1.8/2;本 emitter 取 1.7(新旧 n8n 导入都稳,
      参数形态与 3.x 一致)。提示词走 promptType="define" +
      options.systemMessage;用户消息走 text 参数 —— 首个 agent 用
      "={{ $json.chatInput }}"(接 Chat Trigger 输出),链式后续用
      "={{ $json.output }}"(AI Agent 输出 item 为 {"output": ...});
    - Chat Trigger:type="@n8n/n8n-nodes-langchain.chatTrigger",master
      ChatTrigger.node.ts versions [1, 1.1, ..., 1.5],真实模板常用 1.1,
      parameters={"options": {}};
    - connections:{"源节点名": {"main": [[{"node": "目标节点名",
      "type": "main", "index": 0}]]}}(模型/工具子节点走 ai_languageModel /
      ai_tool 键;本 emitter 不生成子节点,接线方式写进 README)。

产出:
    <out>/workflow.json   可直接「Import from File」的 n8n workflow
    <out>/knowledge/*.md  知识文档按 filename 拷贝(不随 workflow.json 导入)
    <out>/README.md       导入方式 + Chat Model 接线(GLM/OpenAI/Claude)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from converter.ir import AgentIR, KnowledgeDoc

try:
    from converter.wir import WorkflowIR
except ImportError:  # pragma: no cover - converter/wir.py 由并行线程提供
    WorkflowIR = None  # type: ignore[assignment]

AGENT_NODE_TYPE = "@n8n/n8n-nodes-langchain.agent"
AGENT_TYPE_VERSION = 1.7  # 真实模板生态最通用;master 已到 3.1,参数形态一致
CHAT_TRIGGER_TYPE = "@n8n/n8n-nodes-langchain.chatTrigger"
CHAT_TRIGGER_TYPE_VERSION = 1.1  # ChatTrigger versions [1..1.5],模板主流 1.1
TRIGGER_NAME = "Chat Trigger"
STEP_SPACING = 300


def emit_n8n(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 n8n workflow 目录(需 converter.wir 就绪),返回 out_dir。"""
    if WorkflowIR is None:
        raise ImportError(
            "converter.wir 未就绪:WorkflowIR 契约模块由并行线程提供,落盘后重试"
        )
    w = WorkflowIR.from_agent_ir(ir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    knowledge = list(getattr(w, "knowledge", None) or ir.knowledge)
    # WorkflowIR 无 tools 字段(契约未改),工具契约直接取源 ir.tools
    tools = list(getattr(w, "tools", None) or ir.tools)
    _write_knowledge(knowledge, out)
    (out / "workflow.json").write_text(
        json.dumps(_workflow(w, tools), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(_readme(w, knowledge), encoding="utf-8")
    return out


# ---------- 节点组装 ----------

def _trigger_node() -> Dict[str, Any]:
    """Chat Trigger:入口触发器(带 webhookId,对齐真实导出形态)。"""
    return {
        "parameters": {"options": {}},
        "id": str(uuid.uuid4()),
        "name": TRIGGER_NAME,
        "type": CHAT_TRIGGER_TYPE,
        "typeVersion": CHAT_TRIGGER_TYPE_VERSION,
        "position": [-STEP_SPACING, 300],
        "webhookId": str(uuid.uuid4()),
    }


def _agent_node(name: str, prompt: str, is_first: bool, index: int) -> Dict[str, Any]:
    """AI Agent 节点:promptType=define + options.systemMessage,text 按链位取值。"""
    return {
        "parameters": {
            "promptType": "define",
            "text": "={{ $json.chatInput }}" if is_first else "={{ $json.output }}",
            "options": {"systemMessage": prompt or ""},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": AGENT_NODE_TYPE,
        "typeVersion": AGENT_TYPE_VERSION,
        "position": [index * STEP_SPACING, 300],
    }


def _unique_names(candidates: List[str]) -> List[str]:
    """n8n 要求节点名唯一:空名补默认,重名加 " 2"/" 3" 后缀,并避开触发器名。"""
    used = {TRIGGER_NAME}
    result: List[str] = []
    counters: Dict[str, int] = {}
    for i, raw in enumerate(candidates):
        name = (raw or "").strip() or f"Agent {i + 1}"
        if name in used:
            counters[name] = counters.get(name, 1) + 1
            name = f"{name} {counters[name]}"
        used.add(name)
        result.append(name)
    return result


def _ordered_chain(w: "WorkflowIR") -> Tuple[List[str], List[Tuple[str, str]], Dict[str, str]]:
    """返回 (按执行序的节点名, main 边列表[(src, tgt)], prompt 按名字索引)。

    边端点按 id 或 name 匹配(契约未钉死);解析出的边不足以构成链时退化为
    节点顺序串联,保证每个 agent 都挂在执行链上。
    """
    raw_nodes = list(getattr(w, "nodes", None) or [])
    names = _unique_names([str(getattr(n, "name", "") or "") for n in raw_nodes])
    prompts = {
        names[i]: str(getattr(n, "prompt", "") or "")
        for i, n in enumerate(raw_nodes)
    }
    by_id = {
        str(getattr(n, "id", "") or ""): names[i]
        for i, n in enumerate(raw_nodes)
        if getattr(n, "id", None)
    }
    name_set = set(names)
    edges: List[Tuple[str, str]] = []
    seen = set()
    for e in getattr(w, "edges", None) or []:
        src = by_id.get(str(getattr(e, "source", "") or "")) or str(
            getattr(e, "source", "") or ""
        )
        tgt = by_id.get(str(getattr(e, "target", "") or "")) or str(
            getattr(e, "target", "") or ""
        )
        if src in name_set and tgt in name_set and src != tgt and (src, tgt) not in seen:
            seen.add((src, tgt))
            edges.append((src, tgt))
    # 不足链时按节点顺序补边
    if len(edges) < len(names) - 1:
        for a, b in zip(names, names[1:]):
            if (a, b) not in seen:
                seen.add((a, b))
                edges.append((a, b))
    # Kahn 拓扑序(触发器语义上在链头,这里只排 agent 间的执行顺序)
    targets = {t for _, t in edges}
    order = [n for n in names if n not in targets]
    remaining = [n for n in names if n in targets]
    adj: Dict[str, List[str]] = {n: [] for n in names}
    for src, tgt in edges:
        adj[src].append(tgt)
    while remaining:
        progressed = False
        for n in list(remaining):
            if all(dep not in remaining for dep in adj[n] if dep != n):
                order.append(n)
                remaining.remove(n)
                progressed = True
        if not progressed:  # 环:按原顺序兜底
            order.extend(remaining)
            break
    return order, edges, prompts


def _workflow(w: "WorkflowIR", tools: Optional[List[Any]] = None) -> Dict[str, Any]:
    """组装 n8n workflow 顶层结构(节点按 position 横排,connections 按名字映射)。"""
    order, edges, prompts = _ordered_chain(w)
    nodes: List[Dict[str, Any]] = [_trigger_node()]
    pos_index = {name: i for i, name in enumerate(order)}
    for name in order:
        nodes.append(
            _agent_node(
                name=name,
                prompt=prompts.get(name, ""),
                is_first=pos_index[name] == 0,
                index=pos_index[name],
            )
        )
    connections: Dict[str, Any] = {}

    def _connect(src: str, tgt: str) -> None:
        conns = connections.setdefault(src, {"main": [[]]})
        conns["main"][0].append({"node": tgt, "type": "main", "index": 0})

    # 分支拓扑优先:parser 保留的 graph_edges(含 A→B 且 A→C 的并行分支)
    # 与当前节点匹配的部分按原图重建——线性 edges 会把分支压成链,丢失
    # DAG 语义(语义审计 P2)。来自触发器的边(源不在 agent 名集内)由
    # TRIGGER 逻辑接管;agent 间边全匹配才启用,否则回退线性链。
    graph_edges = (getattr(w, "metadata", None) or {}).get("graph_edges")
    name_set = set(order)
    if isinstance(graph_edges, list):
        internal = [e for e in graph_edges
                    if isinstance(e, list) and len(e) == 2
                    and e[0] in name_set and e[1] in name_set]
    else:
        internal = []
    if internal:
        for src, tgt in internal:
            _connect(src, tgt)
        if order and not any(e[1] == order[0] for e in internal):
            _connect(TRIGGER_NAME, order[0])
    else:
        if order:
            _connect(TRIGGER_NAME, order[0])
        for src, tgt in edges:
            _connect(src, tgt)
    # x-source-skill:转换器私有扩展(n8n 导入宽容忽略未知顶层键),
    # 携带原 description 与 system_prompt 全文保证 roundtrip——节点链只
    # 是工作流骨架,原文的 Overview 等非步骤章节在这里保全(评测 F_prompt
    # 曾因此降至 0.71)。与 openai.yaml 的 x-source-skill 同一模式。
    # tools 键(同结构列表)携带工具契约 {name,description,input_schema,
    # side_effects},workflow 形态不丢工具 schema。
    xskill: Dict[str, Any] = {
        "name": w.name,
        "description": w.description,
        "systemPrompt": w.system_prompt,
    }
    if tools:
        xskill["tools"] = [t.to_dict() for t in tools]
    return {
        "name": str(getattr(w, "display_name", "") or getattr(w, "name", "") or "Workflow"),
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "meta": {"templateCredsSetupCompleted": True},
        "pinData": {},
        "tags": [],
        "x-source-skill": xskill,
    }


# ---------- 知识文档拷贝 ----------

def _safe_filename(filename: str) -> Optional[str]:
    """过滤非法路径名:为空、. / ..、含 / 或 \\ 或 .. 的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _write_knowledge(knowledge: List[KnowledgeDoc], out: Path) -> List[str]:
    written: List[str] = []
    for doc in knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        kdir = out / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(doc.content or "", encoding="utf-8")
        written.append(name)
    return written


# ---------- README ----------

def _readme(w: "WorkflowIR", knowledge: List[KnowledgeDoc]) -> str:
    docs = [d for d in knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 workflow 未附带知识文档)"
    _, edges, _ = _ordered_chain(w)
    chain = "Chat Trigger -> " + " -> ".join(
        f"{src} -> {tgt}" for src, tgt in edges
    ) if edges else "Chat Trigger -> (单 agent)"
    return f"""# {getattr(w, 'display_name', '') or getattr(w, 'name', '')} —— n8n Workflow(由 agentskills-bridge 生成)

## 文件

- workflow.json —— n8n 官方 workflow 格式(1 个 Chat Trigger + N 个 AI Agent 节点)
- knowledge/ —— 参考知识文档(不随 workflow.json 导入,挂载方式见下):
{listing}

## 导入方式(n8n 1.x)

1. n8n 里新建 workflow(Workflows -> Add first workflow,或列表页右上 +)。
2. 画布右上「...」菜单 -> **Import from File**,选择 workflow.json(部分版本支持把
   文件直接拖入画布)。
3. 给每个 AI Agent 节点挂上 Chat Model 子节点(见下),Save 后打开 Chat 面板即可执行。

## Chat Model 接线(GLM / OpenAI / Claude)

每个 AI Agent 节点的「Chat Model」输入口必须挂一个模型子节点才能运行:

- OpenAI:挂「OpenAI Chat Model」节点并选好 OpenAI credential;
- Claude:改挂「Anthropic Chat Model」节点并选 credential;
- GLM(bigmodel):挂「OpenAI Chat Model」节点,credential 的 Base URL 填
  `https://open.bigmodel.cn/api/paas/v4/`,模型名填 `glm-4.6`(免费档 `glm-4-flash`;
  `glm-5.3-flash` 走 GLM 的 Anthropic 兼容端点 `https://open.bigmodel.cn/api/anthropic`,
  详见 llm-wiki/03-frameworks/llm-provider-config.md)。

## 执行链

{chain}

首个 agent 的用户消息取 `{{{{ $json.chatInput }}}}`(Chat Trigger 输出),链式后续
agent 取上一个 agent 的输出 `{{{{ $json.output }}}}`(已写入各节点 text 参数)。

## knowledge 挂载

knowledge/ 不随导入进 n8n。把需要的文件内容贴进对应 agent 的
options.systemMessage,或用「Default Data Loader」+ Vector Store 按检索方式挂载。
"""
