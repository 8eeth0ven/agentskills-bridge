"""Independent static, behavioral and native-runtime checks for AI migrations.

The execution flag is an explicit decision to run generated code. Temporary
HOME, a credential-free environment, timeouts and output limits reduce ambient
state; they are not an operating-system security sandbox.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

OUTPUT_LIMIT = 131072
RESULT_MARKER = "__AGENTSKILLS_BRIDGE_RESULT__"


def _relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("module must be a portable relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("module must be a portable relative path")
    return Path(*path.parts)


def _safe_file(root: Path, value: str) -> Path:
    path = root / _relative(value)
    if any(p.is_symlink() for p in (path, *list(path.parents)[:len(path.relative_to(root).parts)])):
        raise ValueError("symlinks are not executable project inputs")
    if not path.is_file():
        raise ValueError(f"missing project file: {value}")
    return path


def redact(text: Any, root: Path | None = None) -> str:
    """Remove ambient credentials and machine-local paths from diagnostics."""
    value = str(text)
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"KEY|TOKEN|SECRET|PASSWORD|BASE_URL", key, re.I):
            value = value.replace(secret, "<redacted>")
    if root is not None:
        for variant in (str(root), str(root.absolute()), str(root.resolve())):
            value = value.replace(variant, "<project>")
    value = value.replace(str(Path.home()), "<home>")
    value = re.sub(r"(?:/private)?/(?:tmp|var/folders)/[^\s\"'<>:]+", "<temporary-path>", value)
    value = re.sub(r"/(?:Users|home)/[^/\s\"'<>]+", "<home>", value)
    value = re.sub(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\\\s\"'<>]+", "<home>", value)
    return value


def _clean_environment(home: str) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items()
              if key in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ")}
    result.update(HOME=home, USERPROFILE=home, TMPDIR=home, TEMP=home, TMP=home,
                  PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                  OTEL_SDK_DISABLED="true", CREWAI_TELEMETRY_ENABLED="false",
                  ANONYMIZED_TELEMETRY="false", DO_NOT_TRACK="1")
    return result


def run_command(argv: list[str], root: Path, *, stdin: str = "", timeout: float = 30,
                _capture_raw: bool = False) -> dict:
    """Run argv without a shell, bound time/output, and kill its process group."""
    started = time.monotonic()
    result: dict[str, Any] = {"ok": False, "returncode": None, "stdout": "", "stderr": "",
                              "timed_out": False, "output_limited": False}
    if not argv or any(not isinstance(x, str) or "\x00" in x for x in argv):
        result["stderr"] = "invalid runtime command argv"
        return result
    process = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    with tempfile.TemporaryDirectory(prefix="bridge-execution-") as home, tempfile.TemporaryFile() as source:
        source.write(stdin.encode("utf-8"))
        source.seek(0)
        try:
            process = subprocess.Popen(argv, cwd=root, stdin=source, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=_clean_environment(home),
                                       start_new_session=True)
            selector = selectors.DefaultSelector()
            assert process.stdout is not None and process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            deadline = started + max(0.05, float(timeout))
            try:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        result["timed_out"] = True
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        data = os.read(key.fileobj.fileno(), 8192)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        target = buffers[key.data]
                        available = OUTPUT_LIMIT - len(target)
                        target.extend(data[:max(0, available)])
                        if len(data) > available:
                            result["output_limited"] = True
                            break
                    if result["output_limited"]:
                        break
                if result["timed_out"] or result["output_limited"]:
                    _kill_process(process)
                else:
                    try:
                        process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        result["timed_out"] = True
                        _kill_process(process)
            finally:
                selector.close()
                process.stdout.close()
                process.stderr.close()
            result["returncode"] = process.returncode
            # A successful leader must not leave descendants running after a
            # verification case has finished. This is process cleanup, not an
            # operating-system sandbox against deliberately hostile code.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                pass
        except (OSError, ValueError) as exc:
            result["stderr"] = redact(exc, root)
            if process is not None:
                _kill_process(process)
    for key, value in buffers.items():
        if value:
            result[key] = redact(value.decode("utf-8", errors="replace"), root)
    if _capture_raw:
        # Transient parent-only comparison input. Callers must pop this before
        # returning or persisting a report; public diagnostics stay redacted.
        result["_raw_stdout"] = buffers["stdout"].decode("utf-8", errors="replace")
    result["duration_seconds"] = round(time.monotonic() - started, 4)
    result["ok"] = result["returncode"] == 0 and not result["timed_out"] and not result["output_limited"]
    if result["timed_out"]:
        result["stderr"] += "\nexecution timed out"
    if result["output_limited"]:
        result["stderr"] += "\nexecution output exceeded its limit"
    return result


def _kill_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError):
        process.kill()
    process.wait()


_FUNCTION_RUNNER = r'''
import asyncio, importlib.util, inspect, json, pathlib, sys
root = pathlib.Path.cwd()
specification = json.load(sys.stdin)
sys.path.insert(0, str(root))
path = root / specification["module"]
spec = importlib.util.spec_from_file_location("bridge_acceptance_module", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
try:
    spec.loader.exec_module(module)
    function = getattr(module, specification["callable"])
    if not callable(function):
        raise TypeError("acceptance target is not callable")
    value = function(**specification["input"])
    if inspect.isawaitable(value):
        value = asyncio.run(value)
except BaseException as error:
    raise RuntimeError("acceptance code must return a result without terminating the runner") from error
print("__AGENTSKILLS_BRIDGE_RESULT__" + json.dumps({"value": value}, ensure_ascii=False, allow_nan=False))
'''

_CLI_RUNNER = r'''
import io, json, pathlib, runpy, sys
specification = json.load(sys.stdin)
class BoundedOutput(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > 131072:
            raise ValueError("CLI JSON output exceeded its limit")
        return super().write(value)
output = BoundedOutput()
sys.path.insert(0, str(pathlib.Path.cwd()))
sys.argv = [specification["module"]]
sys.stdin = io.StringIO(json.dumps(specification["input"], ensure_ascii=False, allow_nan=False))
original_stdout = sys.stdout
sys.stdout = output
try:
    try:
        runpy.run_path(specification["module"], run_name="__main__")
    except SystemExit as error:
        if error.code not in (None, 0):
            raise
finally:
    sys.stdout = original_stdout
text = output.getvalue()
print("__AGENTSKILLS_BRIDGE_RESULT__" + json.dumps({"value": json.loads(text)}, ensure_ascii=False, allow_nan=False))
'''


def _function_names(root: Path, acceptance: list[dict], tools: list[dict]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {"bridge_workflow.py": {"run"}, "agent.py": {"build_agent", "build_crew"}}
    for case in acceptance:
        if case.get("kind") == "function":
            names.setdefault(str(case.get("module", "")), set()).add(str(case.get("callable", "")))
    for tool in tools:
        names.setdefault(str(tool.get("implementation_file", "bridge_tools.py")), set()).add(str(tool.get("callable", tool.get("name", ""))))
    return names


def _static_checks(root: Path, acceptance: list[dict], tools: list[dict]) -> tuple[list[dict], list[str]]:
    checks, errors = [], []
    function_names = _function_names(root, acceptance, tools)
    native_packages = {"langchain", "langchain_core", "langgraph", "deepagents", "crewai",
                       "autogen_agentchat", "autogen_core", "autogen_ext"}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"symlink in project: {rel}")
            continue
        if ".agentskills-bridge" in path.relative_to(root).parts or path.relative_to(root).parts[0] == "source":
            # Immutable source archives may contain code for other interpreters.
            # Only generated active implementations are globally compiled;
            # any source code actually reused is validated by its execution.
            continue
        first = path.relative_to(root).parts[0]
        if first in native_packages or (path.parent == root and path.stem in native_packages):
            errors.append(f"project-local native framework shadowing is forbidden: {rel}")
            continue
        if not path.is_file() or path.suffix not in (".py", ".json"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                json.loads(text)
            else:
                tree = ast.parse(text, filename=rel)
                compile(tree, rel, "exec")
                selected = function_names.get(rel, set())
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in selected:
                        continue
                    body = list(node.body)
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                        body = body[1:]
                    if not body or all(isinstance(item, ast.Pass) or (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and item.value.value is Ellipsis) for item in body):
                        raise ValueError(f"unimplemented function: {node.name}")
                    segment = ast.get_source_segment(text, node) or ""
                    if "TODO(stub)" in segment or "[stub]" in segment:
                        raise ValueError(f"placeholder implementation: {node.name}")
                    for item in ast.walk(node):
                        if isinstance(item, ast.Raise):
                            exception = item.exc.func if isinstance(item.exc, ast.Call) else item.exc
                            if isinstance(exception, ast.Name) and exception.id == "NotImplementedError":
                                raise ValueError(f"unimplemented function: {node.name}")
            checks.append({"kind": "syntax", "file": rel, "ok": True})
        except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
            error = f"{rel}: {redact(exc, root)}"
            errors.append(error)
            checks.append({"kind": "syntax", "file": rel, "ok": False, "error": error})
    if not checks:
        errors.append("project contains no Python or JSON implementation files")
    return checks, errors


def _validate_case(root: Path, case: dict) -> None:
    if not isinstance(case, dict):
        raise ValueError("acceptance case must be an object")
    for key in ("id", "requirement_id", "kind", "module", "input", "expected"):
        if key not in case:
            raise ValueError(f"acceptance case missing {key}")
    if not isinstance(case["id"], str) or not case["id"] or not isinstance(case["requirement_id"], str) or not case["requirement_id"]:
        raise ValueError("acceptance identifiers must be nonempty strings")
    if case["kind"] not in ("function", "cli_json"):
        raise ValueError("unknown acceptance kind")
    if _safe_file(root, case["module"]).suffix != ".py":
        raise ValueError("acceptance module must be a Python file")
    if case["kind"] == "function":
        if not re.fullmatch(r"[A-Za-z_]\w*", case.get("callable", "")):
            raise ValueError("acceptance callable must be a Python identifier")
        if not isinstance(case["input"], dict):
            raise ValueError("function acceptance input must be keyword arguments")
    json.dumps(case["input"], allow_nan=False)
    json.dumps(case["expected"], allow_nan=False)


def _file_inventory(root: Path) -> dict[str, tuple[str, int]]:
    """Snapshot existing regular files, including immutable source resources."""
    inventory = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("execution project contains a symlink")
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.S_IMODE(path.stat().st_mode) & 0o777,
            )
        elif not path.is_dir():
            raise ValueError("execution project contains a nonregular file")
    return inventory


def _changed_existing_files(root: Path, inventory: dict[str, tuple[str, int]]) -> list[str]:
    changed = []
    for rel, expected in inventory.items():
        path = root / rel
        try:
            if any(component.is_symlink() for component in
                   (path, *list(path.parents)[:len(Path(rel).parts)])):
                changed.append(rel)
                continue
            observed = (hashlib.sha256(path.read_bytes()).hexdigest(),
                        stat.S_IMODE(path.stat().st_mode) & 0o777)
            if not path.is_file() or observed != expected:
                changed.append(rel)
        except (OSError, ValueError):
            changed.append(rel)
    return changed


def _execute_on_copy(root: Path, action) -> dict:
    """Execute against a disposable copy, never publish execution side effects.

    New business output files are allowed in the copy. Existing implementation
    and resource bytes/modes must remain unchanged. Each case and the native
    probe receive fresh copies so one case cannot rewrite the next one's code.
    This limits incidental state; it is not an operating-system sandbox.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="bridge-project-execution-") as temporary:
            project = Path(temporary) / "project"
            shutil.copytree(root, project, symlinks=True)
            inventory = _file_inventory(project)
            result = action(project)
            changed = _changed_existing_files(project, inventory)
            result["project_unchanged"] = not changed
            if changed:
                result["ok"] = False
                result["status"] = "failed"
                result["stderr"] = result.get("stderr", "") + "\nExecution modified existing project files: " + ", ".join(changed[:20])
            return result
    except (OSError, ValueError, shutil.Error) as exc:
        return {"ok": False, "status": "failed", "returncode": None,
                "stdout": "", "stderr": "Execution copy failed: " + redact(exc, root),
                "project_unchanged": False}


def validate_project(root: Path, target: str, acceptance: list[dict], *, execute: bool = False,
                     python_executable: str = sys.executable, timeout: float = 30,
                     runtime_command: list[str] | None = None, tools: list[dict] | None = None) -> dict:
    """Validate immutable source-derived cases and a separate native runtime.

    The caller owns/fixes the acceptance list before code generation. The model
    generating or repairing files must never be allowed to weaken those cases.
    No success is reported without execution and a native runtime check.
    """
    root = Path(root)
    result: dict[str, Any] = {"ok": False, "static_ok": False, "executed": False,
                              "runtime_ok": False, "status": "failed", "checks": [], "errors": []}
    if root.is_symlink() or not root.is_dir():
        result["errors"].append("project root must be a regular directory")
        return result
    root = root.resolve()
    if not isinstance(acceptance, list) or not acceptance or any(not isinstance(case, dict) for case in acceptance):
        result["errors"].append("source-derived acceptance cases must be a nonempty list of objects")
        return result
    if tools is not None and (not isinstance(tools, list) or any(not isinstance(tool, dict) for tool in tools)):
        result["errors"].append("tools must be a list of objects")
        return result
    checks, errors = _static_checks(root, acceptance, tools or [])
    result["checks"].extend(checks)
    result["errors"].extend(errors)
    ids = set()
    for case in acceptance:
        try:
            _validate_case(root, case)
            if case["id"] in ids:
                raise ValueError("duplicate acceptance case id")
            ids.add(case["id"])
        except (ValueError, TypeError, OSError) as exc:
            result["errors"].append(redact(exc, root))
    result["static_ok"] = not result["errors"]
    if not result["static_ok"]:
        return result
    if not execute:
        result["status"] = "not_executed"
        result["errors"].append("execution was not enabled; static checks alone do not establish migration success")
        return result
    result["executed"] = True
    original_files = _file_inventory(root)
    for case in acceptance:
        runner = _FUNCTION_RUNNER if case["kind"] == "function" else _CLI_RUNNER
        child_input = {key: case[key] for key in ("module", "input")}
        if case["kind"] == "function":
            child_input["callable"] = case["callable"]
        report = _execute_on_copy(root, lambda project: run_command(
            [str(python_executable), "-B", "-c", runner], project,
            stdin=json.dumps(child_input, ensure_ascii=False, allow_nan=False),
            timeout=timeout, _capture_raw=True))
        raw_output = report.pop("_raw_stdout", "")
        if report["ok"]:
            try:
                if raw_output.count(RESULT_MARKER) != 1:
                    raise ValueError("acceptance runner returned missing or duplicate result frames")
                evidence = json.loads(raw_output.split(RESULT_MARKER, 1)[1].strip())
                if not isinstance(evidence, dict) or set(evidence) != {"value"}:
                    raise ValueError("acceptance runner must return actual result data")
                actual = json.dumps(evidence["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                expected = json.dumps(case["expected"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if actual != expected:
                    raise ValueError("expected JSON " + expected + "; observed " + actual)
            except (IndexError, ValueError, TypeError) as exc:
                report["ok"] = False
                report["stderr"] += "\n" + redact(exc, root)
        report.update(kind="acceptance", id=case["id"], requirement_id=case["requirement_id"])
        result["checks"].append(report)
        if not report["ok"]:
            result["errors"].append(f"acceptance {case['id']} failed: {report['stderr'][-4000:]}")
    if runtime_command is not None:
        command = list(runtime_command)
        if command and command[0] in ("python", "python3", "{python}"):
            command[0] = str(python_executable)
        def run_native_command(project):
            # Project-local absolute argv paths must refer to the execution
            # copy too; the interpreter/host executable outside root is kept.
            prefix = str(root) + os.sep
            copied_command = [str(project / value[len(prefix):]) if value.startswith(prefix) else value
                              for value in command]
            return run_command(copied_command, project, timeout=timeout)
        runtime = _execute_on_copy(root, run_native_command)
        runtime.update(kind="native_runtime", method="user_command")
        runtime["status"] = "passed" if runtime["ok"] else "failed"
    else:
        from converter.ai_runtime import native_runtime_probe
        runtime = _execute_on_copy(root, lambda project: native_runtime_probe(
            project, target, acceptance, tools or [],
            python_executable=str(python_executable), timeout=timeout))
    result["checks"].append(runtime)
    result["runtime_ok"] = bool(runtime["ok"])
    if not runtime["ok"]:
        result["errors"].append(f"native runtime validation failed: {runtime.get('stderr', runtime.get('error', 'no native runtime evidence'))}")
    changed_original = _changed_existing_files(root, original_files)
    if changed_original:
        result["errors"].append("Published project changed during verification: " + ", ".join(changed_original[:20]))
    result["ok"] = not result["errors"] and result["runtime_ok"]
    result["status"] = "verified" if result["ok"] else ("needs_configuration" if runtime.get("status") == "needs_configuration" else "failed")
    return result
