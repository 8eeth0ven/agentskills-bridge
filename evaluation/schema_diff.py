"""schema 深度一致性校验:三格式产物 vs 官方真实 schema 逐字段比对。

    python3 evaluation/schema_diff.py [--official-flow <fixture.json>] [--offline] [--json <path>]

比对对象:
    langflow        我们的 flow.json vs 官方 starter flow 真实 JSON
                    (basic_prompting.json:显式 --official-flow 输入、官方 URL、内置结构摘录回退)
    openai          我们的 agents/openai.yaml vs Codex 官方三段结构
                    (interface/policy/dependencies,codex-rs 源码证据)
    claude-subagent 我们的 .claude/agents/*.md vs Claude Code subagent 硬约束
                    (code.claude.com/docs/en/sub-agents)

键分级(langflow,依据 langflow main@1.12.5 源码):
    REQUIRED   导入/运行时直接读取:node{id,position,type,data} + data{type,id,node}
               + data.node{base_classes,field_order,outputs,template(_type)}
               (graph/graph/base.py:_create_vertex 逐键下标访问;
                vertex/base.py:251 template._type=="Component" 时 outputs 必需)
    UI-META    官方导出双写到 data 层、画布节点标题用:{display_name,description}
               (官方 fixture 中 ChatInput/Prompt 携带;非运行时必需,但对齐官方导出)
    DECOR      编辑器状态/测量值,导入后自动重建:measured/width/height/dragging/
               selected/beta/edited/pinned/lf_version/... (不补,保持产物精简)

退出码:0 = REQUIRED 级差异清零;1 = 仍有必需级缺失(或产物无法生成)。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT))

EXAMPLE_SKILL = ROOT / "examples" / "agent-fullcycle-engineering"

OFFICIAL_FLOW_URL = (
    "https://raw.githubusercontent.com/langflow-ai/langflow/main/src/lfx/tests/"
    "fixtures/starter_flows/v1.9.0/basic_prompting.json"
)


# ---------------------------------------------------------------- 分级表

# node 顶层(reactflow)
NODE_TOP_REQUIRED = {"data", "id", "position", "type"}
NODE_TOP_DECOR = {
    "measured", "width", "height", "dragging", "selected",
    "positionAbsolute", "style", "resizing",
}

# data 层
DATA_REQUIRED = {"type", "id", "node"}
DATA_UI_META = {"display_name", "description"}          # 官方双写,画布标题
DATA_DECOR = {"selected_output", "showNode"}            # 编辑器状态

# data.node 层
NODE_META_REQUIRED = {"base_classes", "field_order", "outputs", "template"}
NODE_META_FUNCTIONAL = {"custom_fields"}                # 动态输入口注册(Prompt 用)
NODE_META_DECOR = {
    "beta", "conditional_paths", "documentation", "edited", "frozen", "icon",
    "legacy", "lf_version", "metadata", "output_types", "pinned", "tool_mode",
    "last_updated", "minimized", "priority",
}

# template 字段 dict
TEMPLATE_REQUIRED = {"_type"}
FIELD_DICT_REQUIRED = {"name", "type", "value"}
FIELD_DICT_CORE = {
    "name", "display_name", "type", "value", "show", "advanced",
    "dynamic", "info", "input_types", "list", "placeholder",
    "required", "title_case",
}

# 边
EDGE_REQUIRED = {"source", "target", "sourceHandle", "targetHandle"}

# 顶层
FLOW_TOP_REQUIRED = {"data", "id", "name"}
FLOW_TOP_DECOR = {"last_tested_version", "tags", "endpoint_name", "is_component", "description"}

NODE_TYPES = ["ChatInput", "Prompt", "LanguageModelComponent", "ChatOutput"]

# openai.yaml 官方约束(codex-rs/skills/src/interface.rs:
#   MAX_NAME_LEN=64, MAX_DESCRIPTION_LEN=1024)
OPENAI_INTERFACE_LIMITS = {"display_name": 64, "short_description": 1024, "default_prompt": 1024}

# claude-subagent(model 值域:sonnet/opus/haiku/fable/inherit/完整 claude-* id)
CLAUDE_MODEL_VALUES = {"sonnet", "opus", "haiku", "fable", "inherit"}


# ---------------------------------------------------------------- 官方样本

def load_official_flow(official_flow: Optional[Path] = None, offline: bool = False) -> Tuple[Optional[dict], str]:
    """Use only an explicitly supplied fixture, the official URL, or the embedded excerpt."""
    if official_flow is not None:
        return json.loads(official_flow.read_text(encoding="utf-8")), f"explicit fixture: {official_flow.name}"
    if not offline:
        try:
            with urllib.request.urlopen(OFFICIAL_FLOW_URL, timeout=20) as response:
                return json.loads(response.read()), f"official URL: {OFFICIAL_FLOW_URL}"
        except (OSError, ValueError):
            pass
    return _official_flow_from_research(), "内置官方结构摘录(离线或官方样本下载不可用)"


def _official_flow_from_research() -> dict:
    """调研报告摘录的键结构(顶层 + ChatInput 精简样例的字段 dict 键)。"""
    chat_input_field_keys = [
        "advanced", "display_name", "dynamic", "info", "input_types", "list",
        "load_from_db", "multiline", "name", "required", "show",
        "title_case", "trace_as_input", "trace_as_metadata", "type", "value",
    ]
    return {
        "id": "0dbee653-41ae-4e51-af2e-55757fb24be3",
        "name": "Basic Prompting",
        "description": "Perform basic prompting with an OpenAI model.",
        "endpoint_name": None,
        "is_component": False,
        "last_tested_version": "1.5.0",
        "tags": ["chatbots"],
        "data": {
            "nodes": [
                {
                    "data": {
                        "description": "Get chat inputs from the Playground.",
                        "display_name": "Chat Input",
                        "id": "ChatInput-SzjnT",
                        "node": {
                            "base_classes": ["Message"],
                            "field_order": [
                                "input_value", "store_message", "sender",
                                "sender_name", "session_id", "files",
                            ],
                            "outputs": [{
                                "method": "message_response", "name": "message",
                                "selected": "Message", "types": ["Message"],
                            }],
                            "template": {
                                "_type": "Component",
                                "code": {"name": "code", "type": "code", "value": "..."},
                                "input_value": dict.fromkeys(chat_input_field_keys, ""),
                            },
                        },
                        "selected_output": "message",
                        "type": "ChatInput",
                    },
                    "dragging": False,
                    "id": "ChatInput-SzjnT",
                    "measured": {"height": 234, "width": 320},
                    "position": {"x": 689.57, "y": 765.15},
                    "selected": False,
                    "type": "genericNode",
                    "width": 320,
                },
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


# ---------------------------------------------------------------- 产物生成

def _generate_targets(out_root: Path) -> Dict[str, Optional[Path]]:
    """cli skill2agent 生成三格式产物;失败回退为直接调 emitter。"""
    out: Dict[str, Optional[Path]] = {}
    for target, key in (("langflow", "langflow"), ("openai", "openai"),
                        ("claude-subagent", "claude")):
        dest = out_root / key
        try:
            r = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), "skill2agent",
                 str(EXAMPLE_SKILL), "--target", target, "--out", str(dest)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and (dest / "flow.json").is_file() or \
               (target != "langflow" and r.returncode == 0 and dest.is_dir()):
                out[key] = dest
                continue
        except (OSError, subprocess.SubprocessError):
            pass
        # 回退:直接调 emitter
        try:
            from converter.emitters import EMITTERS
            from converter.skill_loader import load_skill
            EMITTERS[target](load_skill(EXAMPLE_SKILL), dest)
            out[key] = dest
        except Exception:  # noqa: BLE001 - 生成失败即报
            out[key] = None
    return out


# ---------------------------------------------------------------- langflow 比对

def diff_langflow(ours: dict, official: dict) -> List[dict]:
    """逐节点类型比对键集合差异,按 REQUIRED/UI/DECOR/EXTRA 分级。"""
    items: List[dict] = []

    def add(scope: str, key: str, level: str, status: str, note: str = "") -> None:
        items.append({"scope": scope, "key": key, "level": level,
                      "status": status, "note": note})

    # ---- 顶层
    o_top, h_top = set(official), set(ours)
    for k in sorted(FLOW_TOP_REQUIRED - h_top):
        add("flow 顶层", k, "REQUIRED", "MISSING", "后端 FlowBase/导入必需")
    for k in sorted(h_top - o_top):
        add("flow 顶层", k, "UNKNOWN-EXTRA", "EXTRA", "官方样例无此键(无害,前端忽略)")
    for k in sorted((o_top - h_top) - FLOW_TOP_REQUIRED):
        add("flow 顶层", k, "DECOR", "MISSING-OK", "装饰性,不补")

    off_nodes = {n.get("data", {}).get("type"): n for n in official["data"]["nodes"]
                 if isinstance(n, dict) and n.get("type") == "genericNode"}
    our_nodes = {n.get("data", {}).get("type"): n for n in ours["data"]["nodes"]
                 if isinstance(n, dict)}

    for ntype in NODE_TYPES:
        onode, hnode = off_nodes.get(ntype), our_nodes.get(ntype)
        if hnode is None:
            add(f"节点 {ntype}", "<node>", "REQUIRED", "MISSING", "节点本身缺失")
            continue
        scope = f"节点 {ntype}"

        # ---- node 顶层
        o, h = set(onode or {}), set(hnode)
        for k in sorted(NODE_TOP_REQUIRED - h):
            add(f"{scope} 顶层", k, "REQUIRED", "MISSING", "reactflow/后端 _create_vertex 必需")
        for k in sorted((o - h) & NODE_TOP_DECOR):
            add(f"{scope} 顶层", k, "DECOR", "MISSING-OK", "测量值/编辑器状态,导入自动重建")
        for k in sorted(h - o - NODE_TOP_REQUIRED):
            add(f"{scope} 顶层", k, "UNKNOWN-EXTRA", "EXTRA", "官方样例无此键(无害)")

        # ---- data 层
        odata = set((onode or {}).get("data", {}))
        hdata = set(hnode.get("data", {}))
        for k in sorted(DATA_REQUIRED - hdata):
            add(f"{scope} data", k, "REQUIRED", "MISSING", "vertex_data['type']/['id']/['node'] 必需")
        for k in sorted((odata - hdata) & DATA_UI_META):
            add(f"{scope} data", k, "UI-META", "MISSING", "官方导出双写,画布节点标题显示")
        for k in sorted((odata - hdata) & DATA_DECOR):
            add(f"{scope} data", k, "DECOR", "MISSING-OK", "编辑器状态")
        for k in sorted(hdata - odata - DATA_REQUIRED):
            add(f"{scope} data", k, "UNKNOWN-EXTRA", "EXTRA", "官方样例无此键(无害)")

        # ---- data.node 层
        ometa = (onode or {}).get("data", {}).get("node", {})
        hmeta = hnode.get("data", {}).get("node", {})
        o, h = set(ometa), set(hmeta)
        for k in sorted(NODE_META_REQUIRED - h):
            add(f"{scope} data.node", k, "REQUIRED", "MISSING",
                "Vertex: template._type==Component 时 outputs 必需 / base_classes 用于类型判定")
        for k in sorted((o - h) & NODE_META_FUNCTIONAL):
            add(f"{scope} data.node", k, "FUNCTIONAL", "MISSING", "动态输入口注册")
        for k in sorted((o - h) & NODE_META_DECOR):
            add(f"{scope} data.node", k, "DECOR", "MISSING-OK", "编辑器状态/元数据残留")
        for k in sorted(h - o - NODE_META_REQUIRED):
            add(f"{scope} data.node", k, "UNKNOWN-EXTRA", "EXTRA", "官方样例无此键(无害)")

        # ---- template._type + 字段 dict 必需/核心键
        htmpl = hmeta.get("template", {})
        if TEMPLATE_REQUIRED - set(htmpl):
            add(f"{scope} template", "_type", "REQUIRED", "MISSING",
                "vertex_base_type = data.node.template._type(下标访问)")
        for fname, fd in sorted(htmpl.items()):
            if not isinstance(fd, dict):
                continue
            miss_req = FIELD_DICT_REQUIRED - set(fd)
            if miss_req:
                add(f"{scope} 字段 {fname}", ",".join(sorted(miss_req)),
                    "REQUIRED", "MISSING", "字段 dict 缺 name/type/value")
            miss_core = FIELD_DICT_CORE - set(fd)
            if miss_core:
                add(f"{scope} 字段 {fname}", ",".join(sorted(miss_core)),
                    "UI-META", "MISSING", "官方通用字段元数据键(调研 §1 精简样例)")
        # 输出 dict 必需键
        for i, out_d in enumerate(hmeta.get("outputs", [])):
            miss = {"name", "method", "types", "selected"} - set(out_d)
            if miss:
                add(f"{scope} outputs[{i}]", ",".join(sorted(miss)),
                    "REQUIRED", "MISSING", "输出 handle 定义缺键")

    # ---- 边
    for i, e in enumerate(ours["data"].get("edges", [])):
        miss = EDGE_REQUIRED - set(e)
        if miss:
            add(f"edge[{i}]", ",".join(sorted(miss)), "REQUIRED", "MISSING",
                "reactflow 边必需键")
    return items


# ---------------------------------------------------------------- openai 比对

def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """解析本项目产物形状的简单 YAML:顶层段 + 一层双引号标量(标准库)。"""
    result: Dict[str, Any] = {}
    section: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):
            key = raw.rstrip(":").strip()
            if raw.rstrip().endswith(":"):
                section = key
                result.setdefault(section, {})
            else:
                name, _, val = raw.partition(":")
                result[name.strip()] = _yaml_scalar(val.strip())
                section = None
        elif section:
            name, _, val = raw.strip().partition(":")
            result[section][name.strip()] = _yaml_scalar(val.strip())
    return result


def _yaml_scalar(v: str) -> Any:
    if v.startswith('"') and v.endswith('"'):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v.strip('"')
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    return v


def diff_openai(out_dir: Path) -> Tuple[List[dict], List[dict]]:
    """openai.yaml vs 官方三段结构:键存在性、值类型、长度约束、x-source-skill 判定。"""
    items: List[dict] = []
    notes: List[dict] = []

    def add(scope, key, level, status, note=""):
        items.append({"scope": scope, "key": key, "level": level,
                      "status": status, "note": note})

    yaml_path = out_dir / "agents" / "openai.yaml"
    if not yaml_path.is_file():
        add("openai.yaml", "<file>", "REQUIRED", "MISSING", "agents/openai.yaml 不存在")
        return items, notes
    parsed = _parse_simple_yaml(yaml_path.read_text(encoding="utf-8"))

    iface = parsed.get("interface")
    if not isinstance(iface, dict):
        add("interface", "<section>", "REQUIRED", "MISSING",
            "官方三段之首(codex-rs SkillInterfaceFile)")
        iface = {}
    for field in ("display_name", "short_description", "default_prompt"):
        if field not in iface:
            add("interface", field, "REQUIRED", "MISSING", "调研确认的三字段之一")
        elif not isinstance(iface[field], str):
            add("interface", field, "REQUIRED", "TYPE-MISMATCH",
                f"应为 str,实为 {type(iface[field]).__name__}")
        else:
            limit = OPENAI_INTERFACE_LIMITS[field]
            if len(iface[field]) > limit:
                add("interface", field, "REQUIRED", "OVER-LENGTH",
                    f"{len(iface[field])} > {limit},Codex resolve_str 超长即忽略该字段")
    for field in ("icon_small", "icon_large", "brand_color"):
        if field in iface:
            add("interface", field, "OPTIONAL", "PRESENT", "官方可选字段")

    # 可选段
    if "policy" not in parsed:
        notes.append({"topic": "policy 段",
                      "finding": "缺失——官方可选段(Option + serde default),源 IR 无对应信息,不产出合法",
                      "confidence": "高(codex-rs/ext/skills/src/loader/metadata.rs:28-35)"})
    if "dependencies" not in parsed:
        notes.append({"topic": "dependencies 段",
                      "finding": "缺失——官方可选段,源 skill 无 MCP/工具依赖声明,不产出合法",
                      "confidence": "高(同上源码)"})

    # x-source-skill
    if "x-source-skill" in parsed:
        notes.append({
            "topic": "x-source-skill 顶层键",
            "finding": "Codex SkillMetadataFile(serde Deserialize,无 deny_unknown_fields)"
                       "对未知顶层键宽容忽略,不会拒载 openai.yaml;metadata 解析本身 fail-open"
                       "(解析失败仅 warn,不阻塞 SKILL.md 加载)。其余客户端不读取 agents/openai.yaml。",
            "confidence": "高(源码直读 codex-rs/ext/skills/src/loader/metadata.rs)",
        })
    return items, notes


# ---------------------------------------------------------------- claude 比对

def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """解析 frontmatter(双引号标量 + YAML 列表),返回 (标量映射, 列表映射)。"""
    scalars: Dict[str, Any] = {}
    lists: Dict[str, List[str]] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return scalars, lists
    cur_list: Optional[str] = None
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        stripped = raw.strip()
        if stripped.startswith("- "):
            if cur_list:
                lists[cur_list].append(str(_yaml_scalar(stripped[2:])))
            continue
        name, colon, val = stripped.partition(":")
        if not colon:
            continue
        name, val = name.strip(), val.strip()
        if val == "":
            cur_list = name
            lists[name] = []
        else:
            cur_list = None
            scalars[name] = _yaml_scalar(val)
    return scalars, lists


def diff_claude(out_dir: Path) -> Tuple[List[dict], List[dict]]:
    """frontmatter 硬约束逐条核。"""
    items: List[dict] = []
    notes: List[dict] = []

    def add(scope, key, level, status, note=""):
        items.append({"scope": scope, "key": key, "level": level,
                      "status": status, "note": note})

    agents_dir = out_dir / ".claude" / "agents"
    mds = sorted(agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    if not mds:
        add("subagent", "<file>", "REQUIRED", "MISSING", "缺 .claude/agents/*.md")
        return items, notes

    for md in mds:
        scope = md.name
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            add(scope, "首行 ---", "REQUIRED", "MISSING",
                "frontmatter 分隔符必须是文件第一行,否则整文件被当正文(skip)")
        scalars, lists = _parse_frontmatter(text)

        name = scalars.get("name")
        if not isinstance(name, str) or not name.strip():
            add(scope, "name", "REQUIRED", "MISSING", "无 name → 当普通文档跳过")
        else:
            if len(name) > 256:
                add(scope, "name", "REQUIRED", "OVER-LENGTH", f"{len(name)} > 256 字符 → skip")
            if ":" in name:
                add(scope, "name", "REQUIRED", "INVALID", "含 ':'(保留给 plugin 作用域)→ skip")
            if name.startswith("-"):
                add(scope, "name", "REQUIRED", "INVALID", "以 '-' 开头 → skip")
            if re.search(r"\s", name):
                add(scope, "name", "REQUIRED", "INVALID",
                    "含空白字符——官方示例均为 slug 形(code-reviewer),identifier 语义不含空格")

        desc = scalars.get("description")
        if not isinstance(desc, str) or not desc.strip():
            add(scope, "description", "REQUIRED", "MISSING", "有 name 无 description → skip")

        if "tools" not in scalars and "tools" not in lists:
            add(scope, "tools", "REQUIRED", "MISSING", "tools 键缺失(缺省继承全部工具,非 skip 项)")
        elif lists.get("tools"):
            if any(not t.strip() for t in lists["tools"]):
                add(scope, "tools", "REQUIRED", "INVALID", "YAML 列表含空项")
        elif "tools" in scalars and not isinstance(scalars["tools"], str):
            add(scope, "tools", "REQUIRED", "TYPE-MISMATCH", "逗号分隔串或 YAML 列表均可,当前非 str")

        model = scalars.get("model")
        if not isinstance(model, str) or not model.strip():
            add(scope, "model", "REQUIRED", "MISSING", "model 键缺失")
        elif model not in CLAUDE_MODEL_VALUES and not model.startswith("claude-"):
            add(scope, "model", "REQUIRED", "OUT-OF-DOMAIN",
                f"值 {model!r} ∉ sonnet/opus/haiku/fable/inherit/claude-* 完整 id")

        if "knowledge" in lists or "knowledge" in scalars:
            notes.append({
                "topic": f"{scope} 的 knowledge: 扩展键",
                "finding": "非 Claude Code 官方 subagent 字段。官方文档未定义该键;"
                           "按'未知字段被忽略不报错'的通用解析行为推断无害,"
                           "但未在真实 Claude Code 中实测验证。",
                "confidence": "低(未验证)——Claude Code 未知键容忍性未验证",
            })
    return items, notes


# ---------------------------------------------------------------- 主流程

def run(json_out: Optional[Path] = None, *, official_flow: Optional[Path] = None, offline: bool = False) -> int:
    with tempfile.TemporaryDirectory(prefix="bridge-schema-") as tmp:
        return _run(Path(tmp), json_out, official_flow=official_flow, offline=offline)


def _run(out_root: Path, json_out: Optional[Path], *, official_flow: Optional[Path], offline: bool) -> int:
    official, official_src = load_official_flow(official_flow, offline)
    print(f"官方 langflow 样本来源:{official_src}")
    targets = _generate_targets(out_root)

    all_items: Dict[str, List[dict]] = {}
    all_notes: List[dict] = []

    # langflow
    if targets.get("langflow") and official:
        flow = json.loads((targets["langflow"] / "flow.json").read_text(encoding="utf-8"))
        all_items["langflow"] = diff_langflow(flow, official)
    else:
        all_items["langflow"] = [{"scope": "langflow", "key": "<artifact>",
                                  "level": "REQUIRED", "status": "MISSING",
                                  "note": "产物或官方样本不可用"}]
    # openai
    if targets.get("openai"):
        it, nt = diff_openai(targets["openai"])
        all_items["openai"] = it
        all_notes += nt
    else:
        all_items["openai"] = [{"scope": "openai", "key": "<artifact>",
                                "level": "REQUIRED", "status": "MISSING",
                                "note": "产物不可用"}]
    # claude
    if targets.get("claude"):
        it, nt = diff_claude(targets["claude"])
        all_items["claude-subagent"] = it
        all_notes += nt
    else:
        all_items["claude-subagent"] = [{"scope": "claude", "key": "<artifact>",
                                         "level": "REQUIRED", "status": "MISSING",
                                         "note": "产物不可用"}]

    # ---- 报告
    required_open = 0
    for fmt, items in all_items.items():
        print(f"\n===== {fmt} =====")
        if not items:
            print("  (无差异)")
        for it in items:
            flag = ""
            if it["level"] == "REQUIRED" and it["status"] not in ("PRESENT",):
                flag = "  <-- 必需级未清零"
                required_open += 1
            print(f"  [{it['level']:>13}] {it['status']:<14} {it['scope']}: "
                  f"{it['key']}{flag}")
            if it.get("note"):
                print(f"                └─ {it['note']}")
    if all_notes:
        print("\n===== 附注(非差异项的合规性结论)=====")
        for n in all_notes:
            print(f"  * {n['topic']}\n      {n['finding']}\n      置信度:{n['confidence']}")

    print(f"\n必需级差异合计:{required_open}")
    if json_out:
        payload = {"official_flow_source": official_src, "diffs": all_items,
                   "notes": all_notes, "required_open": required_open}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"JSON 结果:{json_out}")
    return 1 if required_open else 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="三产物 vs 官方 schema 一致性校验")
    ap.add_argument("--json", help="结构化结果落盘路径(可选)")
    ap.add_argument("--official-flow", type=Path, help="Explicit official Langflow fixture; no local clone discovery")
    ap.add_argument("--offline", action="store_true", help="Use the embedded excerpt without network access")
    args = ap.parse_args(argv)
    return run(Path(args.json) if args.json else None, official_flow=args.official_flow, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
