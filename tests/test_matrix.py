"""双向全矩阵测试:8 键 emit → parse → write_skill → load_skill 全链路。

覆盖(见任务规格):
    TestForwardMatrix     正向:同一 IR 对 EMITTERS 八键各 emit 一份,产物非空、
                          knowledge 恰好拷贝 2 份(knowledge/ 或 skills/*/references/)
    TestBackwardMatrix    反向:emit 后用 PARSERS 对应键解析回来,
                          name / knowledge 数 / system_prompt 非空
    TestRoundtripFidelity 全链路保真:emit→parse→write_skill→load_skill,
                          slug、knowledge filename+content、system_prompt 按格式分级断言
    TestSkillWriterSpec   write_skill 规范化:1500 字 description 截断 ≤1024、
                          emoji 正文不坏、大写下划线 name 归一 kebab
    TestCorpusSinks       边界:极简 IR 八键 emit 全不崩,可解析链 system_prompt 非空

并行线程正在新增 4 个 parser(crewai-skills/deepagents/openai/claude-subagent):
PARSERS 键尚缺时对应用例 skipTest("parser pending"),不算失败。

已知规格偏差(实测上报):parse_langchain 的 name 契约是 slugify(path.stem),
emit_langchain 固定产出 agent.py,故 langchain 反向 name 恒为 "agent" ——
这是 parser 设计而非回归;langchain 链按「合法非空 slug + write/load 不改写」
断言,其余链按 slugify(name) 与源 IR 一致断言。
"""

import importlib
import re
import tempfile
import unittest
from pathlib import Path

from converter.ir import AgentIR, KnowledgeDoc, ToolSpec, parse_frontmatter, slugify

# 八键全矩阵(与 converter.ir.TARGET_FORMATS 对齐)
FORMATS = (
    "crewai",
    "crewai-skills",
    "deepagents",
    "langchain",
    "langflow",
    "openai",
    "claude-subagent",
    "generic",
)

KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# 各格式 parse 入口(相对 emit 产物根目录)
ENTRY = {
    "crewai": lambda d: d,
    "crewai-skills": lambda d: d,
    "deepagents": lambda d: d,
    "langchain": lambda d: d / "agent.py",
    "langflow": lambda d: d / "flow.json",
    "openai": lambda d: d,
    "claude-subagent": lambda d: d,
    "generic": lambda d: d / "agent.json",
}


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


def _emitters():
    """EMITTERS 注册表;模块缺失返回 None(并行线程可能正在改写)。"""
    try:
        from converter.emitters import EMITTERS
    except Exception:
        return None
    return EMITTERS


def _parsers():
    """PARSERS 注册表;模块缺失返回 None(4 个新 parser 落盘中)。"""
    try:
        from converter.parsers import PARSERS
    except Exception:
        return None
    return PARSERS


def _parser_or_skip(case, fmt):
    """取 PARSERS[fmt];注册表缺失或键尚缺时 skipTest 而非 error。"""
    parsers = _parsers()
    if parsers is None:
        case.skipTest("converter.parsers not available yet")
    fn = parsers.get(fmt)
    if fn is None:
        case.skipTest(f"parser pending: PARSERS[{fmt!r}] 尚未落盘")
    return fn


def _emitters_or_skip(case):
    emitters = _emitters()
    if emitters is None:
        case.skipTest("converter.emitters not available yet")
    return emitters


def _skill_fns_or_skip(case):
    """返回 (load_skill, write_skill);任一缺失时 skipTest。"""
    load_skill = _resolve(("converter.skill_loader",), ("load_skill",))
    write_skill = _resolve(("converter.skill_writer",), ("write_skill",))
    if load_skill is None or write_skill is None:
        case.skipTest("skill_loader/skill_writer not available yet")
    return load_skill, write_skill


def make_matrix_ir() -> AgentIR:
    """矩阵测试专用 IR:中英混排、代码栅栏、中文标点引号、双知识文档。"""
    return AgentIR(
        name="matrix-agent",
        display_name="Matrix Agent",
        description="Matrix test agent.",
        system_prompt="# Matrix\n\n- item\n\n```py\nx=1\n```",
        knowledge=[
            KnowledgeDoc("k1.md", "K1", "# K1\n内容"),
            KnowledgeDoc("k2-zh.md", "K2", '# K2\n中文含引号"与顿号、'),
        ],
        tools=[
            ToolSpec("echo", "echo"),
            ToolSpec("fetch", "fetch", {"type": "object"}, True),
        ],
        scripts=[],
    )


def make_minimal_ir() -> AgentIR:
    """极简 IR:无 knowledge、无 tools、无 default_prompt(边界 sink)。"""
    return AgentIR(
        name="bare-agent",
        description="Bare bones agent.",
        system_prompt="Just do the bare minimum.",
    )


def _knowledge_names(out: Path) -> set:
    """emit 产物里的知识文件名集合:knowledge/ 与 skills/*/references/ 并集。"""
    names = {p.name for p in out.glob("knowledge/*.md")}
    names |= {p.name for p in out.glob("skills/*/references/*.md")}
    return names


def _format_methods(runner_attr):
    """给测试类按 FORMATS 生成 test_<attr>_<fmt> 方法(逐键 pass/skip 粒度)。"""

    def decorate(klass):
        for fmt in FORMATS:
            def method(self, _fmt=fmt, _attr=runner_attr):
                getattr(self, _attr)(_fmt)

            method.__name__ = f"test_{runner_attr}_{fmt.replace('-', '_')}"
            setattr(klass, method.__name__, method)
        return klass

    return decorate


def _edge_normalized(text: str) -> str:
    """剥掉首尾换行:write_skill/collect_knowledge 的文件末尾换行是文件格式产物,
    不算内容差异;正文内部逐字符保留。"""
    return (text or "").strip("\n")


# ---------------------------------------------------------------- 正向矩阵

class TestForwardMatrix(unittest.TestCase):
    """同一 IR 对 EMITTERS 八键各 emit:产物非空 + knowledge 恰好 2 份。"""

    def test_emit_all_eight_formats(self):
        emitters = _emitters_or_skip(self)
        missing = set(FORMATS) - set(emitters)
        self.assertFalse(
            missing, f"EMITTERS 应含八键,缺: {sorted(missing)}(emitter 回归)"
        )
        ir = make_matrix_ir()
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in FORMATS:
                out = Path(tmp) / fmt
                emitters[fmt](ir, out)
                files = [p for p in out.rglob("*") if p.is_file()]
                self.assertTrue(files, f"{fmt}: emit 产物目录为空")
                names = _knowledge_names(out)
                self.assertEqual(
                    names,
                    {"k1.md", "k2-zh.md"},
                    f"{fmt}: knowledge 拷贝数应 == 2(实际 {sorted(names)})",
                )


# ---------------------------------------------------------------- 反向矩阵

@_format_methods("run_backward")
class TestBackwardMatrix(unittest.TestCase):
    """emit 每格式 → PARSERS 对应键解析:name / knowledge 数 / prompt 非空。"""

    def run_backward(self, fmt):
        parse_fn = _parser_or_skip(self, fmt)
        emitters = _emitters_or_skip(self)
        ir = make_matrix_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / fmt
            emitters[fmt](ir, out)
            back = parse_fn(ENTRY[fmt](out))

            if fmt == "langchain":
                # 已知契约偏差:parse_langchain 按 path.stem 取名(agent.py →
                # "agent"),emit 固定写 agent.py,故 name 不随源 IR;属设计。
                self.assertTrue(
                    back.name and KEBAB_RE.match(back.name),
                    f"langchain 反向 name 应为合法非空 slug: {back.name!r}",
                )
            else:
                # ir.name 本身是 slug,slugify 后比较同时覆盖「相等」与
                # 「slug 相同」(crewai 例外)两种形态。
                self.assertEqual(
                    slugify(back.name),
                    slugify(ir.name),
                    f"{fmt}: 反向 name 应回流为 {ir.name!r}(实际 {back.name!r})",
                )
            self.assertEqual(
                len(back.knowledge), 2, f"{fmt}: 反向 knowledge 数应为 2"
            )
            self.assertEqual(
                {k.filename for k in back.knowledge},
                {"k1.md", "k2-zh.md"},
                f"{fmt}: 反向 knowledge 文件名应一一对应",
            )
            self.assertTrue(
                back.system_prompt.strip(), f"{fmt}: 反向 system_prompt 应非空"
            )


# ------------------------------------------------------- 全链路保真(核心)

@_format_methods("run_roundtrip")
class TestRoundtripFidelity(unittest.TestCase):
    """emit → parse → write_skill → load_skill 四段链的 F 类指标。

    system_prompt 分级:
        crewai / langchain / langflow —— 结构化组装差异容忍,断言包含关键句
        claude-subagent               —— 正文包含关键句
        crewai-skills / deepagents / generic —— skill 目录原生保留,
                                        除首尾换行外逐字符一致
    """

    # 关键句:源 system_prompt 正文语义标志(标题词)
    KEY_SENTENCE = "Matrix"

    def run_roundtrip(self, fmt):
        parse_fn = _parser_or_skip(self, fmt)
        emitters = _emitters_or_skip(self)
        load_skill, write_skill = _skill_fns_or_skip(self)
        ir = make_matrix_ir()
        src_knowledge = {k.filename: _edge_normalized(k.content) for k in ir.knowledge}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agent_dir = tmp_path / f"agent-{fmt}"
            emitters[fmt](ir, agent_dir)
            back = parse_fn(ENTRY[fmt](agent_dir))

            skill_dir = tmp_path / f"skill-{fmt}"
            write_skill(back, skill_dir)
            final = load_skill(skill_dir)

            # F1 name:最终 skill 的 name 是合法 slug;除 langchain(按 stem
            # 取名,见 TestBackwardMatrix 注)外应与源 IR 的 slug 一致。
            self.assertTrue(
                final.name and KEBAB_RE.match(final.name),
                f"{fmt}: 全链路后 name 应为合法非空 slug: {final.name!r}",
            )
            if fmt == "langchain":
                self.assertEqual(
                    final.name, slugify(back.name),
                    "langchain: write/load 不应改写 parse 给出的 name",
                )
            else:
                self.assertEqual(
                    slugify(final.name), slugify(ir.name),
                    f"{fmt}: 全链路 name 应回流为 {slugify(ir.name)!r}",
                )

            # F2 knowledge:filename + content 全部一致(容文件末尾换行)。
            got_knowledge = {
                k.filename: _edge_normalized(k.content) for k in final.knowledge
            }
            self.assertEqual(
                got_knowledge, src_knowledge,
                f"{fmt}: 全链路 knowledge(filename+content)回流不一致",
            )

            # F3 system_prompt:按格式分级。
            if fmt in ("crewai", "langchain", "langflow", "claude-subagent"):
                self.assertIn(
                    self.KEY_SENTENCE, final.system_prompt,
                    f"{fmt}: 全链路 system_prompt 应保留关键句 {self.KEY_SENTENCE!r}",
                )
            else:  # crewai-skills / deepagents / generic:原生保留,逐字符一致
                self.assertEqual(
                    _edge_normalized(final.system_prompt),
                    _edge_normalized(ir.system_prompt),
                    f"{fmt}: skill 目录原生保留链 system_prompt 应逐字符一致",
                )


# ------------------------------------------------------- skill_writer 规格

class TestSkillWriterSpec(unittest.TestCase):
    """write_skill:1500 字 description 截断、emoji 正文不坏、name 归一。"""

    def test_long_description_emoji_and_name_slug(self):
        write_skill = _resolve(("converter.skill_writer",), ("write_skill",))
        if write_skill is None:
            self.skipTest("skill_writer not available yet")
        ir = AgentIR(
            name="Matrix_Agent V2",  # 大写 + 下划线 + 空格 → 应归一 kebab
            display_name="Matrix Agent",
            description="测" * 1500,  # 1500 字超长 description
            system_prompt="最小输入 🚀 执行并汇总。\n\n- 步骤一 ✅\n- 步骤二 📦",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "skill-out"
            write_skill(ir, out)
            skill_md = out / "SKILL.md"
            self.assertTrue(skill_md.is_file(), "SKILL.md 应存在")
            meta, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))

            name = meta.get("name", "")
            self.assertTrue(
                KEBAB_RE.match(name),
                f"含大写下划线的 name 应被规范化为 kebab: {name!r}",
            )
            self.assertEqual(name, "matrix-agent-v2")

            desc = meta.get("description", "")
            self.assertTrue(desc.strip(), "description 应非空")
            self.assertLessEqual(
                len(desc), 1024, f"1500 字 description 应截断 ≤1024(实际 {len(desc)})"
            )

            self.assertIn("🚀", body, "emoji 正文应原样保留")
            self.assertIn("步骤一 ✅", body)
            self.assertTrue(body.strip(), "正文应非空")


# ---------------------------------------------------------------- 边界 sink

@_format_methods("run_sink")
class TestCorpusSinks(unittest.TestCase):
    """极简 IR(无 knowledge/tools/default_prompt):八键 emit 不崩,解析回非空。"""

    def test_minimal_emit_all_keys_survive(self):
        emitters = _emitters_or_skip(self)
        ir = make_minimal_ir()
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in sorted(emitters):
                out = Path(tmp) / fmt
                emitters[fmt](ir, out)  # 不崩即过
                files = [p for p in out.rglob("*") if p.is_file()]
                self.assertTrue(files, f"{fmt}: 极简 IR emit 产物目录为空")

    def run_sink(self, fmt):
        parse_fn = _parser_or_skip(self, fmt)
        emitters = _emitters_or_skip(self)
        ir = make_minimal_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / fmt
            emitters[fmt](ir, out)
            back = parse_fn(ENTRY[fmt](out))
            self.assertTrue(
                back.system_prompt.strip(),
                f"{fmt}: 极简 IR 解析回 system_prompt 应非空",
            )

    def test_nonempty_prompt_at_least_five_chains(self):
        """可解析链里 system_prompt 非空的 ≥5 条;新 parser 未齐时按已齐数量要求。"""
        parsers = _parsers()
        if parsers is None:
            self.skipTest("converter.parsers not available yet")
        emitters = _emitters_or_skip(self)
        available = [fmt for fmt in FORMATS if fmt in parsers]
        if not available:
            self.skipTest("PARSERS 中尚无矩阵键(parser pending)")
        ir = make_minimal_ir()
        nonempty = []
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in available:
                out = Path(tmp) / fmt
                emitters[fmt](ir, out)
                if parsers[fmt](ENTRY[fmt](out)).system_prompt.strip():
                    nonempty.append(fmt)
        required = min(5, len(available))
        self.assertGreaterEqual(
            len(nonempty), required,
            f"极简 IR 非空 system_prompt 链应 ≥{required}(实际 {len(nonempty)}/{len(available)}: {nonempty})",
        )


if __name__ == "__main__":
    unittest.main()
