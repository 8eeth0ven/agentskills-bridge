"""从 agent 产物目录回收 knowledge/*.md 为 KnowledgeDoc。

skill2agent 各 emitter 都把 references 原样拷到 knowledge/;反向
agent2skill 时把同目录 knowledge/ 装回,保证 roundtrip 不丢知识。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Union

try:
    from converter.ir import KnowledgeDoc
except ImportError:  # pragma: no cover - 包内相对导入兜底
    from ..ir import KnowledgeDoc  # type: ignore


def collect_knowledge(*base_dirs: Union[str, Path]) -> List[KnowledgeDoc]:
    """收集各候选目录下 knowledge/*.md;同名文件先到先得(去重)。"""
    seen: dict = {}
    for base in base_dirs:
        kdir = Path(base) / "knowledge"
        if not kdir.is_dir():
            continue
        for path in sorted(kdir.rglob("*.md")):
            rel = path.relative_to(kdir).as_posix()
            if rel in seen:
                continue
            content = path.read_bytes().decode("utf-8")
            title = ""
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            seen[rel] = KnowledgeDoc(
                filename=rel,
                title=title or path.stem,
                content=content,
                source_path=str(path.resolve()),
            )
    return list(seen.values())
