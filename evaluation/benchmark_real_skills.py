#!/usr/bin/env python3
"""Verify source-independent recovery of three pinned official document skills.

Only tracked regular files from the pinned Git revision are read. No upstream
scripts, model calls, framework imports, or Git hooks are executed. Source text
and binary assets stay in temporary directories; reports contain hashes only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.benchmark_preservation import FORMATS, ir_manifest, one_chain, tree_manifest
from converter.skill_loader import load_skill

UPSTREAM = "https://github.com/anthropics/skills"
REVISION = "dbd4588f9e1033efb41dad4bef2f7947c8993d44"
SKILLS = ("docx", "pdf", "pptx")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def materialize_pinned_skills(repo: Path, destination: Path):
    """Export selected fixed Git trees, ignoring checkout edits/untracked files."""
    archive = git(repo, "archive", REVISION, *(f"skills/{name}" for name in SKILLS))
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("upstream archive contains an unsafe path")
            target = destination.joinpath(*rel.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = stream.extractfile(member)
                if source is None:
                    raise ValueError("upstream archive omitted a regular file")
                target.write_bytes(source.read())
                target.chmod(member.mode & 0o777)
            else:
                raise ValueError("upstream archive contains a nonregular file")


def scrub(value, workspace: Path):
    """Reports must not expose local source locations, including on failures."""
    if isinstance(value, str):
        return value.replace(str(workspace), "<workspace>").replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
    if isinstance(value, list):
        return [scrub(item, workspace) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item, workspace) for key, item in value.items()}
    return value


def run(source_repo: Path, workspace: Path, cycles: int):
    report = {
        "benchmark": "official-source-independent-preservation-v1",
        "source": {
            "repository": UPSTREAM,
            "revision": REVISION,
            "selected_paths": [f"skills/{name}" for name in SKILLS],
            "license_scope": "These document skills are source-available under their upstream LICENSE.txt; no upstream content is vendored in this report.",
        },
        "scope": "Archival/capsule preservation. Does not establish native framework execution equivalence or model behavior.",
        "formats": list(FORMATS), "cycles": cycles,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "implementation_files": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted([ROOT / "cli.py", *ROOT.glob("converter/**/*.py")])
        },
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_sha256": hashlib.sha256((ROOT / "evaluation/benchmark_preservation.py").read_bytes()).hexdigest(),
        "skills": {},
    }
    source_tree = workspace / "upstream"
    materialize_pinned_skills(source_repo, source_tree)
    for name in SKILLS:
        source = source_tree / "skills" / name
        original_tree = tree_manifest(source)
        ir = load_skill(source)
        original_ir = ir_manifest(ir)
        shutil.rmtree(source)
        skill = {
            "upstream_path": f"skills/{name}",
            "upstream_url": f"{UPSTREAM}/tree/{REVISION}/skills/{name}",
            "source_deleted_before_emit": not source.exists(),
            "source_files": len(original_tree),
            "source_bytes": sum(entry["bytes"] for entry in original_tree.values()),
            "source_manifest": original_tree,
            "single_hop": [],
        }
        for fmt in FORMATS:
            chain_root = workspace / f"{name}-single-{fmt}"
            try:
                row = one_chain(ir, original_ir, original_tree, chain_root, (fmt,))
            except Exception as exc:
                row = {"chain": [fmt], "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            skill["single_hop"].append(row)
            shutil.rmtree(chain_root, ignore_errors=True)
        chain_root = workspace / f"{name}-long"
        try:
            skill["long_chain"] = one_chain(ir, original_ir, original_tree, chain_root, FORMATS * cycles)
        except Exception as exc:
            skill["long_chain"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        shutil.rmtree(chain_root, ignore_errors=True)
        skill["single_hop_passed"] = sum(row["ok"] for row in skill["single_hop"])
        report["skills"][name] = skill
    report["summary"] = {
        "single_hop_passed": sum(s["single_hop_passed"] for s in report["skills"].values()),
        "single_hop_total": len(SKILLS) * len(FORMATS),
        "long_chains_passed": sum(s["long_chain"]["ok"] for s in report["skills"].values()),
        "long_chain_hops_each": len(FORMATS) * cycles,
        "source_files_total": sum(s["source_files"] for s in report["skills"].values()),
        "source_bytes_total": sum(s["source_bytes"] for s in report["skills"].values()),
    }
    report["ok"] = (report["summary"]["single_hop_passed"] == report["summary"]["single_hop_total"]
                    and report["summary"]["long_chains_passed"] == len(SKILLS))
    return scrub(report, workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="Optional local upstream Git repository containing the pinned revision (working tree is not used)")
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation/preservation/real-skills.json")
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("--cycles must be positive")
    with tempfile.TemporaryDirectory(prefix="bridge-official-skills-") as tmp:
        workspace = Path(tmp)
        repo = args.source_root
        if repo is None:
            repo = workspace / "repository"
            repo.mkdir()
            git(repo, "init", "--quiet")
            git(repo, "remote", "add", "origin", UPSTREAM + ".git")
            git(repo, "-c", "core.hooksPath=/dev/null", "fetch", "--quiet", "--depth", "1", "origin", REVISION)
        report = run(repo.resolve(), workspace, args.cycles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"report: {args.out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
