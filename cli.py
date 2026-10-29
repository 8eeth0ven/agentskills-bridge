#!/usr/bin/env python3
"""agentskills-bridge CLI。

用法:
  python3 cli.py skill2agent <skill_dir> --target crewai|langchain|langflow|openai|generic --out <dir>
  python3 cli.py agent2skill <path> --from crewai|langchain|langflow|generic --out <dir> [--scripts-from <dir>]
  python3 cli.py ir <path> [--from skill|crewai|langchain|langflow|generic] [--out <file>]
  python3 cli.py wiki list|read <chapter>|verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from converter.ir import TARGET_FORMATS  # noqa: E402
from converter.skill_loader import load_skill  # noqa: E402
from converter.skill_writer import write_skill  # noqa: E402
from converter.wiki import Wiki  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
WIKI_ROOT = PROJECT_ROOT / "llm-wiki"


def _load_ir(path: str, source: str, native_only: bool = False):
    if source == "skill":
        return load_skill(path, native_only=native_only)
    from converter.parsers import PARSERS

    if source not in PARSERS:
        raise SystemExit(f"unsupported --from: {source} (choose from {sorted(PARSERS)})")
    return PARSERS[source](path, native_only=native_only)


def cmd_skill2agent(args) -> int:
    from converter.emitters import EMITTERS

    if args.target not in EMITTERS:
        raise SystemExit(f"unsupported --target: {args.target} (choose from {sorted(EMITTERS)})")
    ir = load_skill(args.skill_dir, native_only=args.native_only)
    out = Path(args.out)
    EMITTERS[args.target](ir, out)
    emitted = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    print(f"[ok] skill -> {args.target}: {out} ({len(emitted)} files)")
    for rel in emitted:
        print(f"  - {rel}")
    return 0


def cmd_agent2skill(args) -> int:
    ir = _load_ir(args.path, args.source, args.native_only)
    out = write_skill(ir, args.out, copy_scripts_from=args.scripts_from)
    emitted = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    print(f"[ok] {args.source} -> skill: {out} ({len(emitted)} files)")
    for rel in emitted:
        print(f"  - {rel}")
    return 0


def cmd_ir(args) -> int:
    source = args.source
    if source is None:
        p = Path(args.path)
        if (p / "SKILL.md").is_file() or p.name == "SKILL.md":
            source = "skill"
        elif p.suffix == ".py":
            source = "langchain"
        elif p.suffix == ".json":
            source = "generic"
        else:
            source = "crewai"
    ir = _load_ir(args.path, source, args.native_only)
    from converter.preservation import portable_ir
    payload = portable_ir(ir).to_json()
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"[ok] IR written to {args.out}")
    else:
        print(payload)
    return 0


def cmd_wiki(args) -> int:
    wiki = Wiki(WIKI_ROOT)
    if args.wiki_cmd == "list":
        for p in wiki.list_chapters():
            rel = p.relative_to(wiki.root)
            first = ""
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    first = line[2:].strip()
                    break
            print(f"{rel}\t{first}")
        return 0
    if args.wiki_cmd == "read":
        print(wiki.read(args.chapter))
        return 0
    if args.wiki_cmd == "verify":
        ok, errors = wiki.verify()
        if ok:
            print(f"[ok] llm-wiki intact ({len(wiki.list_chapters())} chapters verified)")
            return 0
        for err in errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1
    raise SystemExit("unknown wiki subcommand")


def cmd_convert(args) -> int:
    """万能转换:任意形态(skill/agent/workflow)→ 任意 target,一步完成。

    内部即 PARSERS[source] → AgentIR → EMITTERS[target],与两步等价;
    skill 输入走 load_skill。--scripts-from 仅在产出 skill 类目录时生效。
    """
    ir = _load_ir(args.path, args.source, args.native_only)
    from converter.emitters import EMITTERS

    if args.target not in EMITTERS and args.target != "skill":
        raise SystemExit(f"unsupported --target: {args.target} (choose from {sorted(EMITTERS)})")
    out = write_skill(ir, args.out) if args.target == "skill" else EMITTERS[args.target](ir, args.out)
    emitted = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    print(f"[ok] {args.source} -> {args.target}: {out} ({len(emitted)} files)")
    for rel in emitted:
        print(f"  - {rel}")
    return 0


def cmd_verify(args) -> int:
    """Verify the native file set, capsule IR, source bytes and file modes."""
    from converter.preservation import find_capsule, read_capsule, PreservationError
    root = find_capsule(args.path)
    if root is None:
        raise PreservationError("no preservation capsule found")
    ir, manifest = read_capsule(root)
    result = {"ok": True, "format": manifest["format"],
              "native_files": len(manifest["artifacts"]),
              "source_files": len(ir.source_files),
              "tools": len(ir.tools), "tasks": len(ir.tasks)}
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"[ok] {result['format']}: {result['native_files']} native files verified; "
              f"{result['source_files']} source files, {result['tools']} tools, {result['tasks']} tasks preserved")
    return 0


def cmd_migrate(args) -> int:
    """Run real model analysis, native code generation and execution repair."""
    import json
    from converter.ai_context import Redactor
    from converter.ai_migration import MigrationFailed, migrate
    from converter.ai_provider import ModelClient

    if args.report:
        report_path = Path(args.report).resolve()
        output_path = Path(args.out).resolve()
        if report_path == output_path or output_path in report_path.parents:
            raise ValueError("--report must be outside --out; the project already contains migration.json")
        source_path = Path(args.path).resolve()
        if report_path == source_path or (source_path.is_dir() and source_path in report_path.parents and report_path.exists()):
            raise ValueError("--report cannot overwrite a source input file")
    external = json.loads(Path(args.acceptance).read_text(encoding="utf-8")) if args.acceptance else None
    if args.acceptance and not isinstance(external, list):
        raise ValueError("external acceptance must be a JSON array")
    runtime = json.loads(args.runtime_command) if args.runtime_command else None
    if runtime is not None and (not isinstance(runtime, list) or not runtime or any(not isinstance(item, str) for item in runtime)):
        raise ValueError("--runtime-command must be a JSON array of argv strings")
    client = ModelClient(provider=args.provider, model=args.model, base_url=args.base_url,
                         api_key_env=args.api_key_env, timeout=args.model_timeout,
                         max_output_tokens=args.max_output_tokens, thinking=args.thinking)
    ir = _load_ir(args.path, args.source, args.native_only)
    redactor = Redactor(PROJECT_ROOT, args.path, args.out)

    def progress(event):
        print("[ai] " + json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)

    try:
        report = migrate(ir, args.target, args.out, client, execute=args.execute,
                         max_repairs=args.max_repairs, python_executable=args.python,
                         timeout=args.runtime_timeout, runtime_command=runtime,
                         acceptance=external, acceptance_path=args.acceptance, context_chars=args.context_chars,
                         keep_failed=args.keep_failed, progress=progress,
                         source_root=((Path(args.path) if Path(args.path).is_dir() else Path(args.path).parent)
                                      if args.source != "skill" else None))
    except MigrationFailed as exc:
        report = exc.report
        if args.report:
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(redactor.scrub(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[not verified] " + report["status"], file=sys.stderr)
        for blocker in report.get("blockers", []):
            print("  - " + redactor.text(str(blocker)), file=sys.stderr)
        if report.get("attempts"):
            for error in report["attempts"][-1]["validation"].get("errors", []):
                print("  - " + redactor.text(str(error))[:4000], file=sys.stderr)
        return 1
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redactor.scrub(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[verified] {args.source} -> {args.target}: {args.out}; "
          f"{len(report['attempts'])} implementation attempts, {report['model_calls']} model calls")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentskills-bridge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p0 = sub.add_parser("convert", help="any form -> any target in one step (skill/agent/workflow)")
    p0.add_argument("path")
    p0.add_argument(
        "--from",
        dest="source",
        required=True,
        choices=["skill", "crewai", "crewai-skills", "deepagents", "langchain",
                 "langflow", "openai", "claude-subagent", "generic", "autogen",
                 "n8n", "mermaid-workflow"],
    )
    p0.add_argument("--target", required=True, choices=sorted((*TARGET_FORMATS, "skill")))
    p0.add_argument("--out", required=True)
    p0.set_defaults(func=cmd_convert)

    p1 = sub.add_parser("skill2agent", help="convert a skill dir to a framework agent")
    p1.add_argument("skill_dir")
    p1.add_argument("--target", required=True, choices=sorted(TARGET_FORMATS))
    p1.add_argument("--out", required=True)
    p1.set_defaults(func=cmd_skill2agent)

    p2 = sub.add_parser("agent2skill", help="convert a framework agent back to a skill")
    p2.add_argument("path")
    p2.add_argument(
        "--from",
        dest="source",
        required=True,
        choices=[
            "crewai", "crewai-skills", "deepagents", "langchain",
            "langflow", "openai", "claude-subagent", "generic", "autogen",
            "n8n", "mermaid-workflow",
        ],
    )
    p2.add_argument("--out", required=True)
    p2.add_argument("--scripts-from", default=None, help="optional skill dir whose scripts/ will be copied in")
    p2.set_defaults(func=cmd_agent2skill)

    p3 = sub.add_parser("ir", help="dump the AgentIR of a skill or agent")
    p3.add_argument("path")
    p3.add_argument("--from", dest="source", default=None)
    p3.add_argument("--out", default=None)
    p3.set_defaults(func=cmd_ir)

    for command in (p0, p1, p2, p3):
        command.add_argument("--native-only", action="store_true",
                             help="explicitly import native files, ignoring the preservation capsule")

    p5 = sub.add_parser("verify", help="verify a preservation capsule and all native artifacts")
    p5.add_argument("path")
    p5.add_argument("--json", action="store_true", help="machine-readable verification summary")
    p5.set_defaults(func=cmd_verify)

    p4 = sub.add_parser("wiki", help="read-only access to llm-wiki")
    p4.add_argument("wiki_cmd", choices=["list", "read", "verify"])
    p4.add_argument("chapter", nargs="?", default=None)
    p4.set_defaults(func=cmd_wiki)

    p6 = sub.add_parser("migrate", help="AI semantic migration: analyze, generate, execute and repair")
    p6.add_argument("path")
    p6.add_argument("--from", dest="source", default="skill", choices=sorted(("skill", *TARGET_FORMATS)))
    p6.add_argument("--target", required=True, choices=sorted(("skill", *TARGET_FORMATS)))
    p6.add_argument("--out", required=True)
    p6.add_argument("--provider", default="auto", choices=("auto", "anthropic", "openai", "openai-chat"))
    p6.add_argument("--model", help="explicit model; otherwise use MIGRATION_MODEL or provider model environment")
    p6.add_argument("--base-url", help="optional provider endpoint; credentials are read only from environment")
    p6.add_argument("--api-key-env", help="name of the process environment variable containing the credential")
    p6.add_argument("--execute", action="store_true", help="run generated code for behavioral and real native-runtime verification")
    p6.add_argument("--python", default=sys.executable, help="runtime Python interpreter with target framework installed")
    p6.add_argument("--max-repairs", type=int, default=3)
    p6.add_argument("--model-timeout", type=float, default=120)
    p6.add_argument("--runtime-timeout", type=float, default=30)
    p6.add_argument("--max-output-tokens", type=int, default=16000)
    p6.add_argument("--thinking", choices=("disabled",), help="optionally disable extended thinking on compatible Anthropic endpoints")
    p6.add_argument("--context-chars", type=int, default=500000)
    p6.add_argument("--acceptance", help="JSON file of additional frozen cases, withheld from initial generation")
    p6.add_argument("--runtime-command", help="explicit native-host verification argv, encoded as a JSON array")
    p6.add_argument("--report", help="optional redacted JSON report, including on a failed migration")
    p6.add_argument("--keep-failed", action="store_true", help="retain unverified/failed generated project for inspection")
    p6.add_argument("--native-only", action="store_true", help="use native source definitions instead of an existing capsule")
    p6.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
