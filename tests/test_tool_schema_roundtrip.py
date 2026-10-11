"""工具 input_schema / side_effects 的 emit→parse 往返测试(全格式)。

上轮缺点清单第 4 项:此前仅 generic 完整保留 tools schema;本批在
@tool / async def stub 的 docstring 里落 `schema: {单行 JSON}` 与
`side-effects: true|false` 元数据行(emitters/langchain._tool_docstring),
parse 侧按行正则 + json.loads 还原(parsers/langchain._tool_meta_from_docstring,
autogen 同构复用)。

本批消灭能力矩阵最后一批 ❌:其余六链统一走"自描述扩展键携带、解析端
优先还原"(与 x-source-skill.systemPrompt 同构):
    - skill / crewai-skills / deepagents:SKILL.md frontmatter 的
      metadata 行携带 tools 键(skill_writer._frontmatter_metadata,
      loader 端还原),修复 agent→skill 反向 tools 被静默丢弃的缺陷;
    - openai / n8n:x-source-skill 段加 tools 键(JSON 流式序列);
    - claude-subagent:tools 白名单后加 x-tools: 单行 JSON 数组扩展键。

deepagents parser 复用 langchain 的 _extract_tools 合并 agent.py 工具;
skills/*/SKILL.md 的 metadata 行是工具 schema 的另一来源(emit 侧
agent.py 不含 @tool stub,工具留给 skills/ 运行时)。

覆盖:
    1. emit → py_compile → parse:input_schema 字典级相等(不只 name)、
       side_effects 布尔回读、description 首段语义不变;
    2. schema 含反斜杠/引号等需转义字符时仍精确还原;
    3. 无 schema 行的手写源码:保持 name-only 现状(input_schema == {});
    4. roundtrip emit → parse → emit 二次生成逐字节一致(idempotent);
    5. 六条非 Python 源码链(openai/n8n/claude-subagent/crewai-skills/
       deepagents/skill)各一用例:带 schema 工具经扩展键完整还原。
"""

import py_compile
import tempfile
import unittest
from pathlib import Path

from converter.ir import AgentIR, ToolSpec

try:
    from converter.emitters.autogen import emit_autogen
except Exception:  # pragma: no cover - 并行线程未落盘
    emit_autogen = None

try:
    from converter.emitters.langchain import emit_langchain
except Exception:  # pragma: no cover
    emit_langchain = None

try:
    from converter.parsers.autogen import parse_autogen
except Exception:  # pragma: no cover
    parse_autogen = None

try:
    from converter.parsers.deepagents import parse_deepagents
except Exception:  # pragma: no cover
    parse_deepagents = None

try:
    from converter.parsers.langchain import parse_langchain
except Exception:  # pragma: no cover
    parse_langchain = None

try:
    from converter.emitters.openai_agents import emit_openai_agents
except Exception:  # pragma: no cover
    emit_openai_agents = None

try:
    from converter.parsers.openai import parse_openai
except Exception:  # pragma: no cover
    parse_openai = None

try:
    from converter.emitters.n8n import emit_n8n
    from converter.emitters import n8n as _n8n_emitter
    if _n8n_emitter.WorkflowIR is None:  # converter.wir 未落盘
        emit_n8n = None
except Exception:  # pragma: no cover
    emit_n8n = None

try:
    from converter.parsers.n8n import parse_n8n
except Exception:  # pragma: no cover
    parse_n8n = None

try:
    from converter.emitters.claude_subagent import emit_claude_subagent
except Exception:  # pragma: no cover
    emit_claude_subagent = None

try:
    from converter.parsers.claude_subagent import parse_claude_subagent
except Exception:  # pragma: no cover
    parse_claude_subagent = None

try:
    from converter.emitters.crewai_skills import emit_crewai_skills
except Exception:  # pragma: no cover
    emit_crewai_skills = None

try:
    from converter.parsers.crewai_skills import parse_crewai_skills
except Exception:  # pragma: no cover
    parse_crewai_skills = None

try:
    from converter.emitters.deepagents import emit_deepagents
except Exception:  # pragma: no cover
    emit_deepagents = None

try:
    from converter.skill_writer import write_skill
except Exception:  # pragma: no cover
    write_skill = None

try:
    from converter.skill_loader import load_skill
except Exception:  # pragma: no cover
    load_skill = None


FETCH_URL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "timeout": {"type": "integer"},
    },
    "required": ["url"],
}

# 含反斜杠/引号/嵌套结构:考验 json.dumps → 三引号 docstring →
# _literal_eval → json.loads 的三重转义链。
WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": 'path like C:\\tools and "quotes"'},
        "data": {"type": "string"},
    },
    "required": ["path", "data"],
}


def make_schema_ir() -> AgentIR:
    """标准 schema 往返用 IR:带 schema 工具 ×2(side_effects 真/假)+ 无 schema 工具 ×1。"""
    return AgentIR(
        name="schema-roundtrip-agent",
        description="Schema roundtrip agent.",
        system_prompt="You are the schema roundtrip agent. Be exact.",
        tools=[
            ToolSpec(
                name="fetch_url",
                description="Fetch a URL",
                input_schema=FETCH_URL_SCHEMA,
                side_effects=False,
            ),
            ToolSpec(
                name="write_file",
                description="Write a file",
                input_schema=WRITE_FILE_SCHEMA,
                side_effects=True,
            ),
            ToolSpec(name="echo", description="echo input back to the caller."),
        ],
    )


def make_single_tool_ir() -> AgentIR:
    """六条非 Python 源码链用 IR:单个带 schema 的工具(side_effects=True,
    非 Null 默认值才能证明布尔回读真实生效)。"""
    return AgentIR(
        name="schema-tool-agent",
        description="Single tool schema roundtrip agent.",
        system_prompt="Route every request through the one tool. Be exact.",
        tools=[
            ToolSpec(
                name="fetch_url",
                description="Fetch a URL",
                input_schema=FETCH_URL_SCHEMA,
                side_effects=True,
            ),
        ],
    )


def _py_compile_ok(case: unittest.TestCase, py_file: Path) -> None:
    """py_compile 生成代码(编译缓存落临时目录,失败即 fail)。"""
    cfile = py_file.parent / f"{py_file.stem}.pyc"
    try:
        py_compile.compile(str(py_file), cfile=str(cfile), doraise=True)
    except py_compile.PyCompileError as exc:
        case.fail(f"{py_file} 编译失败: {exc}")


class _RoundtripMixin:
    """emit → parse 的 schema 往返断言,langchain/autogen 共用。"""

    fmt: str = ""

    def _emit(self, ir, out):
        raise NotImplementedError

    def _parse(self, path):
        raise NotImplementedError

    def test_schema_roundtrip(self):
        ir = make_schema_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / self.fmt / "agent"
            self._emit(ir, out)
            agent_py = out / "agent.py"
            self.assertTrue(agent_py.is_file(), "agent.py 应存在")
            _py_compile_ok(self, agent_py)

            back = self._parse(out)
            self.assertEqual([t.name for t in back.tools], ["fetch_url", "write_file", "echo"])
            tools = {t.name: t for t in back.tools}
            # input_schema 字典级相等(不只 name)
            self.assertEqual(tools["fetch_url"].input_schema, FETCH_URL_SCHEMA)
            self.assertEqual(tools["write_file"].input_schema, WRITE_FILE_SCHEMA)
            # side_effects 经 `side-effects:` doc 行回读
            self.assertFalse(tools["fetch_url"].side_effects)
            self.assertTrue(tools["write_file"].side_effects)
            self.assertFalse(tools["echo"].side_effects)
            # description 首段语义不变
            self.assertEqual(tools["fetch_url"].description, "Fetch a URL")
            self.assertIn("echo input", tools["echo"].description)
            # 无 schema 行的工具保持 name-only 现状
            self.assertEqual(tools["echo"].input_schema, {})

    def test_emit_parse_emit_idempotent(self):
        """roundtrip 二次生成逐字节一致:schema/描述/参数注解全链路无损。"""
        ir = make_schema_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / self.fmt / "pass1"
            self._emit(ir, out1)
            text1 = (out1 / "agent.py").read_text(encoding="utf-8")
            back = self._parse(out1)
            out2 = Path(tmp) / self.fmt / "pass2"
            self._emit(back, out2)
            text2 = (out2 / "agent.py").read_text(encoding="utf-8")
            self.assertEqual(text1, text2, "emit→parse→emit 二次生成应逐字节一致")


class TestLangchainSchemaRoundtrip(_RoundtripMixin, unittest.TestCase):
    fmt = "langchain"

    def _emit(self, ir, out):
        if emit_langchain is None:
            self.skipTest("converter.emitters.langchain not available yet")
        return emit_langchain(ir, out)

    def _parse(self, path):
        if parse_langchain is None:
            self.skipTest("converter.parsers.langchain not available yet")
        return parse_langchain(path)

    def test_handwritten_source_without_schema_lines_keeps_name_only(self):
        """无 schema:/side-effects: 行的手写 @tool 源码:保持现状(name+desc)。"""
        if parse_langchain is None:
            self.skipTest("converter.parsers.langchain not available yet")
        src = (
            "from langchain_core.tools import tool\n"
            "\n"
            "@tool\n"
            "def search(query: str) -> str:\n"
            '    """Search the web for the query."""\n'
            "    return query\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            py = Path(tmp) / "handwritten.py"
            py.write_text(src, encoding="utf-8")
            back = parse_langchain(py)
            self.assertEqual([t.name for t in back.tools], ["search"])
            self.assertEqual(back.tools[0].input_schema, {})
            self.assertFalse(back.tools[0].side_effects)
            self.assertIn("Search the web", back.tools[0].description)


class TestAutogenSchemaRoundtrip(_RoundtripMixin, unittest.TestCase):
    fmt = "autogen"

    def _emit(self, ir, out):
        if emit_autogen is None:
            self.skipTest("converter.emitters.autogen not available yet")
        return emit_autogen(ir, out)

    def _parse(self, path):
        if parse_autogen is None:
            self.skipTest("converter.parsers.autogen not available yet")
        return parse_autogen(path)

    def test_handwritten_source_without_schema_lines_keeps_name_only(self):
        """无元数据行的手写 TOOLS 清单:保持现状(name+desc)。"""
        if parse_autogen is None:
            self.skipTest("converter.parsers.autogen not available yet")
        src = (
            "TOOLS = [search]\n"
            "\n"
            "async def search(query: str) -> str:\n"
            '    """Search the web for the query."""\n'
            "    return query\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            py = Path(tmp) / "handwritten.py"
            py.write_text(src, encoding="utf-8")
            back = parse_autogen(py)
            self.assertEqual([t.name for t in back.tools], ["search"])
            self.assertEqual(back.tools[0].input_schema, {})
            self.assertFalse(back.tools[0].side_effects)


class TestDeepagentsInheritsLangchainExtraction(unittest.TestCase):
    """deepagents parser 复用 langchain 的 _extract_tools:agent.py 形态同构回读。"""

    def test_tool_schema_via_deepagents_parser(self):
        if parse_deepagents is None or emit_langchain is None:
            self.skipTest("deepagents parser / langchain emitter not available yet")
        ir = make_schema_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lc"
            emit_langchain(ir, out)
            # 无 skills/ 子目录的 agent.py:parse_deepagents 回退 parse_langchain,
            # 走的正是共享的 _extract_tools(schema 提取同构生效)。
            back = parse_deepagents(out / "agent.py")
            tools = {t.name: t for t in back.tools}
            self.assertEqual(tools["fetch_url"].input_schema, FETCH_URL_SCHEMA)
            self.assertTrue(tools["write_file"].side_effects)
            self.assertEqual(back.metadata.get("source_format"), "deepagents")


class _ArtifactChainMixin:
    """非 Python 源码形态的 emit → parse 工具 schema 往返断言。

    六链(openai/n8n/claude-subagent/crewai-skills/deepagents/skill)统一
    走自描述扩展键(x-source-skill.tools / x-tools: / metadata 行的
    tools 键),解析端优先还原 —— 此前这些链全部静默丢 input_schema。
    """

    fmt: str = ""

    def _emit(self, ir, out):
        raise NotImplementedError

    def _parse(self, path):
        raise NotImplementedError

    def test_tools_schema_roundtrip(self):
        ir = make_single_tool_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / self.fmt
            self._emit(ir, out)
            back = self._parse(out)
            self.assertEqual([t.name for t in back.tools], ["fetch_url"])
            tool = back.tools[0]
            # input_schema 字典级相等 + side_effects 布尔回读(源值为 True)
            self.assertEqual(tool.input_schema, FETCH_URL_SCHEMA)
            self.assertTrue(tool.side_effects)
            self.assertEqual(tool.description, "Fetch a URL")


class TestOpenaiToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    fmt = "openai"

    def _emit(self, ir, out):
        if emit_openai_agents is None:
            self.skipTest("converter.emitters.openai_agents not available yet")
        return emit_openai_agents(ir, out)

    def _parse(self, path):
        if parse_openai is None:
            self.skipTest("converter.parsers.openai not available yet")
        return parse_openai(path)


class TestN8nToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    fmt = "n8n"

    def _emit(self, ir, out):
        if emit_n8n is None:
            self.skipTest("converter.wir not available yet (emit side)")
        return emit_n8n(ir, out)

    def _parse(self, path):
        if parse_n8n is None:
            self.skipTest("converter.parsers.n8n not available yet")
        return parse_n8n(path)


class TestClaudeSubagentToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    fmt = "claude-subagent"

    def _emit(self, ir, out):
        if emit_claude_subagent is None:
            self.skipTest("converter.emitters.claude_subagent not available yet")
        return emit_claude_subagent(ir, out)

    def _parse(self, path):
        if parse_claude_subagent is None:
            self.skipTest("converter.parsers.claude_subagent not available yet")
        return parse_claude_subagent(path)


class TestCrewaiSkillsToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    fmt = "crewai-skills"

    def _emit(self, ir, out):
        if emit_crewai_skills is None:
            self.skipTest("converter.emitters.crewai_skills not available yet")
        return emit_crewai_skills(ir, out)

    def _parse(self, path):
        if parse_crewai_skills is None:
            self.skipTest("converter.parsers.crewai_skills not available yet")
        return parse_crewai_skills(path)


class TestDeepagentsToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    fmt = "deepagents"

    def _emit(self, ir, out):
        if emit_deepagents is None:
            self.skipTest("converter.emitters.deepagents not available yet")
        return emit_deepagents(ir, out)

    def _parse(self, path):
        if parse_deepagents is None:
            self.skipTest("converter.parsers.deepagents not available yet")
        return parse_deepagents(path)


class TestSkillToolsSchemaRoundtrip(_ArtifactChainMixin, unittest.TestCase):
    """agent→skill→agent:write_skill 的 metadata 行携带 tools 键,
    load_skill 优先还原 —— 修复 tools 被静默丢弃的隐性缺陷。"""

    fmt = "skill"

    def _emit(self, ir, out):
        if write_skill is None:
            self.skipTest("converter.skill_writer not available yet")
        return write_skill(ir, out)

    def _parse(self, path):
        if load_skill is None:
            self.skipTest("converter.skill_loader not available yet")
        return load_skill(path)


if __name__ == "__main__":
    unittest.main()
