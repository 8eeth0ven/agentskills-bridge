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


def _load_ir(path: str, source: str):
    if source == "skill":
        return load_skill(path)
    from converter.parsers import PARSERS

    if source not in PARSERS:
        raise SystemExit(f"unsupported --from: {source} (choose from {sorted(PARSERS)})")
    return PARSERS[source](path)


def cmd_skill2agent(args) -> int:
    from converter.emitters import EMITTERS

    if args.target not in EMITTERS:
        raise SystemExit(f"unsupported --target: {args.target} (choose from {sorted(EMITTERS)})")
    ir = load_skill(args.skill_dir)
    out = Path(args.out)
    EMITTERS[args.target](ir, out)
    emitted = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    print(f"[ok] skill -> {args.target}: {out} ({len(emitted)} files)")
    for rel in emitted:
        print(f"  - {rel}")
    return 0


def cmd_agent2skill(args) -> int:
    ir = _load_ir(args.path, args.source)
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
    ir = _load_ir(args.path, source)
    payload = ir.to_json()
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentskills-bridge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

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

    p4 = sub.add_parser("wiki", help="read-only access to llm-wiki")
    p4.add_argument("wiki_cmd", choices=["list", "read", "verify"])
    p4.add_argument("chapter", nargs="?", default=None)
    p4.set_defaults(func=cmd_wiki)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
