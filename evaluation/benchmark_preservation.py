#!/usr/bin/env python3
"""Source-independent preservation benchmark; no models or framework installs.

This measures archival recovery and AgentIR transport, not native execution
equivalence. Every source directory is deleted before the first conversion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from converter.emitters import EMITTERS
from converter.ir import TaskStep, ToolSpec
from converter.parsers import PARSERS
from converter.skill_loader import load_skill
from converter.skill_writer import write_skill

ENTRY = {
    "autogen": "agent.py", "langchain": "agent.py", "langflow": "flow.json",
    "generic": "agent.json", "n8n": "workflow.json", "mermaid-workflow": "workflow.md",
}
FORMATS = tuple(sorted(set(EMITTERS) & set(PARSERS)))


def contract_tools():
    return [ToolSpec(
        "verify_payload", 'Verify "nested" JSON schema; no side effects.',
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object", "required": ["mode", "payload"],
            "additionalProperties": False,
            "properties": {
                "mode": {"enum": ["fast", "strict"]},
                "payload": {"oneOf": [
                    {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    {"type": "array", "items": {"type": "integer", "minimum": 0}},
                ]},
            },
        }, False,
    ), ToolSpec("publish_result", "Explicit side effect", {"type": "object"}, True)]


def make_fixture(root: Path, variant: str = "bundle"):
    """Public fixture reused by comparison harnesses. Returns source AgentIR."""
    root.mkdir(parents=True)
    skill = (
        "---\r\nname: preservation-probe\r\n"
        'description: "Preserve source files, contract and topology."\r\n'
        "license: MIT\r\ncompatibility: Python 3.10+\r\n"
        "allowed-tools: Read Bash(python:*)\r\n"
        "metadata:\r\n  author: preservation-benchmark\r\n  version: '01'\r\n"
        "x-extension:\r\n  quoted: '# literal : value'\r\n---\r\n\r\n"
        "# Preserve 精确字节 🧪\r\n\r\n"
        "1. Inspect the input.\r\n2. Verify the evidence.\r\n"
        "\r\n```python\r\ntext = '\"\"\" and ---'\r\n```\r\n\r\n"
        "See [nested reference](references/deep/事实.md).  \r\n\r\n"
    ).encode("utf-8")
    if variant == "contracts":
        # Contracts belong to the original source, before the loader captures
        # its byte snapshot. Editing mapped IR fields after loading is a
        # different test: correct native projection must then change the source.
        source_metadata = {
            "author": "preservation-benchmark", "version": "01",
            "tools": [tool.to_dict() for tool in contract_tools()],
            "graph_edges": [["inspect", "accept"], ["inspect", "reject"]],
            "custom_extension": {"nested": [True, None, 0, "01", "中文"]},
        }
        skill = skill.replace(
            b"metadata:\r\n  author: preservation-benchmark\r\n  version: '01'\r\n",
            ("metadata: " + json.dumps(source_metadata, ensure_ascii=False, separators=(",", ":")) + "\r\n").encode(),
            1,
        )
    files = {"SKILL.md": skill}
    if variant != "minimal":
        files.update({
            "references/guide.md": b"# Guide\r\nKeep CRLF and trailing spaces.  \r\n",
            "references/deep/事实.md": "# 事实\n无末尾换行".encode(),
            "references/schema.json": b'{"empty":[],"null":null}\n',
            "scripts/run.sh": b"#!/bin/sh\nprintf '%s\\n' preserved\n",
            "scripts/deep/check.py": b"# never executed by this benchmark\r\nprint('ok')\r\n",
            "assets/payload.bin": bytes(range(256)) * 17,
            "assets/empty.dat": b"",
            "templates/config.toml": b'[probe]\nvalue = "001"\n',
            "agents/openai.yaml": b'interface:\n  display_name: "Preservation Probe"\n  default_prompt: "Verify exact recovery."\n',
            "LICENSE.txt": b"MIT fixture, authored for this benchmark.\n",
        })
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if rel == "scripts/run.sh" else 0o644)
    ir = load_skill(root)
    if variant == "contracts":
        expected = [tool.to_dict() for tool in contract_tools()]
        assert [tool.to_dict() for tool in ir.tools] == expected, "source tool contract was not parsed"
        # Task objects have no direct native skill field; separately exercise
        # transport of additional IR state without editing source-mapped fields.
        ir.tasks = [
            TaskStep("inspect", "Inspect bytes", "Evidence", "inspector"),
            TaskStep("accept", "Accept verified payload", "Approved", "reviewer"),
            TaskStep("reject", "Reject invalid payload", "Rejected", "reviewer"),
        ]
    return ir


def tree_manifest(root: Path):
    return {
        p.relative_to(root).as_posix(): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(p.stat().st_mode), "bytes": p.stat().st_size,
        }
        for p in sorted(root.rglob("*")) if p.is_file()
        and ".agentskills-bridge" not in p.relative_to(root).parts
    }


def ir_manifest(ir):
    """Compare the public semantic model, excluding source locations only."""
    obj = ir.to_dict()
    obj.get("metadata", {}).pop("source_path", None)
    for doc in obj.get("knowledge", []):
        doc.pop("source_path", None)
    return obj


def differences(left, right):
    return sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))


def parse_output(fmt, directory):
    return PARSERS[fmt](directory / ENTRY[fmt] if fmt in ENTRY else directory)


def integrity_probes(ir, root):
    """Require explicit preservation errors, not arbitrary native parse failures."""
    try:
        from converter.preservation import PreservationError
    except ImportError:
        return {"supported": False, "passed": 0, "total": 66, "reason": "No preservation capsule implementation"}
    rows = []
    for fmt in FORMATS:
        for mutation in ("native-edit", "native-delete", "native-add", "native-mode", "ir-edit", "format-mismatch"):
            package = root / f"{fmt}-{mutation}"
            try:
                EMITTERS[fmt](copy.deepcopy(ir), package)
                capsule = package / ".agentskills-bridge"
                manifest = json.loads((capsule / "manifest.json").read_text())
                native = package / sorted(manifest["artifacts"])[0]
                if mutation == "native-edit":
                    native.write_bytes(native.read_bytes() + b"\nchanged by integrity probe\n")
                elif mutation == "native-delete":
                    native.unlink()
                elif mutation == "native-add":
                    (package / "unexpected-file.txt").write_text("unexpected\n")
                elif mutation == "native-mode":
                    native.chmod(stat.S_IMODE(native.stat().st_mode) ^ stat.S_IXUSR)
                elif mutation == "ir-edit":
                    payload = capsule / "ir.json"
                    payload.write_bytes(payload.read_bytes() + b" ")
                else:
                    manifest["format"] = "incorrect-format"
                    (capsule / "manifest.json").write_text(json.dumps(manifest))
                try:
                    parse_output(fmt, package)
                    row = {"format": fmt, "mutation": mutation, "ok": False, "error": "Accepted damaged package"}
                except PreservationError as exc:
                    row = {"format": fmt, "mutation": mutation, "ok": True, "detected": str(exc)}
            except Exception as exc:
                row = {"format": fmt, "mutation": mutation, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            shutil.rmtree(package, ignore_errors=True)
    return {"supported": True, "passed": sum(r["ok"] for r in rows), "total": len(rows), "runs": rows}


def one_chain(ir, expected_ir, expected_tree, root, chain):
    current = copy.deepcopy(ir)
    ir_failures = []
    for index, fmt in enumerate(chain):
        emitted = root / f"hop-{index:03d}-{fmt}"
        EMITTERS[fmt](current, emitted)
        current = parse_output(fmt, emitted)
        changed = differences(expected_ir, ir_manifest(current))
        if changed:
            ir_failures.append({"hop": index + 1, "format": fmt, "changed_fields": changed})
    recovered = root / "recovered"
    write_skill(current, recovered)
    got_tree = tree_manifest(recovered)
    missing = sorted(set(expected_tree) - set(got_tree))
    changed_files = sorted(p for p in set(expected_tree) & set(got_tree) if expected_tree[p] != got_tree[p])
    extra = sorted(set(got_tree) - set(expected_tree))
    return {
        "chain": list(chain), "ok": not (ir_failures or missing or changed_files or extra),
        "ir_failures": ir_failures, "missing_files": missing,
        "changed_files": changed_files, "extra_files": extra,
    }


def run(cycles=10, variants=("minimal", "bundle", "contracts")):
    report = {
        "benchmark": "source-independent-preservation-v1",
        "measures": "AgentIR field equality plus exact file paths, SHA-256, byte counts and POSIX modes",
        "scope": "Archival/capsule preservation; native projection and execution equivalence are separate.",
        "formats": list(FORMATS), "cycles": cycles, "variants": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "implementation_files": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted([ROOT / "cli.py", *ROOT.glob("converter/**/*.py")])
        },
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    for variant in variants:
        with tempfile.TemporaryDirectory(prefix="bridge-preservation-") as tmp:
            workspace = Path(tmp)
            source = workspace / "source"
            ir = make_fixture(source, variant)
            original_tree, original_ir = tree_manifest(source), ir_manifest(ir)
            shutil.rmtree(source)
            result = {
                "source_deleted_before_emit": not source.exists(),
                "source_files": len(original_tree),
                "source_bytes": sum(x["bytes"] for x in original_tree.values()),
                "matrix": [],
            }
            for first in FORMATS:
                for second in FORMATS:
                    chain_root = workspace / f"pair-{first}-{second}"
                    try:
                        row = one_chain(ir, original_ir, original_tree, chain_root, (first, second))
                    except Exception as exc:
                        row = {"chain": [first, second], "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    result["matrix"].append(row)
                    shutil.rmtree(chain_root, ignore_errors=True)
            try:
                result["long_chain"] = one_chain(ir, original_ir, original_tree, workspace / "long", FORMATS * cycles)
            except Exception as exc:
                result["long_chain"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            result["matrix_passed"] = sum(row["ok"] for row in result["matrix"])
            result["matrix_total"] = len(result["matrix"])
            report["variants"][variant] = result
            if variant == "contracts":
                report["integrity"] = integrity_probes(ir, workspace / "integrity")
    report["summary"] = {
        "matrix_passed": sum(v["matrix_passed"] for v in report["variants"].values()),
        "matrix_total": sum(v["matrix_total"] for v in report["variants"].values()),
        "long_chains_passed": sum(v["long_chain"]["ok"] for v in report["variants"].values()),
        "long_chain_hops_each": len(FORMATS) * cycles,
        "integrity_passed": report.get("integrity", {}).get("passed", 0),
        "integrity_total": report.get("integrity", {}).get("total", 0),
    }
    report["ok"] = (report["summary"]["matrix_passed"] == report["summary"]["matrix_total"]
                    and report["summary"]["long_chains_passed"] == len(variants)
                    and report["summary"]["integrity_passed"] == report["summary"]["integrity_total"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation/results/preservation.json")
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("--cycles must be positive")
    report = run(args.cycles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"report: {args.out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
