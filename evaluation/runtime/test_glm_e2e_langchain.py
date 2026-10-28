"""GLM 真实 LLM 端到端测试:langchain/deepagents 转换产物 × OpenAI/Anthropic 双协议。

不是 fake 测试(那是 test_langchain_runtime.py 的职责)——这里用真实 GLM API
跑通四条链,证明产物接线在两种协议下都真实可用:

    a. langchain×OpenAI 协议:ChatOpenAI(model=GLM_MODEL, base_url=GLM_BASE_URL)
       + 产物 agent.py 的 SYSTEM_PROMPT/TOOLS → build_agent → invoke;
    b. langchain×Anthropic 协议:ChatAnthropic(model=GLM_ANTHROPIC_MODEL,
       base_url=GLM_ANTHROPIC_BASE_URL) 同上;
    c. deepagents×OpenAI 协议:按产物 build_agent 同构(model=ChatOpenAI 指 GLM
       v4 路径,skills 由产物 FilesystemBackend 指向产物 skills/)→ invoke;
    d. deepagents×Anthropic 协议:model 换 ChatAnthropic 指 GLM anthropic 路径。

验证问题(统一):
    "这个 skill 有哪几种 Response Modes?只列名字"
答案在 examples/agent-fullcycle-engineering 的 SYSTEM_PROMPT 里(Beginner
learning / Interview preparation / Project delivery / Debugging or review)——
回答命中任一模式词即证明产物 system prompt 真实注入并被模型读到。

环境变量(仅显式进程环境,不读取本机配置文件):
    GLM_API_KEY / GLM_BASE_URL / GLM_MODEL               —— OpenAI 兼容路径
    GLM_ANTHROPIC_BASE_URL / GLM_ANTHROPIC_MODEL         —— Anthropic 兼容路径
缺 GLM_API_KEY 时整类 skipTest。

运行方式(项目根目录):
    python3 -m unittest \
        evaluation.runtime.test_glm_e2e_langchain -v

实测备注(2026-10):
- glm-5.3-flash 走 anthropic 路径默认输出 thinking 块,ChatAnthropic 会把
  content 解析成 blocks 列表(thinking + text);直连实测 max_tokens=2048 足够
  (thinking ~190 tokens 即收敛),无需 disable_thinking;本测试统一从 text
  块提取回答。若未来 thinking 变长耗尽 max_tokens 导致无 text 块,重试一次
  仍失败会以断言信息暴露"未命中模式词 + 回复全文",届时调大 max_tokens 即可。
- glm-4-flash 走 v4 路径,tool_calls 正常(bind_tools 实测通过)。
- GLM v4 OpenAI 兼容层缺陷(链 c 实测定位):system content 为 OpenAI 数组
  格式(deepagents middleware 组装出的 blocks)且文本较长(~15k 字符)时,
  system 内容不会被模型读到 → 模型幻觉作答;纯字符串格式 / 短文本 blocks /
  anthropic 路径均正常。官方 OpenAI 接口对两种格式等价,故链 c 用
  FlattenSystemBlocksChatOpenAI 在发请求前把 system blocks 拍平成字符串,
  属兼容层适配,不改变语义(证据见类 docstring)。
- 每链 signal.alarm 120s 超时;失败(异常或未命中模式词)重试一次。
"""

from __future__ import annotations

import importlib.util
import os
import signal
import sys
import time
import traceback
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runtime._artifacts import artifact_root

OUT_LANGCHAIN: Path
OUT_DEEPAGENTS: Path

QUESTION = "这个 skill 有哪几种 Response Modes?只列名字"
# 命中任一即证明 SYSTEM_PROMPT 真实生效(小写匹配,容忍模型改大小写)
MODE_KEYWORDS = [
    "beginner learning",
    "interview preparation",
    "project delivery",
    "debugging or review",
]
CHAIN_TIMEOUT = 120  # 秒/链


def _final_text(result) -> str:
    """取 agent.invoke 结果最后一条消息的文本(兼容 str 与 blocks 列表)。

    glm-5.3-flash 的 ChatAnthropic content 是 blocks:thinking 块跳过,只拼
    text 块;纯 str(langchain_openai 路径)直接返回。
    """
    last = result["messages"][-1]
    content = getattr(last, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _flattening_chat_openai_cls():
    """构造 FlattenSystemBlocksChatOpenAI 类(延迟定义,便于缺包时 skip)。

    GLM v4 OpenAI 兼容层缺陷适配:deepagents 的 SkillsMiddleware 把 system
    prompt 组装成 OpenAI 数组格式 content(blocks),实测(2026-10)GLM v4
    路径在该格式 + 长文本(~15k 字符,含 SYSTEM_PROMPT 与技能元数据)时
    system 内容不会被模型读到,glm-4-flash 直接幻觉;控制变量实验:

        - 同一 15195 字符 system,字符串 content + 8 工具绑定 → 命中模式词;
        - 同文本文本 blocks content + 8 工具绑定 → 幻觉("Text/Markdown/...");
        - 短文本 blocks(无工具)→ 正常;anthropic 路径原生 blocks → 正常。

    官方 OpenAI 接口对 system 的字符串/数组格式语义等价,拍平纯属性能
    兼容适配,不改变消息语义;仅链 c(deepagents×OpenAI)需要——链 a 的
    create_agent(system_prompt=...) 走纯字符串,链 b/d 走 anthropic 路径。
    """
    from langchain_openai import ChatOpenAI

    class FlattenSystemBlocksChatOpenAI(ChatOpenAI):
        def _flatten_system_blocks(self, messages):
            out = []
            for msg in messages:
                content = getattr(msg, "content", None)
                if getattr(msg, "type", "") == "system" and isinstance(content, list):
                    text = "".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                    msg = msg.model_copy(update={"content": text})
                out.append(msg)
            return out

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return super()._generate(
                self._flatten_system_blocks(messages),
                stop=stop, run_manager=run_manager, **kwargs,
            )

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            yield from super()._stream(
                self._flatten_system_blocks(messages),
                stop=stop, run_manager=run_manager, **kwargs,
            )

    return FlattenSystemBlocksChatOpenAI


class GlmE2ELangChainTest(unittest.TestCase):
    """四条真实 GLM 链:产物模块加载方式学 test_langchain_runtime(fake 版)。"""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("GLM_API_KEY"):
            raise unittest.SkipTest("缺 GLM_API_KEY,整类跳过")
        for pkg in ("langchain", "langchain_openai", "langchain_anthropic", "deepagents"):
            try:
                __import__(pkg)
            except Exception as exc:
                raise unittest.SkipTest(f"{pkg} 不可 import:{exc}")
        from converter.emitters import EMITTERS
        from converter.skill_loader import load_skill

        global OUT_LANGCHAIN, OUT_DEEPAGENTS
        artifacts = artifact_root(cls)
        OUT_LANGCHAIN = artifacts / "langchain"
        OUT_DEEPAGENTS = artifacts / "deepagents"
        ir = load_skill(PROJECT_ROOT / "examples" / "agent-fullcycle-engineering")
        EMITTERS["langchain"](ir, OUT_LANGCHAIN)
        EMITTERS["deepagents"](ir, OUT_DEEPAGENTS)

    # ---------- 公共辅助 ----------

    def _load_module(self, path: Path, name: str):
        """importlib 按文件路径加载产物 agent.py(不污染 sys.modules)。"""
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # 顶层零副作用,不需要 provider/key
        return module

    def _openai_model(self, max_tokens: int = 512):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.environ.get("GLM_MODEL", "glm-4-flash"),
            api_key=os.environ["GLM_API_KEY"],
            base_url=os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            max_tokens=max_tokens,
        )

    def _anthropic_model(self, max_tokens: int = 2048):
        # max_tokens=2048:glm-5.3-flash 默认带 thinking 块,直连实测 ~190
        # tokens 即收敛,2048 余量充足(见模块 docstring 实测备注)。
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=os.environ.get("GLM_ANTHROPIC_MODEL", "glm-5.3-flash"),
            api_key=os.environ["GLM_API_KEY"],
            base_url=os.environ.get("GLM_ANTHROPIC_BASE_URL", "https://open.bigmodel.cn/api/anthropic"),
            max_tokens=max_tokens,
        )

    def _run_chain(self, name: str, build_invoke):
        """跑一条链:120s 超时 + 断言模式词,失败重试一次。

        build_invoke: () -> str,完成 组装→invoke→提取回答,内部异常即链失败。
        返回 (回答文本, 耗时秒),两轮均失败则 self.fail。
        """

        def _once():
            old = signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(
                TimeoutError(f"{name} 超过 {CHAIN_TIMEOUT}s")))
            signal.alarm(CHAIN_TIMEOUT)
            try:
                return build_invoke()
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)

        last_err: BaseException | None = None
        for attempt in (1, 2):
            t0 = time.time()
            try:
                answer = _once()
                elapsed = round(time.time() - t0, 1)
                excerpt = " ".join(answer.split())[:150]
                print(f"\n[{name}] attempt {attempt} 回答({elapsed}s): {excerpt!r}")
                low = answer.lower()
                hits = [k for k in MODE_KEYWORDS if k in low]
                if hits:
                    print(f"[{name}] 命中模式词: {hits}")
                    return answer, elapsed
                last_err = AssertionError(
                    f"回答未命中任一 Response Modes 关键词,前300字符: {answer[:300]!r}"
                )
                print(f"[{name}] attempt {attempt} 未命中模式词,重试")
            except Exception as exc:  # noqa: BLE001 - 超时/网络/断言统一走重试
                elapsed = round(time.time() - t0, 1)
                tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
                first = next((ln.strip() for ln in tb if ln.strip().startswith("File ")), "")
                last_err = exc
                print(f"[{name}] attempt {attempt} 失败({elapsed}s): "
                      f"{type(exc).__name__}: {exc} | tb首行: {first}")
        self.fail(f"[{name}] 两次尝试均失败: {last_err}")

    # ---------- a. langchain × OpenAI 协议 ----------

    def test_a_langchain_openai(self):
        """ChatOpenAI→GLM v4 路径 + 产物 SYSTEM_PROMPT/TOOLS → create_agent。"""

        def build_invoke():
            module = self._load_module(OUT_LANGCHAIN / "agent.py", "e2e_lc_openai")
            agent = module.build_agent(model=self._openai_model(max_tokens=512))
            result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
            return _final_text(result)

        answer, elapsed = self._run_chain("langchain×OpenAI", build_invoke)
        print(f"[langchain×OpenAI] PASS {elapsed}s: {answer[:150]!r}")

    # ---------- b. langchain × Anthropic 协议 ----------

    def test_b_langchain_anthropic(self):
        """ChatAnthropic→GLM anthropic 路径 + 产物 SYSTEM_PROMPT/TOOLS → create_agent。"""

        def build_invoke():
            module = self._load_module(OUT_LANGCHAIN / "agent.py", "e2e_lc_anthropic")
            agent = module.build_agent(model=self._anthropic_model(max_tokens=2048))
            result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
            return _final_text(result)

        answer, elapsed = self._run_chain("langchain×Anthropic", build_invoke)
        print(f"[langchain×Anthropic] PASS {elapsed}s: {answer[:150]!r}")

    # ---------- c. deepagents × OpenAI 协议 ----------

    def test_c_deepagents_openai(self):
        """产物 build_agent 同构:model=ChatOpenAI(GLM v4),skills 走产物 FilesystemBackend。

        用 FlattenSystemBlocksChatOpenAI(拍平 system blocks 的 GLM v4 兼容
        适配,见 _flattening_chat_openai_cls docstring 的控制变量实验)。
        """

        def build_invoke():
            module = self._load_module(OUT_DEEPAGENTS / "agent.py", "e2e_da_openai")
            cls = _flattening_chat_openai_cls()
            llm = cls(
                model=os.environ.get("GLM_MODEL", "glm-4-flash"),
                api_key=os.environ["GLM_API_KEY"],
                base_url=os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                max_tokens=512,
            )
            agent = module.build_agent(model=llm)
            result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
            return _final_text(result)

        answer, elapsed = self._run_chain("deepagents×OpenAI", build_invoke)
        print(f"[deepagents×OpenAI] PASS {elapsed}s: {answer[:150]!r}")

    # ---------- d. deepagents × Anthropic 协议 ----------

    def test_d_deepagents_anthropic(self):
        """产物 build_agent 同构:model=ChatAnthropic(GLM anthropic 路径)。"""

        def build_invoke():
            module = self._load_module(OUT_DEEPAGENTS / "agent.py", "e2e_da_anthropic")
            agent = module.build_agent(model=self._anthropic_model(max_tokens=2048))
            result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
            return _final_text(result)

        answer, elapsed = self._run_chain("deepagents×Anthropic", build_invoke)
        print(f"[deepagents×Anthropic] PASS {elapsed}s: {answer[:150]!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
