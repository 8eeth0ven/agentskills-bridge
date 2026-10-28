"""autogen 产物 × GLM 双协议真实 LLM 端到端测试(真实 API,不打桩)。

覆盖两条链(对应任务 d/e):
    d. test_d_autogen_glm_openai_protocol —— 产物 agent.py 的 build_agent()
       + OpenAIChatCompletionClient(model=<glm>, base_url=GLM v4) → run()。
    e. test_e_autogen_glm_anthropic_protocol —— AnthropicChatCompletionClient
       (model=<glm>, base_url=GLM anthropic 兼容端点)同上。

实测环境(2026-10-11,autogen-agentchat/autogen-ext==0.7.5):
- 非官方模型名(glm-4-flash / glm-5.3-flash)不被 autogen-ext 内置模型表
  识别,必须显式传 model_info(否则 ValueError: model_info is required)。
- anthropic SDK:autogen-ext 0.7.5 固定发送 temperature,而 anthropic>=1.13.0
  的 messages.create 已删掉该参数会 TypeError;需 anthropic<1.0(实测
  0.98.1)。装不上 autogen-ext[anthropic] 时本类只测 OpenAI 协议并注明。
- 断言依据:SYSTEM_MESSAGE 全文含 "## Response Modes"(Beginner/
  Interview/Project delivery/Debugging),真实生效则回答含任一模式词。

运行方式(需先通过环境变量设置 GLM_API_KEY 等):
    python3 -m unittest evaluation.runtime.test_glm_e2e_autogen -v

无 GLM_API_KEY 时整类 skipTest(密钥缺失不算失败)。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runtime._artifacts import artifact_root

SKILL_DIR = PROJECT_ROOT / "examples" / "agent-fullcycle-engineering"
OUT_AUTOGEN: Path

QUESTION = "这个 skill 有哪几种 Response Modes?只列名字"
MODE_WORDS = ("Beginner", "Interview", "Project delivery", "Debugging")
TIMEOUT_S = 120  # asyncio.wait_for 预算;失败重试一次

# 非官方模型名(GLM 系)不被 autogen-ext 内置模型表识别,需显式能力声明
MODEL_INFO = {
    "function_calling": True,
    "json_output": True,
    "vision": False,
    "family": "unknown",
    "structured_output": False,
    "multiple_system_messages": True,
}



class GLME2EAutogenTest(unittest.TestCase):
    """autogen 转换产物 × GLM 双协议真实推理(真实 run,断言模式词)。"""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("GLM_API_KEY"):
            raise unittest.SkipTest("GLM_API_KEY 未设置,整类跳过")
        try:
            from autogen_agentchat.agents import AssistantAgent  # noqa: F401
            from autogen_ext.models.openai import OpenAIChatCompletionClient  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"autogen-agentchat / autogen-ext[openai] 不可 import,整类跳过: {exc}")

        import importlib.metadata as md

        cls.autogen_version = md.version("autogen-agentchat")
        print(f"\n[glm-e2e-autogen] autogen-agentchat=={cls.autogen_version}")

        # 用当前 converter 代码重新生成产物,并按产物加载方式 import agent.py
        from converter.emitters import EMITTERS
        from converter.skill_loader import load_skill

        ir = load_skill(SKILL_DIR)
        global OUT_AUTOGEN
        OUT_AUTOGEN = artifact_root(cls) / "autogen"
        EMITTERS["autogen"](ir, OUT_AUTOGEN)

        spec = importlib.util.spec_from_file_location("e2e_autogen_agent", OUT_AUTOGEN / "agent.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.agent_module = module

    # ---------- 公共辅助 ----------

    def _ctx(self) -> str:
        return f"[autogen-agentchat=={self.autogen_version}]"

    def _run_chain(self, client_factory, chain: str, protocol: str, model: str):
        """构造客户端 → build_agent(model_client=...) → run(task=问题) → 断言。

        asyncio.wait_for 强制 120s 预算;失败(含超时)重试一次。
        """
        last_exc: Exception | None = None
        for attempt in (1, 2):
            client = client_factory()
            t0 = time.time()
            try:
                agent = self.agent_module.build_agent(model_client=client)

                async def _run():
                    result = await asyncio.wait_for(agent.run(task=QUESTION), timeout=TIMEOUT_S)
                    return result.messages[-1].to_text()

                answer = asyncio.run(_run())
                head = " ".join(answer.split())[:150]
                elapsed = time.time() - t0
                print(f"[glm-e2e-autogen] {chain} | {protocol} | {model} | {elapsed:.1f}s")
                print(f"[glm-e2e-autogen] 回答前 150 字符: {head}")
                low = answer.lower()
                hits = [w for w in MODE_WORDS if w.lower() in low]
                self.assertTrue(
                    hits,
                    f"{self._ctx()} {chain} 回答不含任何 Response Modes 关键词"
                    f" {MODE_WORDS}(SYSTEM_MESSAGE 未真实生效?): {head!r}",
                )
                print(f"[glm-e2e-autogen] {chain} 命中模式词: {hits}")
                return
            except Exception as exc:
                last_exc = exc
                print(f"[glm-e2e-autogen] {chain} attempt {attempt} 失败: "
                      f"{type(exc).__name__}: {str(exc)[:200]}")
            finally:
                try:
                    asyncio.run(client.close())
                except Exception:
                    pass
        self.fail(f"{self._ctx()} {chain} 两次均失败: {last_exc}")

    # ---------- d. autogen × GLM OpenAI 协议 ----------

    def test_d_autogen_glm_openai_protocol(self):
        """OpenAIChatCompletionClient(model=GLM_MODEL, base_url=v4) + 产物 build_agent。"""
        from autogen_ext.models.openai import OpenAIChatCompletionClient

        model = os.environ.get("GLM_MODEL", "glm-4-flash")
        base_url = (os.environ.get("GLM_BASE_URL")
                    or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")

        def factory():
            return OpenAIChatCompletionClient(
                model=model,
                api_key=os.environ["GLM_API_KEY"],
                base_url=base_url,
                model_info=MODEL_INFO,
                max_tokens=1024,
            )

        self._run_chain(factory, "d:autogen×openai", "OpenAI 兼容 /api/paas/v4", model)

    # ---------- e. autogen × GLM Anthropic 协议 ----------

    def test_e_autogen_glm_anthropic_protocol(self):
        """AnthropicChatCompletionClient(model=GLM_ANTHROPIC_MODEL, base_url=anthropic) 同上。

        依赖 autogen-ext[anthropic];anthropic SDK 需 <1.13(1.13.0 的
        messages.create 删掉 temperature,autogen-ext 0.7.5 固定发送会
        TypeError,实测 0.98.1 可用)。装不上则 skipTest 注明。
        """
        try:
            from autogen_ext.models.anthropic import AnthropicChatCompletionClient  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(
                f"autogen-ext[anthropic] 不可 import(autogen 只测 OpenAI 协议路径并注明): {exc}"
            )

        import anthropic as _anthropic
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        # 已知不兼容组合直接注明跳过(而不是抛 TypeError 让链路红)
        major_minor = tuple(int(x) for x in _anthropic.__version__.split(".")[:2])
        if major_minor >= (1, 13):
            raise unittest.SkipTest(
                f"anthropic SDK {_anthropic.__version__} 的 messages.create 已移除 temperature,"
                "与 autogen-ext 0.7.5 固定发送 temperature 不兼容;"
                "请 pip install 'anthropic<1.13'(实测 0.98.1)"
            )

        model = os.environ.get("GLM_ANTHROPIC_MODEL", "glm-5.3-flash")
        base_url = (os.environ.get("GLM_ANTHROPIC_BASE_URL")
                    or "https://open.bigmodel.cn/api/anthropic").rstrip("/")

        def factory():
            return AnthropicChatCompletionClient(
                model=model,
                api_key=os.environ["GLM_API_KEY"],
                base_url=base_url,
                model_info=MODEL_INFO,
                max_tokens=2048,
            )

        self._run_chain(factory, "e:autogen×anthropic", "Anthropic 兼容 /api/anthropic", model)


if __name__ == "__main__":
    unittest.main(verbosity=2)
