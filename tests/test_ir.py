"""converter/ir.py 的无依赖单测(无条件可跑,不依赖 emitters/parsers)。"""

import unittest

from converter.ir import (
    AgentIR,
    KnowledgeDoc,
    TaskStep,
    ToolSpec,
    parse_frontmatter,
    slugify,
)


def _full_ir() -> AgentIR:
    """构造一个覆盖全部字段的 AgentIR。"""
    return AgentIR(
        name="demo-agent",
        display_name="Demo Agent",
        description="A demo agent for tests",
        system_prompt="# Demo\n\nDo things.",
        default_prompt="Run the demo",
        tools=[
            ToolSpec(
                name="echo",
                description="echo input",
                input_schema={"type": "object"},
                side_effects=False,
            )
        ],
        knowledge=[
            KnowledgeDoc(
                filename="guide.md",
                title="Guide",
                content="# Guide\ncontent",
                source_path="/tmp/guide.md",
            )
        ],
        tasks=[
            TaskStep(
                name="run",
                description="run it",
                expected_output="a result",
                agent="demo-agent",
            )
        ],
        scripts=["scripts/echo.sh"],
        metadata={"source_format": "skill", "lang": "zh"},
    )


class TestAgentIRSerialization(unittest.TestCase):
    """to_dict / from_dict / to_json / from_json roundtrip。"""

    def test_to_dict_keys_complete(self):
        d = _full_ir().to_dict()
        self.assertEqual(
            set(d.keys()),
            {
                "name",
                "display_name",
                "description",
                "system_prompt",
                "default_prompt",
                "tools",
                "knowledge",
                "tasks",
                "scripts",
                "metadata",
            },
        )

    def test_dict_roundtrip_field_equal(self):
        ir = _full_ir()
        restored = AgentIR.from_dict(ir.to_dict())
        self.assertEqual(restored, ir)
        self.assertEqual(restored.tools[0].name, "echo")
        self.assertEqual(restored.knowledge[0].filename, "guide.md")
        self.assertEqual(restored.tasks[0].agent, "demo-agent")
        self.assertEqual(restored.scripts, ["scripts/echo.sh"])
        self.assertEqual(restored.metadata, {"source_format": "skill", "lang": "zh"})

    def test_json_roundtrip_field_equal(self):
        ir = _full_ir()
        text = ir.to_json()
        restored = AgentIR.from_json(text)
        self.assertEqual(restored, ir)
        # to_json 输出必须是合法 JSON 且可再次反序列化
        self.assertIn('"name": "demo-agent"', text)

    def test_from_dict_tolerates_missing_optional(self):
        restored = AgentIR.from_dict({"name": "bare"})
        self.assertEqual(restored.name, "bare")
        self.assertEqual(restored.tools, [])
        self.assertEqual(restored.knowledge, [])
        self.assertEqual(restored.tasks, [])
        self.assertEqual(restored.metadata, {})


class TestSlugify(unittest.TestCase):
    def test_expected_slug(self):
        self.assertEqual(slugify("Agent Fullcycle Engineering"), "agent-fullcycle-engineering")

    def test_special_chars_and_case(self):
        self.assertEqual(slugify("  Hello, World!  "), "hello-world")
        self.assertEqual(slugify("MiXeD_Case 123"), "mixed-case-123")

    def test_fallback_when_empty(self):
        self.assertEqual(slugify("!!!"), "agent")
        self.assertEqual(slugify("", fallback="x"), "x")


class TestParseFrontmatter(unittest.TestCase):
    SKILL_LIKE = (
        "---\n"
        "name: demo-skill\n"
        "description: This is a long multi word description explaining when to "
        "use the skill and what it does for the agent at runtime.\n"
        "---\n"
        "\n"
        "# Demo Skill\n"
        "\n"
        "Body content here.\n"
    )

    def test_splits_meta_and_body(self):
        meta, body = parse_frontmatter(self.SKILL_LIKE)
        self.assertEqual(meta.get("name"), "demo-skill")
        self.assertEqual(
            meta.get("description"),
            "This is a long multi word description explaining when to use "
            "the skill and what it does for the agent at runtime.",
        )
        self.assertTrue(body.startswith("# Demo Skill"))
        self.assertIn("Body content here.", body)
        self.assertNotIn("---", body)
        self.assertNotIn("name:", body)

    def test_no_frontmatter_returns_all_text(self):
        text = "# Just a heading\n\nno frontmatter here.\n"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_unterminated_frontmatter_returns_all_text(self):
        text = "---\nname: broken\nno closing fence\n"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)


class TestDerivedHelpers(unittest.TestCase):
    def test_title_from_kebab_name(self):
        ir = AgentIR(name="agent-fullcycle-engineering")
        self.assertEqual(ir.title(), "Agent Fullcycle Engineering")

    def test_title_prefers_display_name(self):
        ir = AgentIR(name="demo-agent", display_name="Custom Name")
        self.assertEqual(ir.title(), "Custom Name")

    def test_backstory_short_prompt_unchanged(self):
        prompt = "# Demo\n\nShort enough prompt."
        ir = AgentIR(name="demo", system_prompt=prompt)
        self.assertEqual(ir.backstory(max_chars=1200), prompt.strip())

    def test_backstory_truncates_at_paragraph_boundary(self):
        prompt = "A" * 80 + "\n\n" + "B" * 200
        ir = AgentIR(name="demo", system_prompt=prompt)
        story = ir.backstory(max_chars=100)
        # 短于 max_chars,且以省略号结尾
        self.assertLess(len(story), 100)
        self.assertTrue(story.endswith("\n..."))
        # 在段落边界结束:只保留第一段
        self.assertTrue(story.startswith("A" * 80))
        self.assertNotIn("B", story)
        self.assertLess(len(story), len(prompt))

    def test_backstory_default_limit_truncates_long_prompt(self):
        ir = AgentIR(name="demo", system_prompt="C" * 5000)
        story = ir.backstory()
        self.assertLess(len(story), 5000)
        self.assertTrue(story.endswith("..."))


if __name__ == "__main__":
    unittest.main()
