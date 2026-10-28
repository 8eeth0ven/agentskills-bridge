"""Portable preservation capsules for the public converter registries.

Native framework projections and archival fidelity are different contracts. A
capsule preserves the IR and original regular files; its manifest binds them to
the native output. Hashes detect stale/damaged packages, not malicious forgery.
No source code is imported or executed while reading a capsule.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from functools import wraps
from pathlib import Path, PurePosixPath

from converter.ir import AgentIR, ToolSpec, parse_frontmatter

CAPSULE_DIR = ".agentskills-bridge"
SCHEMA_VERSION = 1


class PreservationError(ValueError):
    """A package cannot satisfy the preservation contract."""


def safe_path(value: str) -> Path:
    """Accept only canonical portable relative paths (never follow symlinks)."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise PreservationError(f"unsafe relative path: {value!r}")
    p = PurePosixPath(value)
    if not p.parts or p.is_absolute() or any(x in (".", "..") for x in p.parts) or p.as_posix() != value:
        raise PreservationError(f"unsafe relative path: {value!r}")
    if CAPSULE_DIR in p.parts:
        raise PreservationError(f"reserved capsule path: {value!r}")
    return Path(*p.parts)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_files(root: Path) -> dict:
    """Capture all regular files except the reserved root capsule directory.

    Symlinks and special files are rejected explicitly; empty directories,
    timestamps, ownership and ACLs are outside the contract.
    """
    files = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.relative_to(root).parts[0] == CAPSULE_DIR:
            continue
        safe_path(rel)
        if p.is_symlink():
            raise PreservationError(f"symlink is not a portable regular file: {rel}")
        if p.is_dir():
            continue
        if not p.is_file():
            raise PreservationError(f"unsupported special file: {rel}")
        raw = p.read_bytes()
        files[rel] = {"data": base64.b64encode(raw).decode("ascii"),
                      "sha256": _digest(raw), "mode": stat.S_IMODE(p.stat().st_mode) & 0o777}
    return files


def decode_files(files: dict) -> dict:
    """Validate the entire file inventory before any writes."""
    if not isinstance(files, dict):
        raise PreservationError("source_files must be an object")
    decoded = {}
    for rel, entry in files.items():
        safe_path(rel)
        try:
            raw = base64.b64decode(entry["data"], validate=True)
            mode = entry["mode"]
            if type(mode) is not int or not 0 <= mode <= 0o777:
                raise ValueError("invalid mode")
            if _digest(raw) != entry["sha256"]:
                raise ValueError("SHA-256 mismatch")
        except (ValueError, TypeError, KeyError) as exc:
            raise PreservationError(f"invalid source file {rel}: {exc}") from exc
        decoded[rel] = (raw, mode)
    for rel in decoded:
        if any(parent.as_posix() in decoded for parent in PurePosixPath(rel).parents if str(parent) != "."):
            raise PreservationError(f"source file/directory collision: {rel}")
    return decoded


def restore_files(files: dict, root: Path) -> None:
    """Restore validated regular-file bytes and POSIX permission bits."""
    for rel, (raw, mode) in decode_files(files).items():
        dst = root / safe_path(rel)
        # Reject existing symlinks in every component, including the root.
        if any(p.is_symlink() for p in (dst, *dst.parents)):
            raise PreservationError(f"symlink in output path: {rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        dst.chmod(mode)


def _replace_bytes(path: Path, raw: bytes) -> None:
    """Atomically replace staged files, including read-only source files."""
    mode = stat.S_IMODE(path.stat().st_mode) & 0o777 if path.exists() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bridge-edit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _rewrite_frontmatter(original: str, replacements: dict, body: str) -> bytes:
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", original, re.S)
    lines, keep = [], True
    if match:
        for line in match.group(1).splitlines(keepends=True):
            key = re.match(r"^([A-Za-z0-9_-]+):", line)
            if key:
                keep = key.group(1) not in replacements
            if keep:
                lines.append(line)
    extra = "".join(lines).rstrip("\r\n")
    front = "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                                for key, value in replacements.items())
    if extra:
        front += extra + "\n"
    return (front + "---\n\n" + body).encode("utf-8")


def _edit_interface(path: Path, changes: dict) -> None:
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"^interface:[ \t]*(?:#.*)?(?:\r?\n)?$", line)), None)
    if start is None:
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines[-1] += newline
        start = len(lines)
        lines.append("interface:" + newline)
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[^\s#][^:]*:", lines[i])), len(lines))
    pending = dict(changes)
    for i in range(start + 1, end):
        match = re.match(r"^( +)([A-Za-z0-9_-]+):", lines[i])
        if match and match.group(2) in pending:
            key = match.group(2)
            lines[i] = match.group(1) + key + ": " + json.dumps(pending.pop(key), ensure_ascii=False) + newline
    lines[end:end] = ["  " + key + ": " + json.dumps(value, ensure_ascii=False) + newline
                      for key, value in pending.items()]
    _replace_bytes(path, "".join(lines).encode("utf-8"))


def project_source_skill(ir: AgentIR, root: Path) -> None:
    """Restore original resources, then apply edits to active mapped IR fields.

    Unchanged inputs recover the exact original bytes. The source snapshot is
    archival provenance, never an excuse to replace newly edited instructions.
    """
    from converter.skill_loader import extract_interface_fields
    restore_files(ir.source_files, root)
    skill = root / "SKILL.md"
    if not skill.is_file():
        raise PreservationError("source_files must include SKILL.md for a skill projection")
    original = skill.read_bytes().decode("utf-8")
    meta, body = parse_frontmatter(original)
    replacements = {}
    if (meta.get("name", ""), meta.get("description", ""), body) != (
            ir.name, ir.description, ir.system_prompt):
        replacements.update(name=ir.name, description=ir.description)
    try:
        original_metadata = json.loads(meta.get("metadata", "{}"))
        if not isinstance(original_metadata, dict):
            original_metadata = None
    except ValueError:
        original_metadata = None
    old_tools = (original_metadata or {}).get("tools", [])
    try:
        old_tools = json.loads(meta["x-bridge-tools"]) if "x-bridge-tools" in meta else old_tools
        old_tools = [ToolSpec.from_dict(t).to_dict() for t in old_tools]
    except (ValueError, TypeError, AttributeError):
        old_tools = []
    new_tools = [t.to_dict() for t in ir.tools]
    if old_tools != new_tools:
        if original_metadata is not None and "x-bridge-tools" not in meta:
            replacements["metadata"] = {**original_metadata, "tools": new_tools}
        else:
            # Keep opaque YAML metadata intact; the explicit contract override
            # is recognized by load_skill, without interpreting arbitrary YAML.
            replacements["x-bridge-tools"] = new_tools
    if replacements:
        _replace_bytes(skill, _rewrite_frontmatter(original, replacements, ir.system_prompt))
    interfaces = sorted(p for p in (root / "agents").glob("*") if p.suffix in (".yaml", ".yml"))
    old, owners = {}, {}
    for path in interfaces:
        for key, value in extract_interface_fields(path.read_text(encoding="utf-8")).items():
            if value and key not in old:
                old[key], owners[key] = value, path
    changes = {}
    for key, value in (("display_name", ir.display_name), ("default_prompt", ir.default_prompt)):
        if old.get(key, "") != value:
            destinations = [owners.get(key, interfaces[0] if interfaces else root / "agents" / "openai.yaml")]
            if not value:
                # An empty first value must not expose a stale fallback from a
                # later interface file; match the loader's first-nonempty rule.
                destinations = interfaces or destinations
            for dst in destinations:
                changes.setdefault(dst, {})[key] = value
    for dst, fields in changes.items():
        _edit_interface(dst, fields)
    current = {doc.filename for doc in ir.knowledge}
    for rel in ir.source_files:
        if rel.startswith("references/") and rel.endswith(".md") and rel[len("references/"):] not in current:
            (root / safe_path(rel)).unlink()
    for doc in ir.knowledge:
        dst = root / "references" / safe_path(doc.filename)
        raw = doc.content.encode("utf-8")
        if not dst.is_file() or dst.read_bytes() != raw:
            _replace_bytes(dst, raw)


def portable_ir(ir: AgentIR) -> AgentIR:
    """Copy IR without machine-local source paths; all semantic fields survive."""
    data = ir.to_dict()
    data["metadata"].pop("source_path", None)
    for doc in data["knowledge"]:
        doc["source_path"] = ""
    return AgentIR.from_dict(data)


def _inventory(root: Path) -> dict:
    entries = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.relative_to(root).parts[0] == CAPSULE_DIR:
            continue
        safe_path(rel)
        if p.is_symlink():
            raise PreservationError(f"symlink in package: {rel}")
        if p.is_dir():
            continue
        if not p.is_file():
            raise PreservationError(f"special file in package: {rel}")
        entries[rel] = {"sha256": _digest(p.read_bytes()),
                        "mode": stat.S_IMODE(p.stat().st_mode) & 0o777}
    return entries


def write_capsule(ir: AgentIR, root: Path, fmt: str) -> None:
    """Write deterministic JSON, with no timestamps or local absolute paths."""
    decode_files(ir.source_files)
    capsule = root / CAPSULE_DIR
    capsule.mkdir()
    payload = (portable_ir(ir).to_json() + "\n").encode("utf-8")
    (capsule / "ir.json").write_bytes(payload)
    manifest = {"schema_version": SCHEMA_VERSION, "format": fmt,
                "ir_sha256": _digest(payload), "artifacts": _inventory(root)}
    (capsule / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def find_capsule(path: str | Path) -> Path | None:
    """Locate at the supplied root/file or its three conventional parents.

    Supports config/agents.yaml, .claude/agents/name.md and skills/name/SKILL.md.
    Bounded traversal prevents accidentally using an unrelated ancestor package.
    """
    p = Path(path).absolute()
    if p.is_symlink():
        raise PreservationError(f"symlink input: {path}")
    if not p.exists():
        raise FileNotFoundError(f"input does not exist: {path}")
    root = p if p.is_dir() else p.parent
    for candidate in (root, *list(root.parents)[:3]):
        capsule = candidate / CAPSULE_DIR
        if capsule.exists() or capsule.is_symlink():
            return candidate
    return None


def read_capsule(root: Path, expected_format: str | None = None) -> tuple[AgentIR, dict]:
    """Verify hashes, exact native file set and modes before returning any IR."""
    root = Path(root)
    capsule = root / CAPSULE_DIR
    try:
        if root.is_symlink() or capsule.is_symlink():
            raise PreservationError("symlink in capsule path")
        if {p.name for p in capsule.iterdir()} != {"ir.json", "manifest.json"}:
            raise PreservationError("unexpected capsule contents")
        if any(p.is_symlink() or not p.is_file() for p in capsule.iterdir()):
            raise PreservationError("capsule entries must be regular files")
        manifest = json.loads((capsule / "manifest.json").read_bytes())
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
            raise PreservationError("unsupported capsule schema_version")
        if expected_format and manifest.get("format") != expected_format:
            raise PreservationError(f"capsule format is {manifest.get('format')!r}, requested {expected_format!r}")
        raw = (capsule / "ir.json").read_bytes()
        if _digest(raw) != manifest["ir_sha256"]:
            raise PreservationError("capsule IR SHA-256 mismatch")
        if _inventory(root) != manifest["artifacts"]:
            raise PreservationError("native artifacts changed (bytes, file set or permissions)")
        ir = AgentIR.from_json(raw.decode("utf-8"))
        decode_files(ir.source_files)
        return ir, manifest
    except PreservationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PreservationError(f"invalid preservation capsule: {exc}") from exc


def _publish(staged: Path, out: Path) -> Path:
    """Refuse nonempty output, so failure cannot mix new and stale artifacts."""
    if out.is_symlink():
        raise PreservationError(f"symlink output directory: {out}")
    if out.exists():
        if not out.is_dir() or any(out.iterdir()):
            raise PreservationError(f"output must be a new or empty directory: {out}")
        out.rmdir()
    os.replace(staged, out)
    return out


def package_output(ir: AgentIR, out_dir: str | Path, fmt: str, emit) -> Path:
    """Stage, validate and publish a native projection plus its capsule."""
    decode_files(ir.source_files)
    for doc in ir.knowledge:
        safe_path(doc.filename)
    safe_path(ir.name or "agent")
    out = Path(out_dir).absolute()
    if out.is_symlink():
        raise PreservationError(f"symlink output directory: {out}")
    out = out.parent.resolve() / out.name
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise PreservationError(f"output must be a new or empty directory: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bridge-stage-", dir=out.parent) as tmp:
        staged = Path(tmp) / "package"
        staged.mkdir()
        clean = portable_ir(ir)
        emit(clean, staged)
        if fmt in ("crewai-skills", "deepagents"):
            skill = next((staged / "skills").iterdir())
            # A native skills runtime needs the resources too, not just an archive.
            if ir.source_files:
                project_source_skill(ir, skill)
            else:
                _materialize_knowledge(ir, skill / "references")
        elif fmt != "skill":
            _materialize_knowledge(ir, staged / "knowledge")
        write_capsule(clean, staged, fmt)
        return _publish(staged, out)


def _materialize_knowledge(ir: AgentIR, root: Path) -> None:
    for doc in ir.knowledge:
        target = root / safe_path(doc.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(doc.content.encode("utf-8"))


def preserving_emitter(fmt: str, emit):
    """Wrap a low-level native emitter for use through EMITTERS."""
    @wraps(emit)
    def wrapped(ir, out_dir):
        return package_output(ir, out_dir, fmt, emit)
    return wrapped


def preserving_parser(fmt: str, parse):
    """Require an intact capsule when present; native_only explicitly bypasses."""
    @wraps(parse)
    def wrapped(path, *, native_only=False):
        if not native_only:
            root = find_capsule(path)
            if root is not None:
                return read_capsule(root, fmt)[0]
        return parse(path)
    return wrapped
