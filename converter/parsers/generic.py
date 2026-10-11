"""generic agent.json → AgentIR 解析器。

path 指 agent.json 或其所在目录;目录形态时找 <dir>/agent.json。
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

try:
    from converter.ir import AgentIR
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import AgentIR  # type: ignore


def parse_generic(path: Union[str, Path]) -> AgentIR:
    """读 agent.json(path 为文件或目录)为 AgentIR,metadata 补 source_format。

    agent.json 不存在抛 FileNotFoundError;JSON 非法时由 json 抛错。
    """
    p = Path(path)
    agent_json = p / "agent.json" if p.is_dir() else p
    if not agent_json.is_file():
        raise FileNotFoundError(f"missing agent.json: {path}")
    ir = AgentIR.from_json(agent_json.read_text(encoding="utf-8"))
    ir.metadata["source_format"] = "generic"
    ir.metadata.setdefault("source_path", str(agent_json.resolve()))
    return ir
