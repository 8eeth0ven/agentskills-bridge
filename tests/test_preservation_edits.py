"""Independent regressions for archival bytes versus deliberately edited IR.

These assertions inspect native SKILL.md/interface/reference files, without
relying on the capsule parser to establish projection correctness.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from converter.emitters import EMITTERS
from converter.ir import ToolSpec
from converter.parsers import PARSERS
from converter.preservation import PreservationError, capture_files, package_output, read_capsule
from converter.skill_loader import load_skill
from converter.skill_writer import write_skill


class PreservationEditTests(unittest.TestCase):
    FORMATS = ("skill", "crewai-skills", "deepagents")

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "SKILL.md").write_bytes(
            b'---\r\nname: edit-test\r\ndescription: "Original description"\r\n'
            b'license: MIT\r\ncompatibility: "test fixture"\r\n'
            b'x-unknown:\r\n  nested: [one, two]\r\n'
            b'metadata: {"tools":[{"name":"old-tool","description":"old"}]}\r\n'
            b'---\r\n\r\nOriginal prompt.\r\n'
        )
        (self.source / "agents").mkdir()
        self.interface = self.source / "agents" / "a.yaml"
        self.interface.write_text(
            'interface:\n  display_name: "Original Display"\n'
            '  short_description: "Original summary"\n'
            '  default_prompt: "Original default"\n'
            '  icon_small: "./assets/icon.svg"\n'
            'dependencies:\n  tools: []\n', encoding="utf-8")
        (self.source / "references").mkdir()
        (self.source / "references" / "note.md").write_bytes(b'# Reference\r\nOriginal knowledge.\r\n')
        (self.source / "assets").mkdir()
        (self.source / "assets" / "binary.dat").write_bytes(bytes(range(256)))
        (self.source / "scripts").mkdir()
        script = self.source / "scripts" / "run.py"
        script.write_bytes(b'#!/usr/bin/env python3\nprint("fixture")\n')
        script.chmod(0o751)
        self.ir = load_skill(self.source)

    def project(self, ir, fmt, name="output"):
        out = self.root / f"{name}-{fmt}"
        if fmt == "skill":
            write_skill(ir, out)
            return out, out
        EMITTERS[fmt](ir, out)
        return out, next((out / "skills").iterdir())

    def test_unchanged_skill_projection_is_exact_without_source_directory(self):
        expected = capture_files(self.source)
        ir = deepcopy(self.ir)
        shutil.rmtree(self.source)
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                out, skill = self.project(ir, fmt)
                self.assertEqual(expected, capture_files(skill))
                self.assertEqual(ir.source_files, read_capsule(out)[0].source_files)

    def test_mapped_edits_reach_native_prompt_name_description_interface_and_reference(self):
        ir = deepcopy(self.ir)
        ir.name = "edited-name"
        ir.description = "Edited description"
        ir.system_prompt = "Edited prompt.\n"
        ir.display_name = "Edited Display"
        ir.default_prompt = "Edited default"
        ir.knowledge[0].content = "# Reference\nEdited knowledge.\n"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                out, skill = self.project(ir, fmt)
                native = load_skill(skill, native_only=True)
                for attr in ("name", "description", "system_prompt", "display_name", "default_prompt"):
                    self.assertEqual(getattr(ir, attr), getattr(native, attr), (fmt, attr))
                self.assertEqual(ir.knowledge[0].content, native.knowledge[0].content)
                self.assertEqual(ir.system_prompt, read_capsule(out)[0].system_prompt)
                if fmt != "skill":
                    self.assertEqual("edited-name", skill.name)

    def test_prompt_edit_preserves_unknown_frontmatter(self):
        ir = deepcopy(self.ir)
        ir.system_prompt = "New prompt.\n"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                native = (skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn('license: MIT', native)
                self.assertIn('compatibility: "test fixture"', native)
                self.assertIn('x-unknown:\n  nested: [one, two]', native)

    def test_interface_edits_preserve_unmapped_interface_and_dependency_fields(self):
        # Use the canonical filename to catch truncation, independently of the
        # a.yaml precedence regression in the multi-field edit test above.
        self.interface.rename(self.source / "agents" / "openai.yaml")
        ir = load_skill(self.source)
        ir.default_prompt = "Edited default"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                interface = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")
                self.assertIn('short_description: "Original summary"', interface)
                self.assertIn('icon_small: "./assets/icon.svg"', interface)
                self.assertIn('dependencies:\n  tools: []', interface)

    def test_removed_knowledge_does_not_return_to_native_projection(self):
        ir = deepcopy(self.ir)
        ir.knowledge = []
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                self.assertEqual([], load_skill(skill, native_only=True).knowledge)

    def test_edited_tool_contract_does_not_restore_old_frontmatter_contract(self):
        ir = deepcopy(self.ir)
        ir.tools = [ToolSpec(name="edited-tool", description="edited", input_schema={"type": "object"}, side_effects=True)]
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                native = load_skill(skill, native_only=True)
                self.assertEqual([t.to_dict() for t in ir.tools], [t.to_dict() for t in native.tools])

    def test_prompt_name_and_description_edits_reach_native_skill(self):
        ir = deepcopy(self.ir)
        ir.name = "edited-name"
        ir.description = "Edited description"
        ir.system_prompt = "Edited prompt.\n"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                native = load_skill(skill, native_only=True)
                self.assertEqual((ir.name, ir.description, ir.system_prompt),
                                 (native.name, native.description, native.system_prompt))

    def test_reference_content_edit_reaches_native_file(self):
        ir = deepcopy(self.ir)
        ir.knowledge[0].content = "# Reference\nEdited knowledge.\n"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                self.assertEqual(ir.knowledge[0].content.encode("utf-8"),
                                 (skill / "references" / "note.md").read_bytes())

    def test_readonly_source_file_can_be_edited_without_losing_mode(self):
        (self.source / "SKILL.md").chmod(0o444)
        ir = load_skill(self.source)
        ir.system_prompt = "Edited readonly source.\n"
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                self.assertEqual(ir.system_prompt, load_skill(skill, native_only=True).system_prompt)
                self.assertEqual(0o444, (skill / "SKILL.md").stat().st_mode & 0o777)

    def test_clearing_interface_fields_does_not_expose_later_sources(self):
        (self.source / "agents" / "b.yaml").write_text(
            'interface:\n  display_name: "Later Display"\n  default_prompt: "Later default"\n', encoding="utf-8")
        ir = load_skill(self.source)
        ir.display_name = ""
        ir.default_prompt = ""
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                _, skill = self.project(ir, fmt)
                native = load_skill(skill, native_only=True)
                self.assertEqual("", native.display_name)
                self.assertEqual("", native.default_prompt)

    def test_existing_output_directory_is_preserved(self):
        out = self.root / "occupied"
        out.mkdir()
        marker = out / "existing.txt"
        marker.write_bytes(b"must survive")
        with self.assertRaises(PreservationError):
            EMITTERS["generic"](self.ir, out)
        self.assertEqual(b"must survive", marker.read_bytes())
        self.assertEqual(["existing.txt"], [p.name for p in out.iterdir()])

    def test_output_symlink_is_rejected_without_touching_target(self):
        target = self.root / "target"
        target.mkdir()
        marker = target / "existing.txt"
        marker.write_bytes(b"must survive")
        out = self.root / "output-link"
        out.symlink_to(target, target_is_directory=True)
        with self.assertRaises(PreservationError):
            EMITTERS["generic"](self.ir, out)
        self.assertTrue(out.is_symlink())
        self.assertEqual(b"must survive", marker.read_bytes())
        self.assertEqual(["existing.txt"], [p.name for p in target.iterdir()])

    def test_failed_staging_does_not_remove_existing_empty_output(self):
        out = self.root / "empty-output"
        out.mkdir()

        def fail_after_write(ir, staged):
            (staged / "partial.txt").write_bytes(b"partial")
            raise RuntimeError("simulated emitter failure")

        with self.assertRaisesRegex(RuntimeError, "simulated emitter failure"):
            package_output(self.ir, out, "generic", fail_after_write)
        self.assertTrue(out.is_dir())
        self.assertEqual([], list(out.iterdir()))
        self.assertEqual([], list(self.root.glob(".bridge-stage-*")))

    def test_capsule_format_mismatch_is_rejected(self):
        out = self.root / "generic"
        EMITTERS["generic"](self.ir, out)
        with self.assertRaisesRegex(PreservationError, "requested"):
            PARSERS["langchain"](out)

    def test_added_native_symlink_is_rejected(self):
        out = self.root / "generic"
        EMITTERS["generic"](self.ir, out)
        target = self.root / "external.txt"
        target.write_bytes(b"outside package")
        (out / "linked.txt").symlink_to(target)
        with self.assertRaises(PreservationError):
            PARSERS["generic"](out)
        self.assertEqual(b"outside package", target.read_bytes())

    def test_nonexistent_entry_does_not_resolve_to_parent_capsule(self):
        out = self.root / "langchain"
        EMITTERS["langchain"](self.ir, out)
        with self.assertRaises(FileNotFoundError):
            PARSERS["langchain"](out / "typo.py")


if __name__ == "__main__":
    unittest.main()
