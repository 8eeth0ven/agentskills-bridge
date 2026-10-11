"""Langflow flow.json → AgentIR 解析器(best-effort,向后兼容)。

提取目标:
    flow name            → display_name(slugify → name)
    system_prompt        → 优先级:
                           ① 官方 1.4+ 格式 data.node.template.template.value
                              (genericNode,data.type=="Prompt")
                           ② 旧版 data.template.system_prompt.value / 裸字符串
                              (本项目历史产物)
                           ③ Agent 组件 template.system_prompt.value(真实
                              无 Prompt 节点的 flow,≥20 字符)
                           ④ 回退:任意 template 里含 prompt 键(或 prompt 类型
                              字段)且 value 为长文本的节点(取最长)
                           ⑤ Note 组件文本兜底(noteNode template.note.value)
    LLM 节点             → metadata["model"](model_name;1.9+ model_name 为空
                              时回退 model 字段;兼容旧版 OpenAIModel 等)
    data.edges 顺序      → metadata["chain"](节点名/类型按边出现顺序去重)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from converter.ir import AgentIR, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore


def _node_label(node: Dict[str, Any]) -> str:
    """节点可读名:data.type(新版 PascalCase 类名)> data.node.name > name > type > id。"""
    data = node.get("data") or {}
    inner = data.get("node") or {}
    return str(
        data.get("type") or inner.get("name") or node.get("name")
        or node.get("type") or node.get("id") or ""
    )


def _is_prompt_node(node: Dict[str, Any]) -> bool:
    """新版 data.type=="Prompt" 或旧版顶层 type=="Prompt"。"""
    data = node.get("data") or {}
    return data.get("type") == "Prompt" or node.get("type") == "Prompt"


def _templates_of(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """节点的 template 候选:新版 data.node.template + 旧版 data.template(均保证 dict)。"""
    data = node.get("data") or {}
    found: List[Dict[str, Any]] = []
    inner = data.get("node")
    if isinstance(inner, dict) and isinstance(inner.get("template"), dict):
        found.append(inner["template"])  # 官方 1.4+ 格式
    if isinstance(data.get("template"), dict):
        found.append(data["template"])  # 旧版/简写格式
    return found


def _extract_system_prompt(nodes: List[Dict[str, Any]]) -> str:
    """按优先级提取 system_prompt(见模块 docstring)。

    优先级:① 官方 Prompt 组件 template.template.value;② 本项目旧版
    system_prompt 键;③ Agent 组件 template.system_prompt.value(真实
    无 Prompt 节点的 flow,如 langflow 官方 starter "Pokédex Agent");
    ④ 模糊回退:任意 template 含 prompt 键且 value 为长文本(取最长);
    ⑤ Note 组件文本兜底。
    """
    # ① 官方 1.4+ 格式:Prompt 节点的 data.node.template.template.value
    for node in nodes:
        if not _is_prompt_node(node):
            continue
        inner = (node.get("data") or {}).get("node") or {}
        value = (inner.get("template") or {}).get("template")
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            if value["value"].strip():
                return value["value"]
    # ② 旧版(本项目历史产物):data.template.system_prompt.value / 裸字符串 / data.system_prompt
    for node in nodes:
        if not _is_prompt_node(node):
            continue
        data = node.get("data") or {}
        sp = data.get("system_prompt")
        if isinstance(sp, str) and sp.strip():
            return sp
        value = (data.get("template") or {}).get("system_prompt")
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            if value["value"].strip():
                return value["value"]
        if isinstance(value, str) and value.strip():
            return value
    # ③ Agent 组件(langflow 官方 Agent 节点):template.system_prompt.value
    for node in nodes:
        data = node.get("data") or {}
        ntype = str(data.get("type") or node.get("type") or "")
        if ntype != "Agent":
            continue
        for tmpl in _templates_of(node):
            value = tmpl.get("system_prompt")
            text = value.get("value") if isinstance(value, dict) else value
            if isinstance(text, str) and len(text.strip()) >= 20:
                return text.strip()
    # ④ 模糊回退:任意 template 里含 prompt 键(或 prompt 类型字段)且 value 为长文本,取最长
    best: Tuple[int, str] = (0, "")
    for node in nodes:
        for tmpl in _templates_of(node):
            for key, item in tmpl.items():
                if not isinstance(item, dict):
                    continue
                if "prompt" not in key.lower() and item.get("type") != "prompt":
                    continue
                value = item.get("value")
                if isinstance(value, str) and len(value) > best[0] and len(value) > 50:
                    best = (len(value), value)
    if best[1]:
        return best[1]
    # ⑤ Note 组件文本兜底(noteNode:template.note.value / data.node.description)
    for node in nodes:
        ntype = str(node.get("type") or (node.get("data") or {}).get("type") or "")
        if "note" not in ntype.lower():
            continue
        for tmpl in _templates_of(node):
            value = tmpl.get("note")
            text = value.get("value") if isinstance(value, dict) else value
            if isinstance(text, str) and len(text.strip()) >= 20:
                return text.strip()
        desc = (node.get("data") or {}).get("node", {})
        if isinstance(desc, dict):
            text = desc.get("description")
            if isinstance(text, str) and len(text.strip()) >= 20:
                return text.strip()
    return ""


def _extract_model(nodes: List[Dict[str, Any]]) -> Optional[str]:
    """新版 LanguageModelComponent / 旧版 OpenAIModel 的 model_name,再放宽到任意节点。

    1.9+ 官方 flow 的 LLM 组件 model_name 是「覆盖名」常为空,真实模型在
    ``model`` 字段(ModelInput.value,如 "openai/gpt-4o-mini"),故每个键
    依次尝试 model_name → model,取第一个非空 value。
    """
    for want in ("LanguageModelComponent", "OpenAIModel", None):
        for node in nodes:
            data = node.get("data") or {}
            ntype = str(data.get("type") or node.get("type") or "")
            if want is not None and ntype != want:
                continue
            if want is None and ntype in ("LanguageModelComponent", "OpenAIModel"):
                continue  # 前两轮已查过
            for tmpl in _templates_of(node):
                for key in ("model_name", "model"):
                    value = tmpl.get(key)
                    text = value.get("value") if isinstance(value, dict) else value
                    if isinstance(text, str) and text.strip():
                        return text.strip()
    return None


def _extract_chain(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[str]:
    """按 edges 出现顺序推导节点链(source→target 端点去重追加)。"""
    id_to_label = {str(n.get("id")): _node_label(n) for n in nodes if n.get("id")}
    chain: List[str] = []
    for edge in edges:
        for endpoint in (edge.get("source"), edge.get("target")):
            label = id_to_label.get(str(endpoint)) or str(endpoint or "")
            if label and label not in chain:
                chain.append(label)
    return chain


def parse_langflow(flow_file: Union[str, Path]) -> AgentIR:
    """解析 langflow 导出的 flow.json 为 AgentIR。

    文件不存在抛 FileNotFoundError;JSON 非法抛 ValueError。
    """
    path = Path(flow_file)
    if path.is_dir():
        # 目录形态(如 agent2skill 传产物根):自动定位 flow.json
        cand = path / "flow.json"
        if not cand.is_file():
            raise FileNotFoundError(f"missing flow.json under: {path}")
        path = cand
    if not path.is_file():
        raise FileNotFoundError(f"missing langflow flow file: {path}")
    try:
        flow = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid langflow json: {path}") from exc
    if not isinstance(flow, dict):
        raise ValueError(f"invalid langflow json structure: {path}")

    data = flow.get("data") or {}
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]

    raw_name = str(flow.get("name") or flow.get("display_name") or path.stem)
    name = slugify(raw_name)
    title = " ".join(p.capitalize() for p in name.split("-") if p) or raw_name

    metadata: Dict[str, Any] = {
        "source_format": "langflow",
        "source_path": str(path.resolve()),
    }
    model = _extract_model(nodes)
    if model:
        metadata["model"] = model
    chain = _extract_chain(nodes, edges)
    if chain:
        metadata["chain"] = chain

    system_prompt = _extract_system_prompt(nodes)
    return AgentIR(
        name=name,
        display_name=str(flow.get("name") or title),
        description=str(flow.get("description") or ""),
        system_prompt=system_prompt,
        knowledge=collect_knowledge(path.parent),
        metadata=metadata,
    )
