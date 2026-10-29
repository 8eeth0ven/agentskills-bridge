"""Source context and redaction for model-assisted migrations.

Source assets remain in the local preservation capsule. Only readable task,
reference and code content is sent to the selected model; credentials and
machine-local source locations are excluded from prompts and shared reports.
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from converter.ir import AgentIR
from converter.preservation import CAPSULE_DIR, decode_files, portable_ir, safe_path

_TEXT_SUFFIXES = {".py", ".pyi", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".js", ".mjs", ".cjs", ".ts", ".sh", ".csv", ".sql", ".xml", ".ini", ".cfg"}
_PRIVATE_NAME = re.compile(r"(^|[./_-])(\.env|credentials?|secrets?|passwords?|id_rsa|id_ed25519|api[_-]?keys?|access[_-]?tokens?)([./_-]|$)", re.I)
_PRIVATE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_EXCLUDED_DIRS = {".git", "venv", "node_modules", "out", CAPSULE_DIR, "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"}
_PRIVATE_COMPONENTS = {".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc", ".git-credentials"}
_SENSITIVE_FIELDS = {"password", "passwd", "passphrase", "apikey", "accesskey", "secretaccesskey", "clientsecret", "secret", "credential", "credentials", "authorization", "authtoken", "accesstoken", "refreshtoken", "idtoken", "sessiontoken", "bearertoken", "token", "privatekey"}
_SECRET = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)
_LOCAL_PATH = re.compile(r"(?:/(?:Users|home|private|var/folders)/[^\s\"'<>`]+|[A-Za-z]:\\Users\\[^\s\"'<>`]+)")
_LITERAL_CREDENTIAL = re.compile(
    r"(?P<prefix>\b(?:[A-Za-z0-9_-]*(?:password|passwd|passphrase|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret)|authorization)[\"']?\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", re.I)
_CONFIG_ASSIGNMENT = re.compile(
    r"^(?P<prefix>[ \t]*(?:-[ \t]+)?[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[\"']?[ \t]*[:=][ \t]*)(?P<value>[^\r\n]+)", re.M)
_JSON_CREDENTIAL = re.compile(
    r'(?P<prefix>"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)"[ \t]*:[ \t]*)"(?:\\.|[^"\\])*"')
_UNQUOTED_CREDENTIAL = re.compile(
    r"(?P<prefix>\b(?P<key>password|passwd|passphrase|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret)[\"']?[ \t]*[:=][ \t]*)(?P<value>[A-Za-z0-9_./+@-]+)", re.I)
_PLACEHOLDER = re.compile(
    r"^(?:<[^>]+>|\$\{[^}]+\}|\*{3,}|(?:your|replace|insert|example|dummy|test|fake|placeholder)(?:[-_ ].*)?|api[-_ ]?key|token|password|true|false|null|none|\.\.\.)$", re.I)
_CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def _literal_value(raw: str) -> str | None:
    """Read a credential scalar, never an expression or type annotation."""
    value = raw.strip()
    if value.startswith(('"', "'")):
        quote = value[0]
        match = re.match(r'"((?:\\.|[^"\\])*)"' if quote == '"' else r"'((?:\\.|[^'\\])*)'", value)
        if match:
            return match.group(1)
        return None
    value = value.split(" #", 1)[0].strip().rstrip(",")
    if not value or any(char in value for char in "()[]{};") or value.startswith(("$", "os.", "env.")):
        return None
    if value in ("str", "int", "float", "bool", "dict", "list", "bytes"):
        return None
    return value


def _redact_assignments(text: str) -> str:
    def replace(match):
        if not _sensitive_field(match.group("key")) or _literal_value(match.group("value")) is None:
            return match.group(0)
        return match.group("prefix") + '"<redacted>"'
    return _CONFIG_ASSIGNMENT.sub(replace, text)


def private_source_path(value: str | Path) -> bool:
    """Recognize credential-bearing resources consistently in every IR view."""
    path = Path(value)
    return (any(part.startswith(".env") or part in _PRIVATE_COMPONENTS for part in path.parts)
            or bool(_PRIVATE_NAME.search(path.as_posix()))
            or path.suffix.lower() in _PRIVATE_SUFFIXES)


def _excluded_directory(name: str) -> bool:
    return name in _EXCLUDED_DIRS or name.startswith(".venv") or name in _PRIVATE_COMPONENTS


def collect_source_assets(root: str | Path) -> dict:
    """Statically capture an explicit native project without executing its code.

    Return portable regular-file bytes for source/ reuse. Dependencies, generated
    output, VCS internals and credential files are excluded before reading; any
    other symlink/special file is rejected. Text context limits are applied later
    by source_context and never silently truncate the project's implementation.
    """
    root = Path(root)
    if root.is_symlink() or not root.exists():
        raise ValueError("native source root must exist and must not be a symlink")
    base = root if root.is_dir() else root.parent
    files = []
    if root.is_file():
        files = [root]
    elif root.is_dir():
        for current, directories, names in os.walk(root, followlinks=False):
            retained = []
            for name in sorted(directories):
                candidate = Path(current) / name
                rel = candidate.relative_to(base)
                if _excluded_directory(name) or private_source_path(rel):
                    continue
                if candidate.is_symlink():
                    raise ValueError("native source contains an unsupported symlink directory")
                retained.append(name)
            directories[:] = retained
            files.extend(Path(current) / name for name in sorted(names))
    else:
        raise ValueError("native source root must be a regular file or directory")
    result = {}
    for path in sorted(files):
        rel = path.relative_to(base).as_posix()
        if private_source_path(rel) or any(_excluded_directory(part) for part in path.relative_to(base).parts[:-1]):
            continue
        safe_path(rel)
        if path.is_symlink() or not path.is_file():
            raise ValueError("native source contains an unsupported nonregular file")
        raw = path.read_bytes()
        result[rel] = {"data": base64.b64encode(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest(),
                       "mode": stat.S_IMODE(path.stat().st_mode) & 0o777}
    return result


def _sensitive_field(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _SENSITIVE_FIELDS or any(normalized.endswith(suffix) for suffix in
                                                ("password", "passwd", "passphrase", "apikey", "clientsecret", "secretaccesskey", "accesstoken", "refreshtoken", "authtoken", "privatekey"))


def _metadata(value: Any, redactor: "Redactor") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _sensitive_field(str(key)):
                # A schema property named api_key describes a parameter; it is
                # not itself a credential. Preserve its contract while removing
                # literal credential defaults/examples from that property.
                if isinstance(item, dict) and (item.get("type") in ("string", "integer", "number", "boolean", "object", "array", "null")
                                               or any(name in item for name in ("$ref", "anyOf", "oneOf", "allOf"))):
                    clean = {name: child for name, child in item.items()
                             if name not in ("default", "const", "enum", "examples")}
                    result[redactor.text(str(key))] = _metadata(clean, redactor)
                else:
                    result[redactor.text(str(key))] = "<redacted>"
            else:
                result[redactor.text(str(key))] = _metadata(item, redactor)
        return result
    if isinstance(value, (list, tuple)):
        return [_metadata(item, redactor) for item in value]
    if isinstance(value, str):
        return redactor.document(value, "metadata.md")
    return redactor.scrub(value)


class Redactor:
    """Mask active credentials and local paths without logging their values."""

    def __init__(self, *roots: str | Path):
        self.roots = sorted({str(Path(p).absolute()) for p in roots if p} | {str(Path.home())}, key=len, reverse=True)
        self.secrets = sorted({value for name, value in os.environ.items()
                               if len(value) >= 8 and any(part in name.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "KEY"))},
                              key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "<redacted>")
        for root in self.roots:
            value = value.replace(root, "<local>")
        value = _PRIVATE_KEY.sub("<redacted-private-key>", value)
        value = _SECRET.sub("<redacted-credential>", value)
        value = _LITERAL_CREDENTIAL.sub(lambda match: match.group("prefix") + '"<redacted>"', value)
        return _LOCAL_PATH.sub("<local-path>", value)

    def document(self, value: str, path: str | Path) -> str:
        """Redact raw configuration and Markdown views as well as IR metadata."""
        suffix = Path(path).suffix.lower()
        if suffix == ".json":
            try:
                value = json.dumps(_metadata(json.loads(value), self), ensure_ascii=False, indent=2)
            except (ValueError, TypeError):
                value = _redact_assignments(value)
        elif suffix in _CONFIG_SUFFIXES or suffix in (".md", ".txt"):
            value = _redact_assignments(value)
            # Markdown can embed a compact JSON credential object, including
            # within code fences. It is still a repeated source-content view.
            value = _JSON_CREDENTIAL.sub(
                lambda match: match.group("prefix") + '"<redacted>"'
                if _sensitive_field(match.group("key")) and match.group("key").lower() != "token"
                else match.group(0), value)
            value = _UNQUOTED_CREDENTIAL.sub(
                lambda match: match.group("prefix") + "<redacted>"
                if _literal_value(match.group("value")) is not None
                else match.group(0), value)
        return self.text(value)

    def has_sensitive_data(self, value: str, path: str | Path | None = None) -> bool:
        """Check generated text without treating safe examples as leaked keys.

        Prompt redaction is deliberately conservative. Artifact rejection uses
        known active secrets, recognizable credential material, local paths,
        and literal credentials in configuration files. Parameter names and
        arbitrary business variables named ``token`` are not credentials.
        """
        if any(secret in value for secret in self.secrets):
            return True
        if any(root and root in value for root in self.roots) or _PRIVATE_KEY.search(value) or _SECRET.search(value) or _LOCAL_PATH.search(value):
            return True
        if path is None or Path(path).suffix.lower() not in _CONFIG_SUFFIXES:
            return False
        if Path(path).suffix.lower() == ".json":
            try:
                def contains(item):
                    if isinstance(item, dict):
                        return any((_sensitive_field(str(key)) and isinstance(child, str)
                                    and bool(child) and not _PLACEHOLDER.fullmatch(child.strip()))
                                   or contains(child) for key, child in item.items())
                    if isinstance(item, list):
                        return any(contains(child) for child in item)
                    return False
                return contains(json.loads(value))
            except (ValueError, TypeError):
                pass
        for match in _CONFIG_ASSIGNMENT.finditer(value):
            literal = _literal_value(match.group("value"))
            if _sensitive_field(match.group("key")) and literal and not _PLACEHOLDER.fullmatch(literal):
                return True
        return False

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, tuple):
            return [self.scrub(item) for item in value]
        if isinstance(value, dict):
            return {self.text(str(key)): self.scrub(item) for key, item in value.items()}
        return value


def source_context(ir: AgentIR, redactor: Redactor, max_chars: int = 500_000,
                   source_assets: dict | None = None) -> dict:
    """Build a complete bounded text context; never silently truncate a source."""
    data = portable_ir(ir).to_dict()
    data.pop("source_files", None)
    # Paths to local copies are not meaningful model context.
    data["metadata"] = _metadata({key: value for key, value in data["metadata"].items()
                                  if not key.startswith("_")}, redactor)
    for name in ("system_prompt", "description", "default_prompt", "display_name"):
        data[name] = redactor.document(data[name], name + ".md")
    for tool in data["tools"]:
        tool["description"] = redactor.document(tool["description"], "tool-description.md")
    for task in data["tasks"]:
        for name in ("description", "expected_output"):
            task[name] = redactor.document(task[name], "task-" + name + ".md")
    data["knowledge"] = [{**doc, "content": redactor.document(doc["content"], doc["filename"])}
                         for doc in data["knowledge"] if not private_source_path(doc["filename"])]
    data["scripts"] = [rel for rel in data["scripts"] if not private_source_path(rel)]
    files, inventory, excluded = [], [], 0
    assets = ir.source_files if source_assets is None else source_assets
    for rel, (raw, mode) in decode_files(assets).items():
        path = Path(rel)
        if private_source_path(rel):
            excluded += 1
            continue
        inventory.append({"path": rel, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "mode": mode})
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            continue
        if "\x00" not in text:
            files.append({"path": rel, "content": redactor.document(text, rel)})
    context = redactor.scrub({"ir": data, "files": files, "inventory": inventory,
                              "excluded_credential_files": excluded})
    encoded = json.dumps(context, ensure_ascii=False)
    if len(encoded) > max_chars:
        raise ValueError(f"source context has {len(encoded)} characters, exceeding context limit {max_chars}; increase --context-chars")
    return context


def project_context(root: Path, redactor: Redactor, max_chars: int = 500_000) -> list[dict]:
    """Expose current native text artifacts to generation/repair, not capsules."""
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_symlink():
            raise ValueError("generated project contains a symlink")
        if not path.is_file() or ".agentskills-bridge" in rel.parts or "__pycache__" in rel.parts:
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if private_source_path(rel):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeError:
            continue
        if "\x00" not in text:
            files.append({"path": rel.as_posix(), "content": redactor.document(text, rel)})
    if len(json.dumps(files, ensure_ascii=False)) > max_chars:
        raise ValueError("native project context exceeds --context-chars; increase the configured limit")
    return files
