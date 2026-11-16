"""llm-wiki 只读访问层。

wiki 是本工具的知识来源(各框架格式规范、转换规则),设计为只读:
- 任何写操作方法在这里直接抛 ReadOnlyWikiError(设计级只读);
- 文件系统级由 MANIFEST.sha256 + verify() 保证被改动可被发现;
- 部署时配合 chmod a-w 实现三重保护。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Tuple

MANIFEST_NAME = "MANIFEST.sha256"


class ReadOnlyWikiError(PermissionError):
    """llm-wiki 是只读知识库,禁止任何写操作。"""


class Wiki:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"wiki root not found: {self.root}")

    def _resolve(self, rel_path: str) -> Path:
        """Resolve paths by components, including symlinks, within the wiki root."""
        try:
            target = (self.root / rel_path).resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"cannot resolve wiki path: {rel_path}") from exc
        # Python 3.13 may leave a symlink cycle unresolved in non-strict mode.
        if target.is_symlink():
            raise ValueError(f"cannot resolve wiki path: {rel_path}")
        if not target.is_relative_to(self.root):
            raise ValueError(f"path escapes wiki root: {rel_path}")
        return target

    # ---------- 只读操作 ----------

    def list_chapters(self) -> List[Path]:
        """全部章节 md,按路径排序;不含 MANIFEST。"""
        chapters = []
        for path in self.root.rglob("*.md"):
            try:
                resolved = self._resolve(str(path.relative_to(self.root)))
            except ValueError:
                continue
            if resolved.is_file():
                chapters.append(path)
        return sorted(chapters)

    def read(self, rel_path: str) -> str:
        """读一个章节;防路径穿越。"""
        target = self._resolve(rel_path)
        if not target.is_file():
            raise FileNotFoundError(f"chapter not found: {rel_path}")
        return target.read_text(encoding="utf-8")

    def verify(self) -> Tuple[bool, List[str]]:
        """校验 MANIFEST.sha256:每个清单条目 hash 一致,且无未登记的新文件。"""
        errors: List[str] = []
        try:
            manifest = self._resolve(MANIFEST_NAME)
        except ValueError:
            return False, [f"{MANIFEST_NAME} escapes wiki root"]
        if not manifest.is_file():
            return False, [f"missing {MANIFEST_NAME}"]
        recorded = {}
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, _, rel = line.partition("  ")
            if not rel:
                errors.append(f"malformed manifest line: {line!r}")
                continue
            recorded[rel] = digest
        for rel, digest in sorted(recorded.items()):
            try:
                path = self._resolve(rel)
            except ValueError:
                errors.append(f"listed file escapes wiki root: {rel}")
                continue
            if not path.is_file():
                errors.append(f"listed file missing: {rel}")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != digest:
                errors.append(f"hash mismatch: {rel}")
        current = set()
        for path in self.root.rglob("*.md"):
            rel = str(path.relative_to(self.root))
            try:
                resolved = self._resolve(rel)
            except ValueError:
                errors.append(f"chapter cannot be resolved within wiki root: {rel}")
                continue
            if resolved.is_file():
                current.add(rel)
            elif path.is_symlink():
                errors.append(f"chapter link has no regular target: {rel}")
        unlisted = sorted(current - set(recorded))
        for rel in unlisted:
            errors.append(f"file not in manifest: {rel}")
        return not errors, errors

    def build_manifest(self) -> str:
        """(仅构建期由项目维护者手动调用)重新生成清单文本。"""
        lines = ["# llm-wiki integrity manifest (sha256)  -- regenerate via maintainer only"]
        for p in self.list_chapters():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{digest}  {p.relative_to(self.root)}")
        return "\n".join(lines) + "\n"

    # ---------- 设计级只读:写操作一律拒绝 ----------

    def write(self, *args, **kwargs):  # noqa: D102
        raise ReadOnlyWikiError("llm-wiki is read-only; regenerate manifest via maintainer script instead")

    def save(self, *args, **kwargs):
        raise ReadOnlyWikiError("llm-wiki is read-only")

    def update(self, *args, **kwargs):
        raise ReadOnlyWikiError("llm-wiki is read-only")

    def delete(self, *args, **kwargs):
        raise ReadOnlyWikiError("llm-wiki is read-only")
