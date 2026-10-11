"""评测指标与 V_format 静态校验器(纯函数,零第三方依赖,Python 3.13)。

指标公式(本模块的 docstring 契约,实现不得偏离):

    F_name   = 1.0 if slugify(ir_in.name) == slugify(ir_out.name) else 0.0

    F_desc   = norm_desc 相等 → 1.0
               否则 1 - levenshtein(a, b) / max(len(a), len(b)),下限 0
               norm_desc(s) = s 中换行归一为 \\n 后再把 \\n 替换成空格,再 strip()

    F_prompt = norm_prompt 相等 → 1.0
               否则 1 - levenshtein(a, b) / max(len(a), len(b)),下限 0
               norm_prompt(s) = \\r\\n → \\n、\\r → \\n,再 strip()

    F_know_q = len(ir_out.knowledge) / len(ir_in.knowledge)
               (ir_in.knowledge 为 0 时定义为 1.0)

    F_know_c = 内容 sha256 一致(按 filename 配对)的 knowledge 数 / len(ir_in.knowledge)
               (ir_in.knowledge 为 0 时定义为 1.0)

    V_format = forward 产物静态校验(VALIDATORS 注册表,每 target 一个函数),
               全部检查通过 = 1,任一失败 = 0 并附原因列表。

    L        = Loss points:值为 0 / 异常 / 降级的字段及原因字符串列表,
               每条 {"field", "kind", "reason"}(kind 为稳定桶名,供频次统计)。

levenshtein 为纯 Python 实现(禁第三方):短串走双行 DP,长串(如 13KB
system_prompt)走 Myers 位并行算法,两者结果完全一致(见 levenshtein())。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# 项目内导入(converter 属本项目,不算第三方依赖)
try:
    from converter.ir import AgentIR, parse_frontmatter, slugify
except ImportError:  # pragma: no cover - 直接以脚本运行本文件时的兜底
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from converter.ir import AgentIR, parse_frontmatter, slugify

try:  # pyyaml 可用时用于 crewai V_format 校验;缺失走容忍式启发检查
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - 环境无 pyyaml
    yaml = None  # type: ignore

__all__ = [
    "levenshtein",
    "f_name",
    "f_desc",
    "f_prompt",
    "f_know_q",
    "f_know_c",
    "roundtrip_metrics",
    "VALIDATORS",
    "validate_forward",
    "validate_skill_dir",
]

# agentskills.io 开放规范对 SKILL.md frontmatter 的硬约束
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024


# --------------------------------------------------------------------------
# levenshtein(纯 Python,禁第三方)
# --------------------------------------------------------------------------

_DP_CELL_LIMIT = 250_000  # 短串走朴素 DP 的乘积上限,超过走 Myers 位并行


def _levenshtein_dp(a: str, b: str) -> int:
    """经典双行 DP 编辑距离(插入/删除/替换各代价 1)。"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _levenshtein_myers(a: str, b: str) -> int:
    """Myers 1999 位并行编辑距离,与朴素 DP 结果一致。

    复杂度 O(len(a) * len(b) / 机器位宽):利用 Python 大整数的任意宽度
    位运算,把内层 DP 的一整列压进一个整数,长文本(≥ 数 KB)也能秒级出值。
    """
    if not a or not b:
        return len(a) + len(b)
    if len(b) > len(a):
        a, b = b, a  # 位掩码建在较短串上
    m = len(b)
    peq: Dict[str, int] = {}
    for i, ch in enumerate(b):
        peq[ch] = peq.get(ch, 0) | (1 << i)
    full = (1 << m) - 1
    top = 1 << (m - 1)
    pv = full
    mv = 0
    score = m
    for ch in a:
        eq = peq.get(ch, 0)
        xv = eq | mv
        xh = (((eq & pv) + pv) ^ pv) | eq
        ph = mv | (full & ~(xh | pv))
        mh = pv & xh
        if ph & top:
            score += 1
        if mh & top:
            score -= 1
        ph = ((ph << 1) | 1) & full
        mh = (mh << 1) & full
        pv = mh | (full & ~(xv | ph))
        mv = ph & xv
    return score


def levenshtein(a: str, b: str) -> int:
    """返回两字符串的 levenshtein 编辑距离(纯 Python,无第三方依赖)。

    短串(乘积 ≤ _DP_CELL_LIMIT)走双行 DP,长串走 Myers 位并行;
    两条路径对同一输入给出完全相同的距离值。
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) * len(b) <= _DP_CELL_LIMIT:
        return _levenshtein_dp(a, b)
    return _levenshtein_myers(a, b)


# --------------------------------------------------------------------------
# 归一化与 5 个 F 指标
# --------------------------------------------------------------------------

def norm_desc(text: str) -> str:
    """description 归一化:换行统一后 \\n → 空格,再 strip()。"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\n", " ").strip()


def norm_prompt(text: str) -> str:
    """system_prompt 归一化:\\r\\n / \\r → \\n,再 strip()。"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def _similarity(a_norm: str, b_norm: str) -> float:
    """1 - levenshtein(a,b)/max(len),下限 0(两者已归一化且不相等)。"""
    longest = max(len(a_norm), len(b_norm))
    if longest == 0:  # 两个都是空串时不会走到这里(相等已短路)
        return 1.0
    dist = levenshtein(a_norm, b_norm)
    return max(0.0, 1.0 - dist / longest)


def f_name(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """F_name:slugify 归一后 name 完全一致 → 1.0,否则 0.0。"""
    return 1.0 if slugify(ir_in.name) == slugify(ir_out.name) else 0.0


def f_desc(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """F_desc:归一化(strip+换行→空格)后相等 = 1.0;否则 1 - lev/max(len) ≥ 0。"""
    a, b = norm_desc(ir_in.description), norm_desc(ir_out.description)
    if a == b:
        return 1.0
    return _similarity(a, b)


def f_prompt(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """F_prompt:归一化(strip+\\r\\n→\\n)后相等 = 1.0;否则 1 - lev/max(len)。"""
    a, b = norm_prompt(ir_in.system_prompt), norm_prompt(ir_out.system_prompt)
    if a == b:
        return 1.0
    return _similarity(a, b)


def f_know_q(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """F_know_q = len(ir_out.knowledge)/len(ir_in.knowledge);入侧为 0 时定义 1.0。"""
    n_in = len(ir_in.knowledge)
    if n_in == 0:
        return 1.0
    return len(ir_out.knowledge) / n_in


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def f_know_c(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """F_know_c:内容 sha256 一致(按 filename 配对)的文档数 / 入侧文档数;入侧 0 → 1.0。"""
    n_in = len(ir_in.knowledge)
    if n_in == 0:
        return 1.0
    out_by_name: Dict[str, List[str]] = {}
    for doc in ir_out.knowledge:
        out_by_name.setdefault(doc.filename, []).append(_sha256(doc.content))
    hit = 0
    for doc in ir_in.knowledge:
        want = _sha256(doc.content)
        if want in out_by_name.get(doc.filename, []):
            hit += 1
    return hit / n_in


# --------------------------------------------------------------------------
# Loss points(L)
# --------------------------------------------------------------------------

def loss_points(ir_in: AgentIR, ir_out: AgentIR, metrics: Dict[str, float]) -> List[dict]:
    """收集值为 0 / 异常 / 降级字段的 Loss points(字段 + 稳定桶名 + 原因字符串)。"""
    losses: List[dict] = []

    def add(field: str, kind: str, reason: str) -> None:
        losses.append({"field": field, "kind": kind, "reason": reason})

    if metrics.get("F_name") == 0.0:
        add("name", "name-mismatch",
            f"slugify 后不一致: in={ir_in.name!r} out={ir_out.name!r}")
    if metrics.get("F_desc", 1.0) < 1.0:
        a, b = norm_desc(ir_in.description), norm_desc(ir_out.description)
        d = levenshtein(a, b)
        add("description", "desc-degraded",
            f"F_desc={metrics['F_desc']:.4f}(lev={d}, max_len={max(len(a), len(b))})")
    if metrics.get("F_prompt", 1.0) < 1.0:
        a, b = norm_prompt(ir_in.system_prompt), norm_prompt(ir_out.system_prompt)
        d = levenshtein(a, b)
        add("system_prompt", "prompt-degraded",
            f"F_prompt={metrics['F_prompt']:.4f}(lev={d}, max_len={max(len(a), len(b))})")
    if ir_in.knowledge and metrics.get("F_know_q", 1.0) < 1.0:
        add("knowledge", "knowledge-qty-lost",
            f"知识文档数量回流失真: in={len(ir_in.knowledge)} out={len(ir_out.knowledge)}")
    if ir_in.knowledge and metrics.get("F_know_c", 1.0) < 1.0:
        missing = [d.filename for d in ir_in.knowledge
                   if _sha256(d.content) not in
                   [_sha256(o.content) for o in ir_out.knowledge if o.filename == d.filename]]
        add("knowledge", "knowledge-content-mismatch",
            f"内容 sha256 不一致的文档: {', '.join(missing[:5]) or '(部分)'}")
    return losses


def roundtrip_metrics(ir_in: AgentIR, ir_out: AgentIR) -> Tuple[Dict[str, float], List[dict]]:
    """一次 roundtrip 的全部 F 指标 + Loss points。"""
    metrics = {
        "F_name": f_name(ir_in, ir_out),
        "F_desc": f_desc(ir_in, ir_out),
        "F_prompt": f_prompt(ir_in, ir_out),
        "F_know_q": f_know_q(ir_in, ir_out),
        "F_know_c": f_know_c(ir_in, ir_out),
    }
    return metrics, loss_points(ir_in, ir_out, metrics)


# --------------------------------------------------------------------------
# V_format 静态校验器(每 target 一个函数,返回 (1|0, 原因列表))
# --------------------------------------------------------------------------

def _first_key_line(text: str) -> Optional[str]:
    """容忍式 YAML 检查:首个非空非注释行的顶层 key(无 pyyaml 时的降级路径)。"""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[:1] in (" ", "\t"):
            return stripped
    return None


def _tolerant_yaml_ok(text: str, need_keys: Tuple[str, ...]) -> Tuple[bool, List[str]]:
    """yaml 解析(优先 pyyaml;缺失时容忍式启发),返回 (ok, 原因)。"""
    reasons: List[str] = []
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001 - pyyaml 任意解析错误都算失败
            return False, [f"yaml.safe_load 失败: {exc}"]
        if not isinstance(data, dict) or not data:
            return False, ["yaml 解析结果不是非空 mapping"]
        return True, reasons
    # 无 pyyaml:首行有顶层 key + 必需键前缀存在
    first = _first_key_line(text)
    if first is None or ":" not in first:
        reasons.append("无 pyyaml 且首行不是顶层 key")
    for key in need_keys:
        if f"\n{key}:" not in f"\n{text}" and not text.startswith(f"{key}:"):
            reasons.append(f"缺少键 {key}:")
    return (not reasons), reasons


def v_crewai(root: Path) -> Tuple[int, List[str]]:
    """crewai:config/agents.yaml 与 tasks.yaml 存在且可被容忍 yaml 解析。

    无 pyyaml 时要求首行有 agent key、含 role:/goal:/backstory:。
    (agents.yaml 含 skills: 键仅对 crewai-skills 要求,此处不查。)
    """
    reasons: List[str] = []
    agents_yaml = root / "config" / "agents.yaml"
    tasks_yaml = root / "config" / "tasks.yaml"
    if not agents_yaml.is_file():
        return 0, [f"缺 {agents_yaml.relative_to(root) if agents_yaml.exists() else 'config/agents.yaml'}"]
    if not tasks_yaml.is_file():
        return 0, ["缺 config/tasks.yaml"]
    ok, why = _tolerant_yaml_ok(agents_yaml.read_text(encoding="utf-8"),
                                ("role", "goal", "backstory"))
    if not ok:
        reasons.extend(f"agents.yaml: {w}" for w in why)
    ok, why = _tolerant_yaml_ok(tasks_yaml.read_text(encoding="utf-8"), ())
    if not ok:
        reasons.extend(f"tasks.yaml: {w}" for w in why)
    return (0 if reasons else 1), reasons


def _check_skill_md(skill_md: Path, expect_dir_name: Optional[str]) -> List[str]:
    """SKILL.md frontmatter 校验:name 合法 kebab ≤64(可与目录名比对)、description 非空 ≤1024。"""
    reasons: List[str] = []
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"读取失败: {exc}"]
    meta, _body = parse_frontmatter(text)
    name = (meta.get("name") or "").strip()
    if not KEBAB_RE.match(name):
        reasons.append(f"frontmatter name 非法(^[a-z0-9]+(-[a-z0-9]+)*$): {name!r}")
    elif len(name) > MAX_NAME_LEN:
        reasons.append(f"frontmatter name 超 64 字符: {len(name)}")
    if expect_dir_name is not None and name != expect_dir_name:
        reasons.append(f"frontmatter name {name!r} 与目录名 {expect_dir_name!r} 不一致")
    desc = (meta.get("description") or "").strip()
    if not desc:
        reasons.append("frontmatter description 为空")
    elif len(desc) > MAX_DESC_LEN:
        reasons.append(f"frontmatter description 超 1024 字符: {len(desc)}")
    return reasons


def v_crewai_skills(root: Path) -> Tuple[int, List[str]]:
    """crewai-skills:skills/*/SKILL.md 合法且 name 与目录名一致;agents.yaml 含 skills:。"""
    reasons: List[str] = []
    skill_dirs = sorted(p for p in (root / "skills").glob("*/SKILL.md")) if (root / "skills").is_dir() else []
    if not skill_dirs:
        return 0, ["缺 skills/*/SKILL.md"]
    for skill_md in skill_dirs:
        reasons.extend(_check_skill_md(skill_md, skill_md.parent.name))
    agents_yaml = root / "config" / "agents.yaml"
    if not agents_yaml.is_file():
        reasons.append("缺 config/agents.yaml")
    else:
        ok, why = _tolerant_yaml_ok(agents_yaml.read_text(encoding="utf-8"), ())
        if not ok:
            reasons.extend(f"agents.yaml: {w}" for w in why)
        if "skills:" not in agents_yaml.read_text(encoding="utf-8"):
            reasons.append("agents.yaml 缺 skills: 挂载键")
    return (0 if reasons else 1), reasons


def _py_compiles(path: Path) -> Optional[str]:
    """ast.parse 编译检查(py_compile 同级强度,但不落缓存文件);失败返回原因。"""
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return f"语法错误: {exc}"
    except (OSError, ValueError) as exc:
        return f"读取/解码失败: {exc}"
    return None


def v_deepagents(root: Path) -> Tuple[int, List[str]]:
    """deepagents:agent.py 存在且 py_compile(ast.parse)通过、含 create_deep_agent;skills/*/SKILL.md 存在。"""
    reasons: List[str] = []
    agent_py = root / "agent.py"
    if not agent_py.is_file():
        return 0, ["缺 agent.py"]
    why = _py_compiles(agent_py)
    if why:
        reasons.append(f"agent.py {why}")
    text = agent_py.read_text(encoding="utf-8")
    if "create_deep_agent" not in text:
        reasons.append("agent.py 不含 create_deep_agent")
    skill_mds = sorted((root / "skills").glob("*/SKILL.md")) if (root / "skills").is_dir() else []
    if not skill_mds:
        reasons.append("缺 skills/*/SKILL.md")
    return (0 if reasons else 1), reasons


def v_langchain(root: Path) -> Tuple[int, List[str]]:
    """langchain:agent.py py_compile 通过,含 SYSTEM_PROMPT 与 create_agent。"""
    reasons: List[str] = []
    agent_py = root / "agent.py"
    if not agent_py.is_file():
        return 0, ["缺 agent.py"]
    why = _py_compiles(agent_py)
    if why:
        reasons.append(f"agent.py {why}")
    text = agent_py.read_text(encoding="utf-8")
    if "SYSTEM_PROMPT" not in text:
        reasons.append("agent.py 不含 SYSTEM_PROMPT")
    if "create_agent" not in text:
        reasons.append("agent.py 不含 create_agent")
    return (0 if reasons else 1), reasons


_LANGFLOW_ALLOWED = {"ChatInput", "Prompt", "LanguageModelComponent", "ChatOutput"}


def v_langflow(root: Path) -> Tuple[int, List[str]]:
    """langflow:flow.json 可 json.load;全部节点外层 type==genericNode;
    data.type ∈ {ChatInput,Prompt,LanguageModelComponent,ChatOutput};
    存在含 œ 的 handle 且 œ 替换回引号后可 json.loads。"""
    reasons: List[str] = []
    flow_file = root / "flow.json"
    if not flow_file.is_file():
        return 0, ["缺 flow.json"]
    try:
        flow = json.loads(flow_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 0, [f"flow.json 不可解析: {exc}"]
    nodes = [n for n in ((flow.get("data") or {}).get("nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return 0, ["flow 无节点"]
    for node in nodes:
        if node.get("type") != "genericNode":
            reasons.append(f"节点 {node.get('id')!r} 外层 type != genericNode: {node.get('type')!r}")
        inner = (node.get("data") or {}).get("type")
        if inner not in _LANGFLOW_ALLOWED:
            reasons.append(f"节点 {node.get('id')!r} data.type 非法: {inner!r}")
    edges = [e for e in ((flow.get("data") or {}).get("edges") or []) if isinstance(e, dict)]
    oe_ok = False
    for edge in edges:
        for key in ("sourceHandle", "targetHandle"):
            handle = edge.get(key)
            if isinstance(handle, str) and "œ" in handle:
                try:
                    json.loads(handle.replace("œ", '"'))
                except ValueError:
                    reasons.append(f"edge handle œ 还原后非合法 JSON: {handle[:60]!r}")
                else:
                    oe_ok = True
    if not oe_ok:
        reasons.append("不存在含 œ 且还原后可 json.loads 的 handle")
    return (0 if reasons else 1), reasons


def v_openai(root: Path) -> Tuple[int, List[str]]:
    """openai:agents/openai.yaml 存在含 display_name;instructions.md 非空。"""
    reasons: List[str] = []
    openai_yaml = root / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        return 0, ["缺 agents/openai.yaml"]
    if "display_name" not in openai_yaml.read_text(encoding="utf-8"):
        reasons.append("openai.yaml 不含 display_name")
    instructions = root / "instructions.md"
    if not instructions.is_file():
        reasons.append("缺 instructions.md")
    elif not instructions.read_text(encoding="utf-8").strip():
        reasons.append("instructions.md 为空")
    return (0 if reasons else 1), reasons


def v_claude_subagent(root: Path) -> Tuple[int, List[str]]:
    """claude-subagent:.claude/agents/*.md 存在,首行 ---,frontmatter 含
    name/description/tools/model 四键。"""
    reasons: List[str] = []
    agents_dir = root / ".claude" / "agents"
    agent_mds = sorted(agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    if not agent_mds:
        return 0, ["缺 .claude/agents/*.md"]
    for agent_md in agent_mds:
        text = agent_md.read_text(encoding="utf-8")
        first_line = text.split("\n", 1)[0]
        if first_line != "---":
            reasons.append(f"{agent_md.name} 首行不是 ---: {first_line!r}")
        meta, _body = parse_frontmatter(text)
        for key in ("name", "description", "tools", "model"):
            if not (meta.get(key) or "").strip():
                reasons.append(f"{agent_md.name} frontmatter 缺 {key} 键")
    return (0 if reasons else 1), reasons


def v_generic(root: Path) -> Tuple[int, List[str]]:
    """generic:agent.json 可 json.load 且 AgentIR.from_json 成功。"""
    agent_json = root / "agent.json"
    if not agent_json.is_file():
        return 0, ["缺 agent.json"]
    try:
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 0, [f"agent.json 不可解析: {exc}"]
    try:
        AgentIR.from_dict(data)
    except Exception as exc:  # noqa: BLE001 - from_json 任意失败都算不通过
        return 0, [f"AgentIR.from_json 失败: {exc}"]
    return 1, []


def v_autogen(root: Path) -> Tuple[int, List[str]]:
    """autogen:agent.py 编译通过且含 AssistantAgent 与 SYSTEM_MESSAGE。"""
    errors: List[str] = []
    agent_py = root / "agent.py"
    if not agent_py.is_file():
        return 0, [f"缺少 agent.py: {agent_py}"]
    text = agent_py.read_text(encoding="utf-8")
    import ast

    try:
        ast.parse(text)
    except SyntaxError as exc:
        errors.append(f"agent.py 语法错误: {exc}")
    for needle, why in (("AssistantAgent", "缺 AG2 AssistantAgent 入口"),
                        ("SYSTEM_MESSAGE", "缺 SYSTEM_MESSAGE 常量")):
        if needle not in text:
            errors.append(why)
    know = sorted((root / "knowledge").glob("*.md")) if (root / "knowledge").is_dir() else []
    if know and "KNOWLEDGE" not in text:
        errors.append("有 knowledge/ 但 agent.py 未声明 KNOWLEDGE 清单")
    return (0, errors) if errors else (1, [])


def v_n8n(root: Path) -> Tuple[int, List[str]]:
    """n8n:workflow.json 可 json.load、含非空 nodes 与 connections 键,
    且至少一个节点 type 含 "agent"。"""
    reasons: List[str] = []
    workflow_json = root / "workflow.json"
    if not workflow_json.is_file():
        return 0, ["缺 workflow.json"]
    try:
        data = json.loads(workflow_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 0, [f"workflow.json 不可解析: {exc}"]
    if not isinstance(data, dict):
        return 0, ["workflow.json 不是 JSON object"]
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return 0, ["workflow.json 无 nodes(或为空)"]
    if "connections" not in data:
        reasons.append("workflow.json 缺 connections 键")
    if not any(
        isinstance(n, dict) and "agent" in str(n.get("type") or "")
        for n in nodes
    ):
        reasons.append('无 type 含 "agent" 的节点')
    return (0 if reasons else 1), reasons


def v_mermaid_workflow(root: Path) -> Tuple[int, List[str]]:
    """mermaid-workflow:*.md 存在且某文件含 ```mermaid 代码块、
    块类型为 flowchart/graph、方向为 TD/LR。"""
    reasons: List[str] = []
    mds = sorted(root.glob("*.md"))
    if not mds:
        return 0, ["缺 *.md"]
    ok = False
    for md in mds:
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as exc:
            reasons.append(f"{md.name} 读取失败: {exc}")
            continue
        if "```mermaid" in text and (
            "flowchart" in text or "graph" in text
        ) and re.search(r"\b(TD|LR)\b", text):
            ok = True
    if not ok:
        reasons.append("*.md 无 ```mermaid flowchart/graph TD/LR 块")
    return (0 if reasons else 1), reasons


VALIDATORS: Dict[str, Any] = {
    "crewai": v_crewai,
    "crewai-skills": v_crewai_skills,
    "deepagents": v_deepagents,
    "langchain": v_langchain,
    "langflow": v_langflow,
    "openai": v_openai,
    "claude-subagent": v_claude_subagent,
    "generic": v_generic,
    "autogen": v_autogen,
    "n8n": v_n8n,
    "mermaid-workflow": v_mermaid_workflow,
}


def validate_forward(target: str, root: Union[str, Path]) -> Tuple[int, List[str]]:
    """forward 产物静态校验入口:通过 = 1,失败 = 0 并附原因列表。"""
    validator = VALIDATORS.get(target)
    if validator is None:
        return 0, [f"target {target!r} 无校验器"]
    return validator(Path(root))


def validate_skill_dir(skill_dir: Union[str, Path]) -> Tuple[int, List[str]]:
    """roundtrip 出的 skill 目录:SKILL.md frontmatter name 合法、description 非空 ≤1024。"""
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.is_file():
        return 0, ["缺 SKILL.md"]
    reasons = _check_skill_md(skill_md, None)
    return (0 if reasons else 1), reasons
