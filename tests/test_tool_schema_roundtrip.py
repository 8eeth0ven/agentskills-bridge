"""工具 input_schema / side_effects 的 emit→parse 往返测试(langchain/autogen)。

上轮缺点清单第 4 项:此前仅 generic 完整保留 tools schema;本批在
@tool / async def stub 的 docstring 里落 `schema: {单行 JSON}` 与
`side-effects: true|false` 元数据行(emitters/langchain._tool_docstring),
parse 侧按行正则 + json.loads 还原(parsers/langchain._tool_meta_from_docstring,
autogen 同构复用)。deepagents parser 复用 langchain 的 _extract_tools,
其工具往返与 langchain 同构,不单独改 emitter(deepagents 产物把工具留给
skills/ 运行时,agent.py 不含 @tool stub,属已知剩余限制)。

覆盖:
    1. emit → py_compile → parse:input_schema 字典级相等(不只 name)、
       side_effects 布尔回读、description 首段语义不变;
    2. schema 含反斜杠/引号等需转义字符时仍精确还原;
    3. 无 schema 行的手写源码:保持 name-only 现状(input_schema == {});
    4. roundtrip emit → parse → emit 二次生成逐字节一致(idempotent)。
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


if __name__ == "__main__":
    unittest.main()
