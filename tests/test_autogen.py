"""autogen(AutoGen/AG2,第 9 个 target)emitter/parser 的条件化测试。

模块可能尚未就绪:import 放 try/except,缺失时 skipTest(与 test_convert.py
风格一致)。零第三方依赖:语法检查用 ast.parse(py_compile 同级强度,不落
缓存文件)。
"""

import ast
import tempfile
import unittest
from pathlib import Path

from converter.ir import AgentIR, KnowledgeDoc, ToolSpec

try:
    from converter.emitters.autogen import emit_autogen
except Exception:  # pragma: no cover - 并行线程未落盘
    emit_autogen = None

try:
    from converter.parsers.autogen import parse_autogen
except Exception:  # pragma: no cover
    parse_autogen = None

try:
    from converter.skill_loader import load_skill
    from converter.skill_writer import write_skill
except Exception:  # pragma: no cover
    load_skill = None
    write_skill = None


def make_demo_ir() -> AgentIR:
    """标准测试用 IR:2 篇知识 + 1 个工具 + 含引号/换行的提示词。"""
    return AgentIR(
        name="demo-autogen-agent",
        display_name="Demo Autogen Agent",
        description="A demo agent converted to AutoGen AG2.",
        system_prompt=(
            "# Demo\n\n"
            "You are the demo agent. Do things \"carefully\".\n"
            "Paths like C:\\tools\\x and escapes \\n survive the roundtrip."
        ),
        default_prompt="Run the demo",
        tools=[ToolSpec(name="echo", description="echo input back to the caller.")],
        knowledge=[
            # write_skill 会给 references 补尾换行,内容以 \n 结尾才能严格相等
            KnowledgeDoc(filename="guide.md", title="Guide", content="# Guide\ncontent\n"),
            KnowledgeDoc(filename="notes.md", title="Notes", content="# Notes\nmore content\n"),
        ],
        metadata={"note": "unittest"},
    )


class TestEmitAutogen(unittest.TestCase):
    def _emit(self, ir, out):
        if emit_autogen is None:
            self.skipTest("converter.emitters.autogen not available yet")
        return emit_autogen(ir, out)

    def test_emit_structure_and_syntax(self):
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._emit(ir, out)
            agent_py = out / "agent.py"
            self.assertTrue(agent_py.is_file(), "agent.py 应存在")
            text = agent_py.read_text(encoding="utf-8")

            # AG2 新 API 与自描述常量
            self.assertIn("from autogen_agentchat.agents import AssistantAgent", text)
            self.assertIn("from autogen_ext.models.openai import OpenAIChatCompletionClient", text)
            self.assertIn("AssistantAgent(", text)
            self.assertIn("OpenAIChatCompletionClient(model=DEFAULT_MODEL)", text)
            self.assertIn("ConversableAgent", text, "应含旧 API 兼容注释块")
            self.assertIn("def build_agent(model_client=None):", text, "工厂模式,顶层零实例化")
            self.assertIn(f'AGENT_NAME = "{ir.name}"', text)
            self.assertIn("SYSTEM_MESSAGE = ", text)
            # SYSTEM_MESSAGE 全文:反斜杠会被 _py_triple 双写,用无转义片段断言
            self.assertIn("You are the demo agent. Do things \"carefully\".", text)
            self.assertIn("# Demo", text)

            # py_compile 同级强度(ast.parse,不落缓存)
            try:
                ast.parse(text, filename=str(agent_py))
            except SyntaxError as exc:
                self.fail(f"agent.py 语法错误: {exc}")

            # 产物三件套 + knowledge 2 篇
            self.assertTrue((out / "requirements.txt").is_file(), "requirements.txt 应存在")
            req = (out / "requirements.txt").read_text(encoding="utf-8")
            self.assertIn("autogen-agentchat", req)
            self.assertIn("autogen-ext[openai]", req)
            self.assertTrue((out / "README.md").is_file(), "README.md 应存在")
            kbs = sorted(p.name for p in (out / "knowledge").glob("*.md"))
            self.assertEqual(kbs, ["guide.md", "notes.md"], "knowledge 应恰有 2 篇")

    def test_registry(self):
        from converter.emitters import EMITTERS
        from converter.ir import TARGET_FORMATS
        from converter.parsers import PARSERS

        self.assertIn("autogen", EMITTERS, "EMITTERS 应注册 autogen")
        self.assertIn("autogen", PARSERS, "PARSERS 应注册 autogen")
        self.assertIn("autogen", TARGET_FORMATS, "TARGET_FORMATS 应含 autogen")


class TestParseAutogen(unittest.TestCase):
    def _parse(self, path):
        if parse_autogen is None:
            self.skipTest("converter.parsers.autogen not available yet")
        return parse_autogen(path)

    def test_emit_then_parse_roundtrip(self):
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "agent"
            emit_autogen(ir, out)
            back = self._parse(out)  # 目录形态:自动定位 agent.py
            self.assertEqual(back.name, ir.name, "name 应回读一致")
            self.assertEqual(back.system_prompt, ir.system_prompt,
                             "system_prompt 应经 literal_eval 还原后一致(含转义)")
            self.assertEqual(back.metadata.get("source_format"), "autogen")
            by_name = {k.filename: k.content for k in back.knowledge}
            self.assertEqual(by_name, {"guide.md": "# Guide\ncontent\n",
                                       "notes.md": "# Notes\nmore content\n"})
            self.assertIn("demo agent", back.description.lower())

    def test_ctor_fallback_name_and_inline_system_message(self):
        """无自描述常量时:AssistantAgent/ConversableAgent 调用参数兜底。"""
        src = (
            "from autogen_agentchat.agents import AssistantAgent\n"
            "\n"
            'agent = AssistantAgent(\n'
            '    name="Legacy Coder Agent",\n'
            '    system_message="You are a legacy coder agent that writes code for the demo and ships it.",\n'
            ")\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            py = Path(tmp) / "legacy_agent.py"
            py.write_text(src, encoding="utf-8")
            back = self._parse(py)
            self.assertEqual(back.name, "legacy-coder-agent")
            self.assertIn("legacy coder agent", back.system_prompt)

    def test_tools_extraction(self):
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "agent"
            emit_autogen(ir, out)
            back = self._parse(out)
            self.assertEqual([t.name for t in back.tools], ["echo"])
            self.assertIn("echo input", back.tools[0].description)


class TestAutogenFullChain(unittest.TestCase):
    """emit → parse → write_skill → load_skill 的 name/knowledge/content 一致。"""

    def test_full_chain(self):
        if emit_autogen is None or parse_autogen is None:
            self.skipTest("autogen emitter/parser not available yet")
        if load_skill is None or write_skill is None:
            self.skipTest("skill_loader/skill_writer not available yet")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agent_dir = tmp_path / "autogen"
            emit_autogen(ir, agent_dir)
            ir_mid = parse_autogen(agent_dir)
            skill_dir = tmp_path / "skill-back"
            write_skill(ir_mid, skill_dir)
            ir_out = load_skill(skill_dir)

            self.assertEqual(ir_out.name, ir.name)
            by_name_in = {k.filename: k.content for k in ir.knowledge}
            by_name_out = {k.filename: k.content for k in ir_out.knowledge}
            self.assertEqual(by_name_in, by_name_out, "knowledge 内容应逐篇一致")
            self.assertEqual(sorted(by_name_out), ["guide.md", "notes.md"])
            self.assertTrue(
                ((skill_dir / "references" / "guide.md")).is_file(),
                "references/guide.md 应落盘",
            )


if __name__ == "__main__":
    unittest.main()
