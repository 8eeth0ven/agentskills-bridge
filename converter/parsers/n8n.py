"""n8n workflow.json -> AgentIR 解析器(best-effort,向后兼容)。

提取目标(与 emitters/n8n.py 互为逆操作):
    workflow name           -> display_name(slugify -> name)
    AI Agent 节点           -> 步骤:parameters.options.systemMessage(去掉 n8n
                               表达式前缀 "=" 后取全文);无 agent 节点时回退
                               任意含 text/prompt/systemMessage 参数的节点(取长文)
    connections(main 键)   -> 执行顺序:从触发器(chatTrigger/manualTrigger/
                               *webhook)起 BFS,无触发器则入度 0 起;无
                               connections 时按 nodes 数组顺序
    system_prompt           -> 单节点直取;多节点合并为 "## Step N: {name}" 分节
    knowledge/              -> collect_knowledge(同目录)
    模型子节点(lmChat*)   -> metadata["model"](resourceLocator 的 value)

容错:n8n.io 模板 API 的 {"workflow": {...}} 包装;目录形态自动定位
workflow.json(缺失时找目录下唯一含 nodes 的 *.json)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from converter.ir import AgentIR, TaskStep, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, TaskStep, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore

AGENT_NODE_TYPE = "@n8n/n8n-nodes-langchain.agent"


# ---------- 载入 ----------

def _load_workflow(path: Path) -> Dict[str, Any]:
    """定位并解析 workflow.json;目录形态自动定位;非法 JSON 抛 ValueError。"""
    if path.is_dir():
        cand = path / "workflow.json"
        if not cand.is_file():
            # 容错:目录下任一含 nodes 数组的 *.json
            for j in sorted(path.glob("*.json")):
                try:
                    data = json.loads(j.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(data, dict) and isinstance(data.get("nodes"), list):
                    cand = j
                    break
            else:
                raise FileNotFoundError(f"missing workflow.json under: {path}")
        path = cand
    if not path.is_file():
        raise FileNotFoundError(f"missing n8n workflow file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid n8n workflow json: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid n8n workflow structure: {path}")
    # n8n.io 模板 API 形态 {"workflow": {...}} 容错
    inner = data.get("workflow")
    if not isinstance(data.get("nodes"), list) and isinstance(inner, dict) \
            and isinstance(inner.get("nodes"), list):
        data = inner
    if not isinstance(data.get("nodes"), list):
        raise ValueError(f"no nodes array in n8n workflow: {path}")
    return data


# ---------- 节点识别 ----------

def _node_type(node: Dict[str, Any]) -> str:
    return str(node.get("type") or "")


def _is_agent_node(node: Dict[str, Any]) -> bool:
    """@n8n/n8n-nodes-langchain.agent(以及其它 *.agent 形态的 langchain agent)。"""
    t = _node_type(node)
    return t.endswith(".agent") and "langchain" in t


def _is_trigger_node(node: Dict[str, Any]) -> bool:
    t = _node_type(node).lower()
    return "trigger" in t or t.endswith("webhook")


def _strip_expr_prefix(text: str) -> str:
    """去掉 n8n 表达式值的前导 '='(systemMessage 常以 '=' 开头)。"""
    return text[1:] if text.startswith("=") else text


def _system_message(node: Dict[str, Any]) -> str:
    """agent 节点的 options.systemMessage(优先且允许为空,由调用方决定取舍)。"""
    params = node.get("parameters")
    if not isinstance(params, dict):
        return ""
    opts = params.get("options")
    msg = opts.get("systemMessage") if isinstance(opts, dict) else None
    if isinstance(msg, dict):  # 罕见 resourceLocator 形态
        msg = msg.get("value")
    return _strip_expr_prefix(msg) if isinstance(msg, str) else ""


def _fallback_prompt(node: Dict[str, Any]) -> str:
    """无 agent 节点时的兜底:任意节点 parameters 里 text/prompt/systemMessage
    等参数中的长文本(>=20 字符),取最长。"""
    params = node.get("parameters")
    if not isinstance(params, dict):
        return ""
    candidates: List[str] = []
    msg = _system_message(node)
    if msg.strip():
        candidates.append(msg)
    for key in ("prompt", "text", "systemMessage", "userMessage", "jsCode"):
        value = params.get(key)
        texts: List[str] = []
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict) and isinstance(value.get("value"), str):
            texts.append(value["value"])
        for t in texts:
            if len(t.strip()) >= 20:
                candidates.append(_strip_expr_prefix(t))
    return max(candidates, key=len) if candidates else ""


# ---------- 执行顺序 ----------

def _execution_order(nodes: List[Dict[str, Any]], connections: Any) -> List[str]:
    """触发器/入度 0 起 BFS 重建 main 链执行顺序;无 connections 按 nodes 顺序。"""
    names: List[str] = []
    for n in nodes:
        nm = str(n.get("name") or "")
        if nm and nm not in names:
            names.append(nm)
    is_trigger = {
        str(n.get("name") or ""): _is_trigger_node(n) for n in nodes if n.get("name")
    }
    adj: Dict[str, List[str]] = {nm: [] for nm in names}
    indeg: Dict[str, int] = {nm: 0 for nm in names}
    seen_edges = set()
    if isinstance(connections, dict):
        for src, cmap in connections.items():
            src = str(src)
            if src not in adj or not isinstance(cmap, dict):
                continue
            for ctype, groups in cmap.items():
                if ctype != "main" or not isinstance(groups, list):
                    continue
                for group in groups:
                    if not isinstance(group, list):
                        continue
                    for conn in group:
                        if not isinstance(conn, dict):
                            continue
                        tgt = str(conn.get("node") or "")
                        if tgt in adj and tgt != src and (src, tgt) not in seen_edges:
                            seen_edges.add((src, tgt))
                            adj[src].append(tgt)
                            indeg[tgt] += 1
    queue = [nm for nm in names if is_trigger.get(nm)]
    queue += [nm for nm in names if not is_trigger.get(nm) and indeg[nm] == 0
              and nm not in queue]
    order: List[str] = []
    visited = set()
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] <= 0 and nxt not in visited:
                queue.append(nxt)
    order += [nm for nm in names if nm not in visited]  # 断链/孤立节点按原顺序兜底
    return order


# ---------- 元数据 ----------

def _extract_model(nodes: List[Dict[str, Any]]) -> Optional[str]:
    """lmChat* 模型子节点的 parameters.model(resourceLocator value 或裸字符串)。"""
    for node in nodes:
        if "lmChat" not in _node_type(node):
            continue
        params = node.get("parameters")
        if not isinstance(params, dict):
            continue
        model = params.get("model")
        if isinstance(model, dict):
            value = model.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        elif isinstance(model, str) and model.strip():
            return model.strip()
    return None


# ---------- 主入口 ----------

def parse_n8n(path: Union[str, Path]) -> AgentIR:
    """解析 n8n workflow.json(目录或文件)为 AgentIR。

    文件不存在抛 FileNotFoundError;JSON 非法/无 nodes 抛 ValueError。
    """
    p = Path(path)
    data = _load_workflow(p)
    if p.is_dir():
        source_path = (p / "workflow.json").resolve()
    else:
        source_path = p.resolve()

    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    connections = data.get("connections")

    order = _execution_order(nodes, connections)
    node_by_name = {str(n.get("name") or ""): n for n in nodes}

    agent_names = [nm for nm in order
                   if nm in node_by_name and _is_agent_node(node_by_name[nm])]
    if not agent_names:  # 回退:任意含 text/prompt 参数的节点
        agent_names = [nm for nm in order
                       if nm in node_by_name
                       and not _is_trigger_node(node_by_name[nm])
                       and _fallback_prompt(node_by_name[nm])]

    steps: List[Tuple[str, str]] = []
    for nm in agent_names:
        node = node_by_name[nm]
        msg = _system_message(node) if _is_agent_node(node) else ""
        if not msg:
            msg = _fallback_prompt(node)
        steps.append((nm, msg))

    if not steps:
        system_prompt = ""
    elif len(steps) == 1:
        system_prompt = steps[0][1]
    else:
        system_prompt = "\n\n".join(
            f"## Step {i}: {nm}\n\n{msg}".rstrip() for i, (nm, msg) in enumerate(steps, 1)
        )

    # x-source-skill 优先回源:本工具产出的 workflow 携带原 description 与
    # system_prompt 全文(节点链只是骨架,原文非步骤章节在此保全)。
    xskill = data.get("x-source-skill") if isinstance(data.get("x-source-skill"), dict) else {}
    if xskill.get("systemPrompt"):
        system_prompt = str(xskill["systemPrompt"]).strip()

    wf_name = str(xskill.get("name") or data.get("name") or data.get("display_name") or source_path.stem)
    name = slugify(wf_name)
    display_name = wf_name or " ".join(p.capitalize() for p in name.split("-") if p)

    metadata: Dict[str, Any] = {
        "source_format": "n8n",
        "source_path": str(source_path),
    }
    model = _extract_model(nodes)
    if model:
        metadata["model"] = model
    if agent_names:
        metadata["chain"] = list(agent_names)

    description = str(xskill.get("description") or data.get("description") or "").strip()
    if not description:
        description = (
            f"n8n workflow '{wf_name}' with {len(steps)} agent step(s)."
            if steps else f"n8n workflow '{wf_name}' (no agent nodes found)."
        )

    return AgentIR(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=system_prompt,
        knowledge=collect_knowledge(source_path.parent),
        tasks=[TaskStep(name=nm, description=msg, agent=nm) for nm, msg in steps],
        metadata=metadata,
    )
