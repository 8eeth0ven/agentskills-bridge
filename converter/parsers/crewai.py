"""CrewAI 项目 → AgentIR 解析器。

config_dir 指向含 agents.yaml(+可选 tasks.yaml)的目录;兼容直接传
crewai 项目根(自动探测 config/agents.yaml、src/config/agents.yaml)。

YAML 解析优先 pyyaml(pyyaml.YAMLError 时也回退),缺失时用内置最小
解析 _minimal_yaml_load:支持「顶层 key + 一层子字段」映射、> 与 |
块标量、引号值、注释行、空行。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from converter.ir import AgentIR, TaskStep, slugify
    from converter.parsers.knowledge import collect_knowledge
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR, TaskStep, slugify  # type: ignore
    from .knowledge import collect_knowledge  # type: ignore

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - 环境无 pyyaml
    yaml = None  # type: ignore


# ---------- 内置最小 YAML 解析(仅在 pyyaml 不可用/失败时使用) ----------


def _unquote(value: str) -> str:
    """去掉成对引号并做最基本的引号转义还原。

    引号值允许后面跟行内注释(`"x"  # note`):在闭合引号处截断;
    双引号支持 \\" 转义,单引号支持 '' 转义。
    """
    value = value.strip()
    quote = value[:1]
    if quote in ("'", '"') and len(value) >= 2:
        if quote == '"':
            end = 1
            while True:
                end = value.find('"', end)
                if end <= 0:
                    break
                if value[end - 1] == "\\":
                    end += 1
                    continue
                break
        else:
            end = -1
            i = 1
            while i < len(value):
                j = value.find("'", i)
                if j == -1:
                    break
                if j + 1 < len(value) and value[j + 1] == "'":  # '' 转义
                    i = j + 2
                    continue
                end = j
                break
        if end > 0:
            inner = value[1:end]
            if quote == '"':
                inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
            else:
                inner = inner.replace("''", "'")
            return inner
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _minimal_yaml_load(text: str) -> Dict[str, Any]:
    """最小平面 YAML 解析:顶层 key 为 agent/task 名,一层子字段为字符串。

    容忍:> 与 | 块标量(按缩进归属)、单/双引号值、注释行、空行。
    """
    root: Dict[str, Any] = {}
    container: Dict[str, Any] = root
    block: Optional[Dict[str, Any]] = None

    def _flush_block() -> None:
        nonlocal block
        if block is None:
            return
        lines = list(block["lines"])
        while lines and lines[-1] == "":  # clip:去尾部空行
            lines.pop()
        if block["literal"]:
            value = "\n".join(lines)
        else:  # folded:行内空格连接,空行分段
            parts: List[str] = []
            para: List[str] = []
            for ln in lines:
                if ln == "":
                    if para:
                        parts.append(" ".join(para))
                        para = []
                else:
                    para.append(ln)
            if para:
                parts.append(" ".join(para))
            value = "\n".join(parts)
        block["container"][block["key"]] = value
        block = None

    for raw in text.splitlines():
        if block is not None:
            if not raw.strip():
                block["lines"].append("")
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent > block["indent"]:
                block["lines"].append(raw.strip())
                continue
            _flush_block()  # 缩进回落 → 块标量结束
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        m = re.match(r'^("([^"]*)"|\'([^\']*)\'|[^:#]+?)\s*:\s*(.*)$', stripped)
        if not m:
            continue  # 列表项等不支持的结构直接忽略
        if m.group(2) is not None:
            key = m.group(2)
        elif m.group(3) is not None:
            key = m.group(3)
        else:
            key = m.group(1).strip()
        value = m.group(4).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = {
                "container": container,
                "key": key,
                "indent": indent,
                "literal": value.startswith("|"),
                "lines": [],
            }
            continue
        if value == "":
            if indent == 0:
                child = root.get(key)
                if not isinstance(child, dict):
                    child = {}
                    root[key] = child
                container = child
            else:
                container[key] = {}
            continue
        target = root if indent == 0 else container
        target[key] = _unquote(value)
    _flush_block()
    return root


def _load_yaml_text(text: str) -> Any:
    """优先 yaml.safe_load;无 pyyaml 或解析失败时回退内置最小解析。"""
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception:  # noqa: BLE001 - 容错:坏 yaml 也走内置解析
            pass
    return _minimal_yaml_load(text)


# ---------- 主解析 ----------


def _candidates(config_dir: Path) -> List[Path]:
    """agents.yaml 的候选路径:本目录 → config/ → src/config/ → src/*/config/。

    真实 crewAI 项目模板(crewAIInc/crewAI-examples)布局是
    ``src/<package_name>/config/agents.yaml`` 且包名与项目目录名不同
    (如 game-builder-crew → src/game_builder_crew/config/),故最后一段
    用 glob 兜底(排序取第一个,保持确定性)。
    """
    found = [
        config_dir / "agents.yaml",
        config_dir / "config" / "agents.yaml",
        config_dir / "src" / "config" / "agents.yaml",
    ]
    found.extend(sorted((config_dir / "src").glob("*/config/agents.yaml")))
    return found


def parse_crewai(config_dir: Union[str, Path]) -> AgentIR:
    """解析 crewai 配置目录为 AgentIR(取第一个 agent;tasks.yaml 可选)。

    agents.yaml 缺失(三种候选位置均无)抛 FileNotFoundError。
    """
    root = Path(config_dir)
    agents_file = next((p for p in _candidates(root) if p.is_file()), None)
    if agents_file is None:
        raise FileNotFoundError(f"missing agents.yaml: {root}")

    agents_data = _load_yaml_text(agents_file.read_text(encoding="utf-8"))
    if not isinstance(agents_data, dict) or not agents_data:
        raise ValueError(f"no agents parsed from {agents_file}")
    agent_key = next(iter(agents_data))
    agent = agents_data[agent_key]
    if not isinstance(agent, dict):
        agent = {}
    role = str(agent.get("role") or "").strip()
    goal = str(agent.get("goal") or "").strip()
    backstory = str(agent.get("backstory") or "").strip()

    name = slugify(str(agent_key))
    title = " ".join(p.capitalize() for p in name.split("-") if p) or str(agent_key)

    # system_prompt 组装:backstory 本身是 markdown 正文(以 # 开头,即
    # agentskills-bridge emitter 的产物形态)时直接作为正文 —— 三段包装头
    # 会与正文自身的标题层重复,roundtrip 字符保真被破坏(评测 crewai 链
    # F_prompt 的主要残余损失)。原生 crewai 项目(backstory 为人格化
    # 纯文本)仍走 `# {title}` + Role/Goal/Backstory 三段组装。
    if backstory.lstrip().startswith("#"):
        system_prompt = backstory.strip()
    else:
        parts: List[str] = [f"# {role or title}"]
        if role:
            parts.append(f"## Role\n{role}")
        if goal:
            parts.append(f"## Goal\n{goal}")
        if backstory:
            parts.append(f"## Backstory\n{backstory}")
        system_prompt = "\n\n".join(parts)

    # tasks.yaml(可选,与 agents.yaml 同目录)
    tasks: List[TaskStep] = []
    tasks_file = agents_file.parent / "tasks.yaml"
    if tasks_file.is_file():
        tasks_data = _load_yaml_text(tasks_file.read_text(encoding="utf-8"))
        if isinstance(tasks_data, dict):
            for key, body in tasks_data.items():
                body = body if isinstance(body, dict) else {}
                tasks.append(
                    TaskStep(
                        name=str(key),
                        description=str(body.get("description") or ""),
                        expected_output=str(body.get("expected_output") or ""),
                        agent=str(body.get("agent") or ""),
                    )
                )

    return AgentIR(
        name=name,
        display_name=title,
        description=goal or role or "",
        system_prompt=system_prompt,
        tasks=tasks,
        knowledge=collect_knowledge(root, agents_file.parent),
        metadata={
            "source_format": "crewai",
            "source_path": str(agents_file.resolve()),
            # 多 agent 文件(真实项目 3-4 个 agent/文件):IR 单槽只取第一个,
            # 全部 agent 名记入 metadata,不静默丢弃
            "agents_all": [str(k) for k in agents_data.keys()],
            "agents_count": len(agents_data),
            # agents:全部角色的定义(name/role/goal),供 workflow 节点携带
            # "谁以什么角色做这步"的语义(语义审计 P1:此前只有名单,
            # 角色定义在 agent→workflow 时丢失)。backstory 太长不入,正文
            # 在各 agent 原文件里。
            "agents": [
                {
                    "name": str(k),
                    "role": str((v if isinstance(v, dict) else {}).get("role") or ""),
                    "goal": str((v if isinstance(v, dict) else {}).get("goal") or ""),
                }
                for k, v in agents_data.items()
                if isinstance(v, dict)
            ],
        },
    )
