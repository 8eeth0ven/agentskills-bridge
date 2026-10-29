"""Frozen semantic plans and generated-file contracts for AI migrations."""
from __future__ import annotations

import json
import re

from converter.preservation import safe_path


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


_STRING = {"type": "string"}
_STRINGS = {"type": "array", "items": _STRING}
PLAN_SCHEMA = _object({
    "summary": _STRING,
    "requirements": {"type": "array", "items": _object({"id": _STRING, "description": _STRING, "source_evidence": _STRING})},
    "differences": _STRINGS,
    "tools": {"type": "array", "items": _object({
        "name": _STRING, "description": _STRING, "input_schema_json": _STRING,
        "implementation_file": _STRING, "callable": _STRING,
        "source_reuse": _STRINGS, "side_effects": {"type": "boolean"},
    })},
    "workflow": {"type": "array", "items": _object({
        "id": _STRING, "description": _STRING, "depends_on": _STRINGS, "condition": _STRING,
    })},
    "acceptance": {"type": "array", "items": _object({
        "id": _STRING, "requirement_id": _STRING,
        "kind": {"type": "string", "enum": ["function", "cli_json"]},
        "module": _STRING, "callable": _STRING, "input_json": _STRING, "expected_json": _STRING,
    })},
    "blockers": {"type": "array", "items": _STRING, "description": "Use [] when source text defines the behavior. Include ONLY missing essential information that prevents implementation. Lack of existing scripts, optional memory, or a no-network requirement are not blockers."},
})
FILES_SCHEMA = _object({
    "files": {"type": "array", "items": _object({"path": _STRING, "content": _STRING})},
    "notes": _STRINGS,
})


def _unique(items: list[dict], key: str, label: str) -> set[str]:
    values = [item[key] for item in items]
    if any(not value.strip() for value in values) or len(set(values)) != len(values):
        raise ValueError(f"plan {label} identifiers must be nonempty and unique")
    return set(values)


def normalize_plan(raw: dict, context: dict) -> dict:
    """Validate evidence/coverage and freeze JSON inputs before code generation."""
    plan = json.loads(json.dumps(raw))
    requirements = _unique(plan["requirements"], "id", "requirement")
    steps = _unique(plan["workflow"], "id", "workflow")
    _unique(plan["tools"], "name", "tool")
    _unique(plan["acceptance"], "id", "acceptance")
    source = "\n".join([context["ir"].get("system_prompt", ""), context["ir"].get("description", ""),
                        *[item["content"] for item in context["files"]]])
    normalized_source = " ".join(source.split())
    for requirement in plan["requirements"]:
        evidence = " ".join(requirement["source_evidence"].split())
        if evidence not in normalized_source and evidence.strip("`\"'") in normalized_source:
            evidence = evidence.strip("`\"'")
            requirement["source_evidence"] = evidence
        if evidence and evidence not in normalized_source:
            # Several verbatim sentences may cite separate source locations.
            # Accept those only in source order; no paraphrase is accepted.
            segments = [part.strip() for part in re.split(r"\s*(?:\.{3,}|…+)\s*|(?<=[.!?。])\s+", evidence) if part.strip()]
            cursor = 0
            matched = bool(segments)
            witnessed = []
            for segment in segments:
                position = normalized_source.find(segment, cursor)
                if position < 0:
                    # Citation punctuation may terminate a quoted clause whose
                    # source continues with a semicolon. The words/operators
                    # themselves still have to occur verbatim.
                    segment = segment.rstrip(".;。；")
                    position = normalized_source.find(segment, cursor) if segment else -1
                if position < 0:
                    matched = False
                    break
                witnessed.append(segment)
                cursor = position + len(segment)
            if matched:
                requirement["source_evidence"] = " ... ".join(witnessed)
                continue
        if not evidence or evidence not in normalized_source:
            raise ValueError(f"requirement {requirement['id']} source_evidence must copy a literal excerpt from source (not a paraphrase): {evidence[:250]!r}")
    for tool in plan["tools"]:
        safe_path(tool["implementation_file"])
        if not tool["implementation_file"].endswith(".py") or not tool["callable"].isidentifier():
            raise ValueError("tool implementation must identify a Python file and callable")
        tool["input_schema"] = json.loads(tool.pop("input_schema_json"))
        if not isinstance(tool["input_schema"], dict):
            raise ValueError("tool input_schema_json must encode a JSON Schema object")
        for reuse in tool["source_reuse"]:
            safe_path(reuse)
            if reuse not in {item["path"] for item in context["inventory"]}:
                raise ValueError(f"tool {tool['name']} source_reuse includes {reuse!r}, which is not in source inventory; generated modules are not source resources, use [] when nothing is reused")
    covered = set()
    for case in plan["acceptance"]:
        safe_path(case["module"])
        if not case["module"].endswith(".py"):
            raise ValueError(f"acceptance {case['id']} module must be a relative Python file ending .py (for example bridge_tools.py or bridge_workflow.py), observed {case['module']!r}")
        if case["requirement_id"] not in requirements:
            raise ValueError("acceptance case refers to an unknown requirement")
        covered.add(case["requirement_id"])
        case["input"] = json.loads(case.pop("input_json"))
        case["expected"] = json.loads(case.pop("expected_json"))
        if case["kind"] == "function" and (not isinstance(case["input"], dict) or not case["callable"].isidentifier()):
            raise ValueError("function acceptance requires JSON keyword arguments and a callable name")
        if case["kind"] == "function" and ((case["module"] == "bridge_workflow.py" and case["callable"] == "run")
                                           or (case["module"] == "bridge_tools.py" and case["callable"] == "run_workflow")):
            if set(case["input"]) != {"request"}:
                raise ValueError("workflow acceptance calls run(request) or run_workflow(request); do not invent pricing/mock/injection keyword arguments")
    for step in plan["workflow"]:
        if set(step["depends_on"]) - steps or step["id"] in step["depends_on"]:
            raise ValueError("workflow contains an invalid dependency")
    pending = {step["id"]: set(step["depends_on"]) for step in plan["workflow"]}
    while pending:
        ready = {key for key, needs in pending.items() if not needs}
        if not ready:
            raise ValueError("workflow dependencies contain a cycle")
        pending = {key: needs - ready for key, needs in pending.items() if key not in ready}
    if not plan["blockers"]:
        if not plan["workflow"] or not any(tool["name"] == "run_workflow" and tool["implementation_file"] == "bridge_tools.py"
                                           and tool["callable"] == "run_workflow" for tool in plan["tools"]):
            raise ValueError("semantic migration requires a real workflow and a run_workflow tool")
        if not requirements or not plan["acceptance"] or requirements - covered:
            raise ValueError("every source requirement needs a frozen executable acceptance case; missing requirement ids: " + ", ".join(sorted(requirements - covered)))
        for tool in plan["tools"]:
            if tool["name"] == "run_workflow" and tool["callable"] == "run_workflow" and any(
                    case["module"] == "bridge_workflow.py" and case["callable"] == "run" for case in plan["acceptance"]):
                # The orchestrator deterministically mirrors all frozen workflow
                # cases onto this required delegation tool before generation.
                continue
            if not any(case["kind"] == "function" and case["module"] == tool["implementation_file"]
                       and case["callable"] == tool["callable"] for case in plan["acceptance"]):
                raise ValueError(f"tool {tool['name']} needs an independent function acceptance case")
        if plan["workflow"] and not any(case["module"] == "bridge_workflow.py" and case["callable"] == "run" for case in plan["acceptance"]):
            raise ValueError("workflow requires a frozen bridge_workflow.run acceptance case")
    return plan


def generated_files(raw: dict) -> list[dict]:
    """Only native product text files may be changed by the model."""
    files = raw["files"]
    if not files:
        raise ValueError("model produced no native implementation files")
    seen = set()
    for item in files:
        path = item["path"]
        rel = safe_path(path)
        if path in seen:
            raise ValueError("model returned duplicate output paths")
        seen.add(path)
        if rel.parts[0] in (".git", "tests", "evaluation") or rel.name.startswith((".env", "test_")):
            raise ValueError("model attempted to write a reserved or credential file")
        if rel.name in ("migration.json", "migration-plan.json") or rel.suffix in (".key", ".pem", ".p12", ".pfx"):
            raise ValueError("model attempted to overwrite a reserved report or credential file")
        if "\x00" in item["content"]:
            raise ValueError("generated text contains a NUL byte")
        if re.search(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b", item["content"]):
            raise ValueError("generated output contains credential-shaped material")
    return files
