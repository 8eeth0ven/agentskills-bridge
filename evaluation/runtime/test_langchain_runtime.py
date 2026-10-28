"""LangChain/deepagents 运行时验证:用真实安装的框架加载 agentskills-bridge 转换产物。

不是静态检查——setUpClass 里真正安装/导入 langchain>=1.0 与 deepagents>=0.7,
用 importlib 加载生成的 agent.py、用 langchain_core 的 fake chat model 真跑
一轮 create_agent / create_deep_agent 图,并用 deepagents 包内的 SKILL.md
解析入口(_list_skills + FilesystemBackend)加载产物 skills/ 目录。

运行方式(项目根目录):
    python3 -m unittest evaluation.runtime.test_langchain_runtime -v

覆盖(对应任务 a-e):
    a. test_a_agent_py_import —— importlib 加载 临时产物 langchain/agent.py,
       断言 langchain.agents.create_agent / langchain.chat_models.init_chat_model /
       langchain_core.tools.tool 真实可导入且模块顶层零副作用(导入不需要
       provider 包或 API key;组装在 build_agent() 工厂里延迟发生)。
    b. test_b_fake_model_round —— GenericFakeChatModel + monkeypatch
       bind_tools(langchain 1.x create_agent 必调 model.bind_tools,core 的
       fake 未实现,返回 self 即可),经模块内 build_agent(model=fake)
       组装 create_agent(model, tools=TOOLS, system_prompt=SYSTEM_PROMPT),
       invoke 一轮断言返回 AIMessage。
    c. test_c_tool_stubs —— 模块内每个 @tool stub 按参数 schema 填默认值
       直接调用一次,断言返回 str。
    d. deepagents 三件:
       d1 test_d1_deepagents_signature —— import deepagents,核对
          create_deep_agent 真实签名(model/tools/system_prompt/skills/backend
          均为合法参数),并与生成代码调用对照。
       d2 test_d2_skills_loading —— 在已装 deepagents 包源码里确认 SKILL.md
          引用入口(等价 grep -r "SKILL" site-packages/deepagents/),再用
          包内解析函数 _list_skills(FilesystemBackend, "skills") 真实加载
          临时产物 deepagents/skills/agent-fullcycle-engineering,断言
          name/description 被识别。
       d3 test_d3_deepagents_fake_round —— 模块 build_agent(model=RecordingFake)
          跑一轮,断言返回消息;并断言 SkillsMiddleware 把技能 name/description
          注入了模型收到的 system prompt(渐进披露第 1 级)。

langchain 不可 import 时整类 skipTest;仅 deepagents 缺失时 d 组单独
skipTest(网络/环境问题不判失败)。
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runtime._artifacts import artifact_root

SKILL_DIR = PROJECT_ROOT / "examples" / "agent-fullcycle-engineering"
OUT_LANGCHAIN: Path
OUT_DEEPAGENTS: Path
SKILL_NAME = "agent-fullcycle-engineering"
DESC_HEAD = "End-to-end AI agent engineering workflow"

# fake model 每次被问都回这句(不带 tool_calls,一轮即收敛)
FAKE_REPLY = "hello from fake model"

# stub 参数 schema 类型 → 默认值(test_c 用)
_DEFAULTS = {
    "string": "x",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
    "object": {},
}


def _version(pkg: str) -> str:
    from importlib.metadata import version

    return version(pkg)


def _RecordingFakeChatModel(_seen: list):
    """构造记录型 fake BaseChatModel:捕获每次收到的 messages,固定回一句。

    BaseChatModel 是 pydantic 模型,记录列表必须放闭包/模块级(类属性带
    注解会被 pydantic 收编成字段,`type(self).seen` 访问报 AttributeError)。
    bind_tools 返回 self:langchain 1.x 的 create_agent / deepagents 组装链
    必调 model.bind_tools(...),返回自身即按"模型已接受工具"处理。
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _RecordingFake(BaseChatModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
            _seen.append(list(messages))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=FAKE_REPLY))])

        @property
        def _llm_type(self) -> str:
            return "recording-fake-chat-model"

    return _RecordingFake


class LangChainRuntimeTest(unittest.TestCase):
    """用真实 langchain 1.x / deepagents 0.7.x 运行时加载转换产物。"""

    @classmethod
    def setUpClass(cls):
        try:
            import langchain  # noqa: F401
            import langchain_core  # noqa: F401
        except Exception as exc:  # 网络/安装问题不判失败
            raise unittest.SkipTest(f"langchain/langchain_core 不可 import,整类跳过: {exc}")

        cls.lc_version = _version("langchain")
        cls.core_version = _version("langchain-core")
        print(f"\n[langchain runtime] langchain=={cls.lc_version} langchain-core=={cls.core_version}")

        # 每次运行用当前 converter 代码重新生成产物,保证验证的是最新转换逻辑
        from converter.emitters import EMITTERS
        from converter.skill_loader import load_skill

        ir = load_skill(SKILL_DIR)
        global OUT_LANGCHAIN, OUT_DEEPAGENTS
        artifacts = artifact_root(cls)
        OUT_LANGCHAIN = artifacts / "langchain"
        OUT_DEEPAGENTS = artifacts / "deepagents"
        EMITTERS["langchain"](ir, OUT_LANGCHAIN)
        EMITTERS["deepagents"](ir, OUT_DEEPAGENTS)

        # 深度依赖 langchain 的部分这里就绑定;deepagents 单独在 d 组判
        cls.fake_seen: list = []
        cls.RecordingFake = _RecordingFakeChatModel(cls.fake_seen)

    # ---------- 公共辅助 ----------

    def _ctx(self) -> str:
        return f"[langchain=={self.lc_version} core=={self.core_version}]"

    def _fail_with_tb(self, message: str, exc: BaseException) -> None:
        """失败信息带 traceback 首行,便于定位框架内部断点。"""
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        first = next((ln.strip() for ln in lines if ln.strip().startswith("File ")), "")
        self.fail(f"{message}: {type(exc).__name__}: {exc} | tb首行: {first}")

    def _load_module(self, path: Path, name: str):
        """importlib 按文件路径加载生成模块(每次现载,不污染 sys.modules)。"""
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            self._fail_with_tb(f"{self._ctx()} 导入 {path} 失败(API 与真实包不符)", exc)
        return module

    def _fake_model(self):
        """GenericFakeChatModel + monkeypatch bind_tools(任务 b 指定用该 fake)。"""
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage

        # langchain 1.x create_agent 必调 model.bind_tools(tools, ...);
        # core 1.x 的 GenericFakeChatModel 未实现(NotImplementedError),
        # patch 成返回 self 即通过组装链。
        if getattr(GenericFakeChatModel, "bind_tools", None) is None or \
                GenericFakeChatModel.bind_tools.__qualname__ != "GenericFakeChatModel.bind_tools":
            try:
                GenericFakeChatModel.bind_tools = lambda self, tools, **kw: self  # type: ignore[method-assign]
            except TypeError as exc:  # 固化版本不允许 patch 时退回记录型 fake
                print(f"[langchain runtime] bind_tools patch 失败({exc}),退回 RecordingFake")
                return self.RecordingFake()
        return GenericFakeChatModel(messages=iter([AIMessage(content=FAKE_REPLY)]))

    # ---------- a. agent.py 导入 ----------

    def test_a_agent_py_import(self):
        """生成的 agent.py 可被真实 langchain 1.x 导入,顶层零副作用。"""
        # 生成代码引用的三个 API 必须真实存在(import 成功 = API 真实)
        from langchain.agents import create_agent  # noqa: F401
        from langchain.chat_models import init_chat_model  # noqa: F401
        from langchain_core.tools import tool  # noqa: F401

        sig = inspect.signature(create_agent)
        params = list(sig.parameters)
        self.assertIn("model", params, f"{self._ctx()} create_agent 首参应为 model: {params}")
        for kw in ("tools", "system_prompt"):
            self.assertIn(kw, params, f"{self._ctx()} create_agent 缺关键字参数 {kw}: {params}")

        module = self._load_module(OUT_LANGCHAIN / "agent.py", "rt_langchain_agent")
        # 模块级契约:常量 + 工具 + 组装工厂
        self.assertTrue((module.SYSTEM_PROMPT or "").strip(), f"{self._ctx()} SYSTEM_PROMPT 为空")
        self.assertEqual(getattr(module, "AGENT_NAME", None), SKILL_NAME,
                         f"{self._ctx()} AGENT_NAME 与技能名不一致")
        self.assertTrue(list(module.TOOLS), f"{self._ctx()} TOOLS 为空(应至少含占位 echo_tool)")
        self.assertTrue(callable(getattr(module, "build_agent", None)),
                        f"{self._ctx()} 缺 build_agent 工厂(顶层组装会使导入依赖 provider 包)")
        print(f"[langchain runtime] import OK: tools={[t.name for t in module.TOOLS]},"
              f" prompt_len={len(module.SYSTEM_PROMPT)}")

    # ---------- b. 假模型跑一轮 ----------

    def test_b_fake_model_round(self):
        """build_agent(model=fake) 真跑一轮 create_agent 图,断言返回 AIMessage。"""
        module = self._load_module(OUT_LANGCHAIN / "agent.py", "rt_langchain_agent_b")
        fake = self._fake_model()
        try:
            agent = module.build_agent(model=fake)
        except Exception as exc:
            self._fail_with_tb(f"{self._ctx()} build_agent(model=fake) 组装失败(签名不符)", exc)
            return
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
        except Exception as exc:
            self._fail_with_tb(f"{self._ctx()} agent.invoke 一轮失败", exc)
            return
        messages = result["messages"]
        self.assertGreaterEqual(len(messages), 2, f"{self._ctx()} 返回消息数异常: {len(messages)}")
        last = messages[-1]
        from langchain_core.messages import AIMessage

        self.assertIsInstance(last, AIMessage,
                              f"{self._ctx()} 最后一条应为 AIMessage,实际 {type(last).__name__}")
        self.assertEqual(last.content, FAKE_REPLY, f"{self._ctx()} fake 回复未透传: {last.content!r}")
        print(f"[langchain runtime] fake 一轮 OK: {len(messages)} messages, last={last.content!r}")

    # ---------- c. @tool stub 直调 ----------

    def test_c_tool_stubs(self):
        """模块内每个 @tool stub 按参数 schema 填默认值直调一次,返回 str。"""
        module = self._load_module(OUT_LANGCHAIN / "agent.py", "rt_langchain_agent_c")
        stubs = list(module.TOOLS)
        self.assertTrue(stubs, f"{self._ctx()} TOOLS 为空")
        for wrapped in stubs:
            name = getattr(wrapped, "name", None) or getattr(wrapped, "__name__", "<anon>")
            func = getattr(wrapped, "func", None) or wrapped  # StructuredTool 走 .func,裸函数直调
            schema = getattr(wrapped, "args", None) or {}
            kwargs = {}
            for pname, pschema in schema.items():
                ptype = str((pschema or {}).get("type", "")).lower()
                kwargs[pname] = _DEFAULTS.get(ptype, "x")
            try:
                out = func(**kwargs) if kwargs else func()
            except Exception as exc:
                self._fail_with_tb(f"{self._ctx()} stub {name}({kwargs}) 直调失败", exc)
                return
            self.assertIsInstance(out, str, f"{self._ctx()} stub {name} 应返回 str,实际 {type(out).__name__}")
            print(f"[langchain runtime] stub {name}{tuple(kwargs)} -> {out[:60]!r}")

    # ---------- d1. deepagents 签名核对 ----------

    def _deepagents_or_skip(self):
        try:
            import deepagents  # noqa: F401
        except Exception as exc:
            self.skipTest(f"deepagents 不可 import(装失败按 skip 只测 langchain): {exc}")
        import deepagents

        return deepagents

    def test_d1_deepagents_signature(self):
        """create_deep_agent 真实签名与生成代码调用对照(model/system_prompt/skills/backend)。"""
        deepagents = self._deepagents_or_skip()
        da_version = _version("deepagents")
        print(f"[deepagents runtime] deepagents=={da_version}")

        from deepagents import create_deep_agent

        sig = inspect.signature(create_deep_agent)
        params = sig.parameters
        self.assertIn("model", params, f"[deepagents=={da_version}] create_deep_agent 缺 model: {list(params)}")
        for kw in ("system_prompt", "skills"):
            self.assertIn(kw, params, f"[deepagents=={da_version}] create_deep_agent 缺 {kw}: {list(params)}")

        # 生成代码用的是 skills + backend 组合(FilesystemBackend 从磁盘读
        # SKILL.md;默认 StateBackend 是内存文件系统,不传文件就读不到),
        # backend 参数必须真实存在
        self.assertIn("backend", params, f"[deepagents=={da_version}] 缺 backend 参数:"
                                         f" skills=['skills'] 无法从磁盘加载")

        text = (OUT_DEEPAGENTS / "agent.py").read_text(encoding="utf-8")
        self.assertIn("create_deep_agent", text, "生成代码未调用 create_deep_agent")
        self.assertIn("FilesystemBackend", text, "生成代码未用 FilesystemBackend(skills 无法从磁盘加载)")
        self.assertIn('skills=["skills"]', text, "生成代码 skills 源目录写法漂移")

    # ---------- d2. SKILL.md 解析加载 ----------

    def test_d2_skills_loading(self):
        """deepagents 包内 SKILL.md 解析入口真实加载产物 skills/ 并识别 name/description。"""
        self._deepagents_or_skip()
        import deepagents
        from deepagents.backends import FilesystemBackend

        da_version = _version("deepagents")
        skill_md = OUT_DEEPAGENTS / "skills" / SKILL_NAME / "SKILL.md"
        self.assertTrue(skill_md.is_file(), f"[deepagents=={da_version}] 产物缺技能文件: {skill_md}")

        # 1) 在已装 deepagents 包源码里找 SKILL.md 引用入口(等价 grep -r "SKILL")
        pkg_dir = Path(deepagents.__file__).resolve().parent.parent / "deepagents"
        hits = [
            str(p.relative_to(pkg_dir))
            for p in sorted(pkg_dir.rglob("*.py"))
            if "SKILL" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertTrue(hits, f"[deepagents=={da_version}] 包内找不到任何 SKILL 引用:"
                              f" 不支持 Agent Skills: {pkg_dir}")
        print(f"[deepagents runtime] SKILL 引用入口({len(hits)} 处): {hits[:4]}")

        # 2) 包内解析函数 _list_skills + FilesystemBackend 真实加载产物 skills/
        try:
            from deepagents.middleware.skills import _list_skills
        except ImportError as exc:
            self.fail(f"[deepagents=={da_version}] 包内 SKILL.md 解析入口不可导入: {exc}")
        backend = FilesystemBackend(root_dir=OUT_DEEPAGENTS)
        skills = _list_skills(backend, "skills")
        matched = [s for s in skills if s.get("name") == SKILL_NAME]
        self.assertTrue(
            matched,
            f"[deepagents=={da_version}] _list_skills 未识别 {SKILL_NAME}:"
            f" skills={[(s.get('name'), s.get('path')) for s in skills]}",
        )
        sk = matched[0]
        desc = sk.get("description") or ""
        self.assertTrue(desc.strip().startswith(DESC_HEAD),
                        f"[deepagents=={da_version}] 技能 description 未被识别: {desc[:120]!r}")
        print(f"[deepagents runtime] _list_skills OK: name={sk['name']},"
              f" path={sk['path']}, desc_len={len(desc)}")

    # ---------- d3. deepagents fake 跑一轮 ----------

    def test_d3_deepagents_fake_round(self):
        """build_agent(model=fake) 跑一轮 deepagents 图;断言技能元数据注入 system prompt。"""
        self._deepagents_or_skip()
        da_version = _version("deepagents")
        module = self._load_module(OUT_DEEPAGENTS / "agent.py", "rt_deepagents_agent")

        self.fake_seen.clear()
        try:
            agent = module.build_agent(model=self.RecordingFake())
        except Exception as exc:
            self._fail_with_tb(f"[deepagents=={da_version}] build_agent(model=fake) 组装失败", exc)
            return
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
        except Exception as exc:
            self._fail_with_tb(f"[deepagents=={da_version}] agent.invoke 一轮失败", exc)
            return
        messages = result["messages"]
        self.assertTrue(messages, f"[deepagents=={da_version}] 返回 messages 为空")
        last = messages[-1]
        from langchain_core.messages import AIMessage

        self.assertIsInstance(last, AIMessage,
                              f"[deepagents=={da_version}] 最后一条应为 AIMessage,实际 {type(last).__name__}")

        # SkillsMiddleware 渐进披露第 1 级:name/description 注入 system prompt
        self.assertTrue(self.fake_seen, f"[deepagents=={da_version}] fake model 未收到任何调用")
        system_text = ""
        for m in self.fake_seen[0]:
            if getattr(m, "type", "") == "system":
                content = m.content
                if isinstance(content, str):
                    system_text += content
                else:  # content blocks 列表
                    system_text += "".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
        self.assertIn(SKILL_NAME, system_text,
                      f"[deepagents=={da_version}] system prompt 未注入技能名 {SKILL_NAME}"
                      f"(len={len(system_text)})")
        self.assertIn(DESC_HEAD, system_text,
                      f"[deepagents=={da_version}] system prompt 未注入技能 description 头")
        print(f"[deepagents runtime] fake 一轮 OK: last={last.content!r},"
              f" system_len={len(system_text)}, 技能元数据已注入")


if __name__ == "__main__":
    unittest.main(verbosity=2)
