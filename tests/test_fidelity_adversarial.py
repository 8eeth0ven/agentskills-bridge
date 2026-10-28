"""Adversarial fidelity: exact archive restoration and independent native projection.

The registry paths may use preservation capsules. The native tests deliberately import
module functions directly, so an archive cannot hide malformed native artifacts.
"""
import ast
import hashlib
import json
import random
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from converter.emitters import EMITTERS
from converter.parsers import PARSERS
from converter.ir import AgentIR, ToolSpec
from converter.skill_loader import load_skill
from converter.skill_writer import write_skill
from converter.emitters.langchain import emit_langchain
from converter.parsers.langchain import parse_langchain
from converter.emitters.crewai import emit_crewai
from converter.parsers.crewai import parse_crewai
from converter.preservation import CAPSULE_DIR, PreservationError

ENTRY = {"langchain": "agent.py", "langflow": "flow.json", "generic": "agent.json",
         "autogen": "agent.py", "n8n": "workflow.json", "mermaid-workflow": "workflow.md"}


def entry(fmt, root):
    return root / ENTRY[fmt] if fmt in ENTRY else root


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode) & 0o111)
            for p in root.rglob("*") if p.is_file() and p.relative_to(root).parts[0] != CAPSULE_DIR}


def make_skill(root):
    files = {
        "SKILL.md": b'---\r\nname: audit-skill\r\ndescription: "Audit: exact \\"quotes\\"."\r\nlicense: MIT\r\ncompatibility: python3\r\nmetadata:\r\n  vendor:\r\n    nested: [1, 2]\r\n---\r\n\r\n  No heading.  \r\n\r\nDo precisely this.\r\n',
        "references/root.md": b"# Root\r\n\r\nNon-normalized ending",
        "references/a/same.md": "# A\n\n你好 🧭\n".encode(),
        "references/b/same.md": b"# B\n\nDistinct sibling\n",
        "references/spec.json": b'{"schema":true}',
        "scripts/run.sh": b"#!/bin/sh\nexit 0\n",
        "scripts/sub/raw.bin": bytes(range(256)),
        "assets/image.bin": b"\x89PNG\r\n\x1a\n\x00\xff",
        "assets/empty": b"",
        "agents/openai.yaml": b'interface:\n  display_name: "Audit Skill"\n  default_prompt: "A: B"\ncustom_setting: keep\n',
        "LICENSE.txt": b"Fixture license\n",
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "scripts/run.sh").chmod(0o755)
    return root


class TestExactAssetArchive(unittest.TestCase):
    def test_direct_skill_roundtrip_after_source_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = make_skill(root / "src")
            expected = snapshot(src)
            ir = load_skill(src)
            shutil.rmtree(src)
            write_skill(ir, root / "back")
            self.assertEqual(snapshot(root / "back"), expected)

    def test_all_formats_restore_bytes_and_executable_bits_without_source(self):
        for fmt in EMITTERS:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = make_skill(root / "src")
                expected = snapshot(src)
                ir = load_skill(src)
                EMITTERS[fmt](ir, root / "native")
                shutil.rmtree(src)
                ir2 = PARSERS[fmt](entry(fmt, root / "native"))
                write_skill(ir2, root / "back")
                self.assertEqual(snapshot(root / "back"), expected)

    def test_all_ordered_format_pairs_restore_exact_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = make_skill(root / "src")
            expected = snapshot(src)
            initial = load_skill(src)
            shutil.rmtree(src)
            for first in EMITTERS:
                mid = root / first
                EMITTERS[first](initial, mid)
                recovered = PARSERS[first](entry(first, mid))
                for second in EMITTERS:
                    with self.subTest(first=first, second=second):
                        final = root / (first + "-" + second)
                        EMITTERS[second](recovered, final)
                        parsed = PARSERS[second](entry(second, final))
                        back = root / (first + "-" + second + "-back")
                        write_skill(parsed, back)
                        self.assertEqual(snapshot(back), expected)


class TestNativeProjection(unittest.TestCase):
    """Module calls avoid registry capsules and inspect actual emitted semantics."""
    def test_crewai_headingless_prompt(self):
        for prompt in ("Follow instructions without a heading.", "# Heading\n\nDo this.", "", "   "):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                emit_crewai(AgentIR(name="plain", description="Read this.", system_prompt=prompt), root)
                self.assertEqual(parse_crewai(root).system_prompt, prompt.strip())

    def test_external_crewai_markdown_backstory_does_not_erase_role_and_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agents.yaml").write_text('native:\n  role: Investigator\n  goal: Find the cause\n  backstory: |\n    # Biography\n    Analyst background.\n')
            ir = parse_crewai(root)
            self.assertIn("Investigator", ir.system_prompt)
            self.assertIn("Find the cause", ir.system_prompt)
            self.assertIn("Analyst background.", ir.system_prompt)

    def test_langchain_arbitrary_prompt_and_description_literals(self):
        values = ["", "  ", "simple", 'Both """ and \'\'\' plus \\n literal.',
                  'Ends with quotes ""', '\\windows\\path\\', 'NUL:\x00 Unicode:你好 🧭\n\n']
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = AgentIR(name="literal", display_name='Unsafe """ title',
                                 description=value, system_prompt=value)
                emit_langchain(source, root)
                ast.parse((root / "agent.py").read_text())
                restored = parse_langchain(root)
                self.assertEqual(restored.system_prompt, value)
                self.assertEqual(restored.description, value)

    def test_external_langchain_ordinary_literal_is_read_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.py"
            path.write_text('raise RuntimeError("must never execute")\nSYSTEM_PROMPT: str = "ordinary short string"\n')
            self.assertEqual(parse_langchain(path).system_prompt, "ordinary short string")

    def test_langchain_comments_and_dynamic_values_are_not_literal_metadata(self):
        for source in ('# SYSTEM_PROMPT = """ignored comment"""\n# AGENT_NAME = "forged"\n',
                       'SYSTEM_PROMPT = f"""dynamic {unknown}"""\n'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "native.py"
                path.write_text(source)
                ir = parse_langchain(path)
                self.assertEqual(ir.system_prompt, "")
                self.assertEqual(ir.name, "native")

    def test_langchain_large_tool_schema_and_decorator_name(self):
        schema = {"type": "object", "properties": {"item": {"type": "string", "enum": ["entry-" + str(i) for i in range(600)]}}}
        source = AgentIR(name="tool-audit", system_prompt="Tools.", tools=[
            ToolSpec(name="search-files", description='Search "quoted" entries.', input_schema=schema, side_effects=True)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emit_langchain(source, root)
            restored = parse_langchain(root)
            self.assertEqual([t.to_dict() for t in restored.tools], [t.to_dict() for t in source.tools])

    def test_langchain_distinct_names_never_overwrite_python_functions(self):
        schema = {"type": "object", "properties": {"a-b": True, "a_b": False}}
        tools = [ToolSpec(name=name, description="Description.", input_schema=schema)
                 for name in ("search-files", "search_files", "search_files_2")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emit_langchain(AgentIR(name="collisions", tools=tools), root)
            text = (root / "agent.py").read_text()
            tree = ast.parse(text)
            names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
            self.assertEqual(len(names), len(set(names)))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    args = [arg.arg for arg in node.args.args]
                    self.assertEqual(len(args), len(set(args)))
            self.assertEqual([t.to_dict() for t in parse_langchain(root).tools], [t.to_dict() for t in tools])

    def test_python_literal_deterministic_fuzz(self):
        from converter.emitters.langchain import _py_triple
        rng = random.Random(0xB21D6E)
        alphabet = ['a', '"', "'", '\\', '\n', '\r', '\x00', '\t', '你', '🧭']
        for index in range(1000):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(80)))
            with self.subTest(index=index):
                self.assertEqual(ast.literal_eval(_py_triple(value)), value)


class TestCapsuleIntegrity(unittest.TestCase):
    def test_native_changes_are_rejected_for_every_format(self):
        for fmt in EMITTERS:
            for change in ("modify", "add", "delete", "mode"):
                with self.subTest(fmt=fmt, change=change), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    ir = load_skill(make_skill(root / "src"))
                    native = root / "native"
                    EMITTERS[fmt](ir, native)
                    artifacts = sorted(p for p in native.rglob("*") if p.is_file() and p.relative_to(native).parts[0] != CAPSULE_DIR)
                    target = artifacts[0]
                    if change == "modify":
                        target.write_bytes(target.read_bytes() + b"\n")
                    elif change == "add":
                        (native / "untracked-new-file").write_bytes(b"new")
                    elif change == "delete":
                        target.unlink()
                    else:
                        target.chmod(stat.S_IMODE(target.stat().st_mode) ^ 0o100)
                    with self.assertRaises(PreservationError):
                        PARSERS[fmt](entry(fmt, native))

    def test_capsule_ir_damage_and_future_schema_are_rejected(self):
        for change in ("ir", "schema"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                EMITTERS["generic"](AgentIR(name="integrity"), root / "native")
                capsule = root / "native" / CAPSULE_DIR
                if change == "ir":
                    target = capsule / "ir.json"
                    target.write_bytes(target.read_bytes() + b"\n")
                else:
                    target = capsule / "manifest.json"
                    manifest = json.loads(target.read_bytes())
                    manifest["schema_version"] = 999
                    target.write_text(json.dumps(manifest))
                with self.assertRaises(PreservationError):
                    PARSERS["generic"](root / "native" / "agent.json")

    def test_path_traversal_is_rejected_even_with_matching_ir_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            EMITTERS["generic"](load_skill(make_skill(root / "src")), root / "native")
            capsule = root / "native" / CAPSULE_DIR
            ir_file = capsule / "ir.json"
            data = json.loads(ir_file.read_bytes())
            data["source_files"]["../../outside"] = data["source_files"].pop("SKILL.md")
            raw = json.dumps(data).encode()
            ir_file.write_bytes(raw)
            manifest_file = capsule / "manifest.json"
            manifest = json.loads(manifest_file.read_bytes())
            manifest["ir_sha256"] = hashlib.sha256(raw).hexdigest()
            manifest_file.write_text(json.dumps(manifest))
            with self.assertRaises(PreservationError):
                PARSERS["generic"](root / "native" / "agent.json")
            self.assertFalse((root / "outside").exists())

    def test_native_only_is_an_explicit_escape_hatch_after_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            EMITTERS["generic"](AgentIR(name="native"), root / "native")
            source = root / "native" / "agent.json"
            data = json.loads(source.read_bytes())
            data["system_prompt"] = "Edited native prompt."
            source.write_text(json.dumps(data))
            with self.assertRaises(PreservationError):
                PARSERS["generic"](source)
            self.assertEqual(PARSERS["generic"](source, native_only=True).system_prompt, "Edited native prompt.")


if __name__ == "__main__":
    unittest.main()
