"""converter emitters/parsers/skill_loader/skill_writer 的条件化测试。

converter 模块可能尚未就绪:所有 import 放 try/except,模块缺失时对应用例
skipTest,保证部分模块缺失时整个套件不崩(见 INTERFACE.md)。
"""

import importlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from converter.ir import AgentIR, KnowledgeDoc, ToolSpec, parse_frontmatter

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SKILL = ROOT / "examples" / "agent-fullcycle-engineering"


def _resolve(module_names, attr_names):
    """依次尝试从候选模块取候选函数名,返回第一个可调用对象,找不到返回 None。"""
    for module_name in module_names:
        try:
            mod = importlib.import_module(module_name)
        except Exception:  # ModuleNotFoundError 或模块自身 import 失败
            continue
        for attr in attr_names:
            fn = getattr(mod, attr, None)
            if callable(fn):
                return fn
    return None


def make_demo_ir() -> AgentIR:
    """标准测试用 IR(与任务规格一致)。"""
    return AgentIR(
        name="demo-agent",
        display_name="Demo Agent",
        description="A demo",
        system_prompt="# Demo\n\nDo things.",
        default_prompt="Run the demo",
        tools=[ToolSpec(name="echo", description="echo input")],
        knowledge=[
            KnowledgeDoc(filename="guide.md", title="Guide", content="# Guide\ncontent")
        ],
        metadata={"note": "unittest"},
    )


EMITTER_CANDIDATES = {
    "crewai": (("converter.emitters.crewai",), ("emit_crewai",)),
    "langchain": (("converter.emitters.langchain",), ("emit_langchain",)),
    "langflow": (("converter.emitters.langflow",), ("emit_langflow",)),
    "openai": (
        ("converter.emitters.openai_agents", "converter.emitters.openai"),
        ("emit_openai_agents", "emit_openai"),
    ),
    "generic": (("converter.emitters.generic",), ("emit_generic",)),
}


def _get_emitter(target):
    """返回 (emit_fn, unittest.skipTest 工厂);模块缺失时 fn 为 None。"""
    modules, funcs = EMITTER_CANDIDATES[target]
    return _resolve(modules, funcs)


class TestEmitCrewai(unittest.TestCase):
    def test_emit(self):
        fn = _get_emitter("crewai")
        if fn is None:
            self.skipTest("emitter for target 'crewai' not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(make_demo_ir(), out)
            agents_yaml = out / "config" / "agents.yaml"
            tasks_yaml = out / "config" / "tasks.yaml"
            self.assertTrue(agents_yaml.is_file(), "config/agents.yaml 应存在")
            self.assertTrue(tasks_yaml.is_file(), "config/tasks.yaml 应存在")
            text = agents_yaml.read_text(encoding="utf-8")
            self.assertIn("role:", text)
            self.assertIn("backstory:", text)
            self.assertIn("Demo Agent", text)
            kbs = list((out / "knowledge").glob("*.md"))
            self.assertTrue(any(k.name == "guide.md" for k in kbs), "knowledge/guide.md 应存在")


class TestEmitLangchain(unittest.TestCase):
    def test_emit(self):
        fn = _get_emitter("langchain")
        if fn is None:
            self.skipTest("emitter for target 'langchain' not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(make_demo_ir(), out)
            agent_py = out / "agent.py"
            self.assertTrue(agent_py.is_file(), "agent.py 应存在")
            text = agent_py.read_text(encoding="utf-8")
            self.assertIn("SYSTEM_PROMPT", text)
            self.assertIn("guide.md", text)
            self.assertTrue((out / "requirements.txt").is_file())
            self.assertTrue((out / "README.md").is_file())


class TestEmitLangflow(unittest.TestCase):
    def test_emit(self):
        fn = _get_emitter("langflow")
        if fn is None:
            self.skipTest("emitter for target 'langflow' not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(make_demo_ir(), out)
            flow = out / "flow.json"
            self.assertTrue(flow.is_file(), "flow.json 应存在")
            raw = flow.read_text(encoding="utf-8")
            self.assertIn("Do things.", raw, "flow.json 应嵌入 system_prompt 文本")
            data = json.loads(raw)
            nodes = data["data"]["nodes"]
            self.assertGreaterEqual(len(nodes), 4, "至少 ChatInput→Prompt→LLM→ChatOutput 4 节点")
            # 兼容两种导出布局:旧版外层 type 直接是组件名;
            # v1.1.2+ 外层 type 为 genericNode、组件名在 data.type。
            types = {n.get("type") for n in nodes}
            types |= {(n.get("data") or {}).get("type") for n in nodes}
            self.assertIn("ChatInput", types)
            self.assertIn("ChatOutput", types)


class TestEmitOpenai(unittest.TestCase):
    def test_emit(self):
        fn = _get_emitter("openai")
        if fn is None:
            self.skipTest("emitter for target 'openai' not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(make_demo_ir(), out)
            openai_yaml = out / "agents" / "openai.yaml"
            instructions = out / "instructions.md"
            self.assertTrue(openai_yaml.is_file(), "agents/openai.yaml 应存在")
            self.assertTrue(instructions.is_file(), "instructions.md 应存在")
            self.assertIn("Demo Agent", openai_yaml.read_text(encoding="utf-8"))
            self.assertIn("Do things.", instructions.read_text(encoding="utf-8"))


class TestEmitGeneric(unittest.TestCase):
    def test_emit(self):
        fn = _get_emitter("generic")
        if fn is None:
            self.skipTest("emitter for target 'generic' not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ir = make_demo_ir()
            fn(ir, out)
            agent_json = out / "agent.json"
            self.assertTrue(agent_json.is_file(), "agent.json 应存在")
            restored = AgentIR.from_dict(json.loads(agent_json.read_text(encoding="utf-8")))
            self.assertEqual(restored, ir)
            self.assertTrue(any(
                k.name == "guide.md" for k in (out / "knowledge").glob("*.md")
            ), "knowledge/guide.md 应存在")


class TestNewEmitters(unittest.TestCase):
    """新 target 三件套:crewai-skills / deepagents / claude-subagent(存在才测)。

    EMITTERS 注册表可能尚未收录(并行线程进行中):import 失败或缺键一律
    skipTest,不算失败。
    """

    def _get_new_emitter(self, key):
        try:
            from converter.emitters import EMITTERS
        except Exception:
            self.skipTest("converter.emitters.EMITTERS not available yet")
        fn = EMITTERS.get(key)
        if fn is None:
            self.skipTest(f"emitter for target '{key}' not available yet")
        return fn

    def test_crewai_skills(self):
        fn = self._get_new_emitter("crewai-skills")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(ir, out)
            skill_md = out / "skills" / ir.name / "SKILL.md"
            self.assertTrue(skill_md.is_file(), "skills/<name>/SKILL.md 应存在")
            agents_yaml = out / "config" / "agents.yaml"
            self.assertTrue(agents_yaml.is_file(), "config/agents.yaml 应存在")
            self.assertIn("skills:", agents_yaml.read_text(encoding="utf-8"))

    def test_deepagents(self):
        fn = self._get_new_emitter("deepagents")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(ir, out)
            agent_py = out / "agent.py"
            self.assertTrue(agent_py.is_file(), "agent.py 应存在")
            self.assertIn("create_deep_agent", agent_py.read_text(encoding="utf-8"))
            self.assertTrue(
                (out / "skills" / ir.name / "SKILL.md").is_file(),
                "skills/<name>/SKILL.md 应存在",
            )

    def test_claude_subagent(self):
        fn = self._get_new_emitter("claude-subagent")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(ir, out)
            agent_md = out / ".claude" / "agents" / f"{ir.name}.md"
            self.assertTrue(agent_md.is_file(), ".claude/agents/<name>.md 应存在")
            text = agent_md.read_text(encoding="utf-8")
            self.assertEqual(text.splitlines()[0], "---", "首行应为 frontmatter 分隔符 ---")
            self.assertIn("Do things.", text, "正文应含 system_prompt 标志词")


class TestLangflowV112(unittest.TestCase):
    """Langflow v1.1.2+ 导出布局:genericNode 外层 + data.type 组件名 + œ 转义 handle。

    调研结论(langflow 仓库/文档实测):外层 type 为 genericNode,组件名在
    data.type(ChatInput/Prompt/LanguageModelComponent/ChatOutput);edge 的
    sourceHandle/targetHandle 是 JSON 字符串且引号被替换为 œ(U+0153)。
    emitter 仍为旧布局时 skip(并行线程改写中)。
    """

    SYSTEM_PROMPT = (
        "You are the demo agent. Follow this system prompt carefully for the "
        "langflow v1.1.2 roundtrip check. Do things."
    )

    def test_v112_layout_and_parse_roundtrip(self):
        fn = _get_emitter("langflow")
        if fn is None:
            self.skipTest("emitter for target 'langflow' not available yet")
        parse_langflow = _resolve(
            ("converter.parsers.langflow", "converter.parsers"), ("parse_langflow",)
        )
        ir = make_demo_ir()
        ir.system_prompt = self.SYSTEM_PROMPT
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fn(ir, out)
            flow_file = out / "flow.json"
            self.assertTrue(flow_file.is_file(), "flow.json 应存在")
            data = json.loads(flow_file.read_text(encoding="utf-8"))["data"]
            nodes = [n for n in data.get("nodes", []) if isinstance(n, dict)]
            self.assertTrue(nodes, "flow 应含节点")
            if not any(n.get("type") == "genericNode" for n in nodes):
                self.skipTest("langflow v1.1.2 布局 emitter 尚未落盘(仍为旧版节点)")

            allowed = {"ChatInput", "Prompt", "LanguageModelComponent", "ChatOutput"}
            for node in nodes:
                self.assertEqual(
                    node.get("type"), "genericNode", "外层 type 应为 genericNode"
                )
                inner = (node.get("data") or {}).get("type")
                self.assertIn(inner, allowed, f"data.type 应 ∈ {sorted(allowed)}")

            edges = [e for e in data.get("edges", []) if isinstance(e, dict)]
            oe_handles = [
                e["sourceHandle"]
                for e in edges
                if isinstance(e.get("sourceHandle"), str) and "œ" in e["sourceHandle"]
            ]
            self.assertTrue(oe_handles, "至少一条边的 sourceHandle 应含 œ 分隔符")
            self.assertTrue(
                any(self._json_after_oe_swap(h) for h in oe_handles),
                "sourceHandle 的 œ 还原为引号后应为合法 JSON",
            )

            if parse_langflow is None:
                self.skipTest("parser parse_langflow not available yet")
            ir2 = parse_langflow(flow_file)
            self.assertEqual(
                ir2.system_prompt,
                self.SYSTEM_PROMPT,
                "parse_langflow 读回的 system_prompt 应与源 IR 一致",
            )

    @staticmethod
    def _json_after_oe_swap(handle: str) -> bool:
        try:
            json.loads(handle.replace("œ", '"'))
        except (ValueError, TypeError):
            return False
        return True


# ---------------------------------------------------------------- parsers

CREWAI_AGENTS_YAML = """\
demo-agent:
  name: demo-agent
  role: You are a demo agent that completes demo tasks.
  goal: Finish the demo task end to end.
  backstory: A demo agent built for converter tests.
  verbose: false
"""

CREWAI_TASKS_YAML = """\
demo-task:
  description: Run the demo task.
  expected_output: A short demo result.
  agent: demo-agent
"""

LANGFLOW_FLOW = {
    "id": "test-flow",
    "name": "Demo Flow",
    "data": {
        "nodes": [
            {
                "id": "chat-input-1",
                "type": "ChatInput",
                "position": {"x": 0, "y": 0},
                "data": {"template": {"message": {"type": "str", "value": ""}}},
            },
            {
                "id": "prompt-1",
                "type": "Prompt",
                "position": {"x": 200, "y": 0},
                "data": {
                    "template": {
                        "system_prompt": {
                            "type": "str",
                            "value": "You are the demo agent. Do things.",
                        },
                        "prompt": {"type": "str", "value": "{message}"},
                    }
                },
            },
            {
                "id": "model-1",
                "type": "OpenAIModel",
                "position": {"x": 400, "y": 0},
                "data": {
                    "template": {
                        "model_name": {"type": "str", "value": "gpt-4o-mini"}
                    }
                },
            },
            {
                "id": "chat-output-1",
                "type": "ChatOutput",
                "position": {"x": 600, "y": 0},
                "data": {"template": {"message": {"type": "str", "value": ""}}},
            },
        ],
        "edges": [
            {"source": "chat-input-1", "sourceHandle": "out", "target": "prompt-1", "targetHandle": "in"},
            {"source": "prompt-1", "sourceHandle": "out", "target": "agent-1", "targetHandle": "in"},
            {"source": "agent-1", "sourceHandle": "out", "target": "chat-output-1", "targetHandle": "in"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    },
}


class TestParseCrewai(unittest.TestCase):
    def test_parse(self):
        fn = _resolve(("converter.parsers.crewai", "converter.parsers"), ("parse_crewai",))
        if fn is None:
            self.skipTest("parser parse_crewai not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            cfg.mkdir()
            (cfg / "agents.yaml").write_text(CREWAI_AGENTS_YAML, encoding="utf-8")
            (cfg / "tasks.yaml").write_text(CREWAI_TASKS_YAML, encoding="utf-8")
            ir = fn(cfg)
            self.assertIsInstance(ir, AgentIR)
            self.assertTrue(ir.name, "name 应非空")
            self.assertEqual(ir.metadata.get("source_format"), "crewai")
            self.assertIn("## Role", ir.system_prompt)
            self.assertIn("## Goal", ir.system_prompt)
            self.assertIn("## Backstory", ir.system_prompt)
            self.assertIn("demo agent", ir.system_prompt.lower())
            self.assertIn("A demo agent built for converter tests.", ir.system_prompt)


class TestParseLangflow(unittest.TestCase):
    def test_parse(self):
        fn = _resolve(("converter.parsers.langflow", "converter.parsers"), ("parse_langflow",))
        if fn is None:
            self.skipTest("parser parse_langflow not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            flow = Path(tmp) / "flow.json"
            flow.write_text(json.dumps(LANGFLOW_FLOW), encoding="utf-8")
            ir = fn(flow)
            self.assertIsInstance(ir, AgentIR)
            self.assertEqual(ir.metadata.get("source_format"), "langflow")
            self.assertIn("demo agent", ir.system_prompt.lower())
            self.assertIn("Do things.", ir.system_prompt)


# ------------------------------------------------------- skill roundtrip

SYNTH_SKILL_MD = (
    "---\n"
    "name: synth-skill\n"
    "description: A synthetic skill used when the real example is absent.\n"
    "---\n"
    "\n"
    "# Synth Skill\n"
    "\n"
    "Do synthetic things.\n"
)


def _synth_skill_dir(tmp: Path) -> Path:
    src = tmp / "synth-skill"
    (src / "references").mkdir(parents=True)
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text(SYNTH_SKILL_MD, encoding="utf-8")
    (src / "references" / "alpha.md").write_text("# Alpha\n\nalpha content\n", encoding="utf-8")
    (src / "references" / "beta.md").write_text("# Beta\n\nbeta content\n", encoding="utf-8")
    (src / "scripts" / "echo.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    return src


class TestSkillRoundtrip(unittest.TestCase):
    """skill → load_skill → write_skill → load_skill 字段一致。"""

    def _fns(self):
        load_skill = _resolve(("converter.skill_loader",), ("load_skill",))
        write_skill = _resolve(("converter.skill_writer",), ("write_skill",))
        if load_skill is None or write_skill is None:
            self.skipTest("skill_loader/skill_writer not available yet")
        return load_skill, write_skill

    def test_roundtrip(self):
        load_skill, write_skill = self._fns()
        source = EXAMPLE_SKILL if (EXAMPLE_SKILL / "SKILL.md").is_file() else None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            if source is None:
                source = _synth_skill_dir(tmp_path)
            ir1 = load_skill(source)
            out = tmp_path / "out-skill"
            write_skill(ir1, out)
            ir2 = load_skill(out)
            self.assertEqual(ir2.name, ir1.name)
            self.assertEqual(ir2.description, ir1.description)
            self.assertEqual(ir2.system_prompt, ir1.system_prompt)
            self.assertEqual(len(ir2.knowledge), len(ir1.knowledge))
            by_name_1 = {k.filename: k.content for k in ir1.knowledge}
            by_name_2 = {k.filename: k.content for k in ir2.knowledge}
            self.assertEqual(by_name_1, by_name_2)

    def test_copy_scripts_from(self):
        load_skill, write_skill = self._fns()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = _synth_skill_dir(tmp_path)
            ir = load_skill(src)
            out = tmp_path / "out-with-scripts"
            write_skill(ir, out, copy_scripts_from=src)
            copied = out / "scripts" / "echo.sh"
            self.assertTrue(copied.is_file(), "scripts/echo.sh 应被拷贝到新目录")
            self.assertEqual(
                copied.read_text(encoding="utf-8"),
                (src / "scripts" / "echo.sh").read_text(encoding="utf-8"),
            )

    def test_full_chain_knowledge_roundtrip(self):
        """skill -> crewai -> skill 全链路:knowledge 必须原样回流 references/。"""
        load_skill, write_skill = self._fns()
        try:
            from converter.emitters import EMITTERS
            from converter.parsers import PARSERS
        except Exception:
            self.skipTest("emitters/parsers not available yet")
        source = EXAMPLE_SKILL if (EXAMPLE_SKILL / "SKILL.md").is_file() else None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            if source is None:
                source = _synth_skill_dir(tmp_path)
            ir1 = load_skill(source)
            by_name_1 = {k.filename: k.content for k in ir1.knowledge}

            for fmt in ("crewai", "langflow"):
                agent_dir = tmp_path / f"agent-{fmt}"
                EMITTERS[fmt](ir1, agent_dir)
                entry = (
                    agent_dir / "flow.json" if fmt == "langflow" else agent_dir
                )
                ir2 = PARSERS[fmt](entry)
                by_name_2 = {k.filename: k.content for k in ir2.knowledge}
                self.assertEqual(
                    by_name_1, by_name_2, f"{fmt} 全链路 knowledge 回流不完整"
                )
                back = tmp_path / f"back-{fmt}"
                write_skill(ir2, back)
                refs = sorted(p.name for p in (back / "references").glob("*.md"))
                self.assertEqual(refs, sorted(by_name_1), f"{fmt} 反向 references 缺文件")


class TestSkillWriterValidation(unittest.TestCase):
    """write_skill 的 agentskills.io 规范化:name 合法 kebab ≤64、description ≤1024。"""

    _KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def _write_skill(self):
        fn = _resolve(("converter.skill_writer",), ("write_skill",))
        if fn is None:
            self.skipTest("skill_writer not available yet")
        return fn

    def _write_and_read_meta(self, ir) -> dict:
        write_skill = self._write_skill()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "skill-out"
            write_skill(ir, out)
            skill_md = out / "SKILL.md"
            self.assertTrue(skill_md.is_file(), "SKILL.md 应存在")
            meta, _body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            return meta

    def test_name_slugified_and_description_truncated(self):
        meta = self._write_and_read_meta(AgentIR(
            name="Demo_Agent",
            display_name="X",
            description="d" * 1200,
            system_prompt="Body.",
        ))
        name = meta.get("name", "")
        self.assertTrue(
            self._KEBAB_RE.match(name),
            f"frontmatter name 应为合法 kebab-case: {name!r}",
        )
        self.assertLessEqual(len(name), 64, "name 应 ≤64 字符")
        desc = meta.get("description", "")
        self.assertTrue(desc, "description 应非空")
        self.assertLessEqual(len(desc), 1024, "description 应 ≤1024 字符")

    def test_name_over_64_truncated_kebab(self):
        meta = self._write_and_read_meta(AgentIR(
            name="a" * 40 + "-middle-" + "b" * 40,  # 88 字符,slugify 原样保留
            description="ok",
            system_prompt="Body.",
        ))
        name = meta.get("name", "")
        self.assertTrue(self._KEBAB_RE.match(name), f"截断后应保持 kebab: {name!r}")
        self.assertLessEqual(len(name), 64)

    def test_description_blank_fallback(self):
        meta = self._write_and_read_meta(AgentIR(
            name="demo-agent",
            display_name="X",
            description="   \n\t  ",
            system_prompt="Body.",
        ))
        desc = meta.get("description", "")
        self.assertTrue(desc.strip(), "空白 description 应有非空兜底")


class TestScriptsMigration(unittest.TestCase):
    """scripts/ 在 skill 目录形态 target(crewai-skills/deepagents)必须原样迁移。

    该缺陷由能力对照矩阵钉出:早期版本只迁 SKILL.md + references,anthropics
    docx skill 的 59 个脚本文件全部丢失。
    """

    def test_scripts_copied_to_skill_dir_targets(self):
        try:
            from converter.emitters import EMITTERS
            from converter.skill_loader import load_skill
        except Exception:
            self.skipTest("emitters/skill_loader not available yet")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "src-skill"
            (src / "scripts" / "office").mkdir(parents=True)
            (src / "SKILL.md").write_text(
                "---\nname: scripted-skill\ndescription: A skill with scripts.\n---\n\nBody.\n",
                encoding="utf-8",
            )
            (src / "scripts" / "run.py").write_text("print('run')\n", encoding="utf-8")
            (src / "scripts" / "office" / "util.py").write_text("X = 1\n", encoding="utf-8")
            ir = load_skill(src)
            self.assertEqual(len(ir.scripts), 2, "load_skill 应登记 2 个 scripts 相对路径")
            for fmt in ("crewai-skills", "deepagents"):
                if fmt not in EMITTERS:
                    continue
                out = tmp_path / f"out-{fmt}"
                EMITTERS[fmt](ir, out)
                skill_dir = next((out / "skills").iterdir())
                copied = sorted(
                    str(p.relative_to(skill_dir)) for p in (skill_dir / "scripts").rglob("*") if p.is_file()
                )
                self.assertEqual(copied, ["scripts/office/util.py", "scripts/run.py"], f"{fmt} 应原样迁移 scripts/")
                content = (skill_dir / "scripts" / "run.py").read_text(encoding="utf-8")
                self.assertEqual(content, "print('run')\n", f"{fmt} 迁移内容应逐字节一致")

    def test_scripts_skipped_when_source_missing(self):
        """无 source_path(内存 IR)时安静跳过,不抛错。"""
        from converter.emitters.crewai_skills import _write_scripts
        from converter.ir import AgentIR

        ir = AgentIR(name="x", scripts=["scripts/run.py"])  # 无 metadata.source_path
        with tempfile.TemporaryDirectory() as tmp:
            copied = _write_scripts(ir, Path(tmp))
        self.assertEqual(copied, [])


if __name__ == "__main__":
    unittest.main()
