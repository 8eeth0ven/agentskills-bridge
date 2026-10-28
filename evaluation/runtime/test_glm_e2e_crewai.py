"""crewai 产物 × GLM 双协议真实 LLM 端到端测试(真实 API,不打桩)。

覆盖三条链(对应任务 a/b/c):
    a. test_a_crewai_glm_openai_protocol —— crewai 靶 + GLM v4 OpenAI 兼容端点
       (LLM(model="openai/<glm>", api_key=..., api_base=.../api/paas/v4))。
    b. test_b_crewai_glm_anthropic_protocol —— crewai 靶 + GLM anthropic 兼容端点
       (LLM(model=<glm>, provider="anthropic", api_key=..., base_url=.../api/anthropic))。
    c. test_c_crewai_skills_glm_openai_protocol —— crewai-skills 靶,Agent 挂
       skills=["<out>/skills"] 目录发现式引用,真实跑一轮(证明 skills 目录
       运行时真实加载)。

实测环境(2026-10-11,crewai==1.15.27):
- crewai 1.15.x 不再捆绑 litellm:LLM() 路由到内置原生 provider。
  OpenAI 协议:`openai/` 前缀 + api_base 自动判 custom_openai,命中
  OpenAICompletion(base_url=api_base);
  Anthropic 协议:非 claude-* 模型名(`anthropic/<glm>` 写法)不会命中原生
  路由而掉到未安装的 litellm 回退,必须显式 provider="anthropic"(需要
  pip install anthropic 提供 crewai 原生 AnthropicCompletion)。
- 断言依据:examples/agent-fullcycle-engineering 的 SKILL.md 含
  "## Response Modes"(Beginner/Interview/Project delivery/Debugging)。
  backstory/SKILL.md 正文真实生效时,回答必含其中任一模式词。

运行方式(需先通过环境变量设置 GLM_API_KEY 等):
    python3 -m unittest evaluation.runtime.test_glm_e2e_crewai -v

无 GLM_API_KEY 时整类 skipTest(密钥缺失不算失败)。
"""

from __future__ import annotations

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
OUT_CREWAI: Path
OUT_CREWAI_SKILLS: Path
SKILL_NAME = "agent-fullcycle-engineering"

QUESTION = "这个 skill 有哪几种 Response Modes?只列名字"
MODE_WORDS = ("Beginner", "Interview", "Project delivery", "Debugging")
TIMEOUT_S = 120  # 单次调用预算(LLM timeout 110s + 余量),失败重试一次



class GLME2ECrewaiTest(unittest.TestCase):
    """crewai 转换产物 × GLM 双协议真实推理(真实 kickoff,断言模式词)。"""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("GLM_API_KEY"):
            raise unittest.SkipTest("GLM_API_KEY 未设置,整类跳过")
        try:
            import crewai  # noqa: F401
            import yaml  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"crewai/pyyaml 不可 import,整类跳过: {exc}")

        import importlib.metadata as md

        cls.crewai_version = md.version("crewai")
        print(f"\n[glm-e2e-crewai] crewai=={cls.crewai_version}")

        # 用当前 converter 代码重新生成产物:本测试同时验证最新 emitter 接线
        from converter.emitters import EMITTERS
        from converter.skill_loader import load_skill

        ir = load_skill(SKILL_DIR)
        global OUT_CREWAI, OUT_CREWAI_SKILLS
        artifacts = artifact_root(cls)
        OUT_CREWAI = artifacts / "crewai"
        OUT_CREWAI_SKILLS = artifacts / "crewai-skills"
        EMITTERS["crewai"](ir, OUT_CREWAI)
        EMITTERS["crewai-skills"](ir, OUT_CREWAI_SKILLS)

    # ---------- 公共辅助 ----------

    def _ctx(self) -> str:
        return f"[crewai=={self.crewai_version}]"

    def _cfg(self, out_dir: Path):
        """读产物的 agents.yaml/tasks.yaml,返回 (agent_entry, task_entry)。"""
        import yaml

        agents = yaml.safe_load((out_dir / "config" / "agents.yaml").read_text(encoding="utf-8"))
        tasks = yaml.safe_load((out_dir / "config" / "tasks.yaml").read_text(encoding="utf-8"))
        return agents[SKILL_NAME], tasks[f"{SKILL_NAME}_task"]

    def _kickoff(self, llm, out_dir: Path, skills=None):
        """按产物配置构造 Agent/Task/Crew 并 kickoff,失败重试一次。

        问题描述刻意用业务问题(而非 tasks.yaml 的 description)以证明
        backstory/SYSTEM_MESSAGE 全文真实进入模型;Task 骨架取自产物。
        """
        from crewai import Agent, Crew, Process, Task

        agent_entry, task_entry = self._cfg(out_dir)
        last_exc: Exception | None = None
        for attempt in (1, 2):
            t0 = time.time()
            try:
                agent_kwargs = dict(
                    role=agent_entry["role"],
                    goal=agent_entry["goal"],
                    backstory=agent_entry["backstory"],
                    llm=llm,
                    verbose=False,
                )
                if skills is not None:
                    agent_kwargs["skills"] = list(skills)
                agent = Agent(**agent_kwargs)
                if skills is not None:
                    loaded = getattr(agent, "skills", None) or []
                    self.assertTrue(
                        loaded,
                        f"{self._ctx()} skills={skills} 构造期解析出 0 个技能(运行时未真实加载)",
                    )
                task = Task(
                    description=QUESTION,
                    expected_output=task_entry["expected_output"],
                    agent=agent,
                )
                crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)
                result = crew.kickoff()
                return str(getattr(result, "raw", result) or ""), time.time() - t0, attempt
            except Exception as exc:  # 网络抖动/限流:重试一次后仍失败才判败
                last_exc = exc
                print(f"[glm-e2e-crewai] attempt {attempt} 失败: {type(exc).__name__}: {exc}")
        self.fail(f"{self._ctx()} kickoff 两次均失败: {last_exc}")

    def _assert_modes(self, chain: str, protocol: str, model: str, answer: str, elapsed: float):
        """打印链路信息与回答前 150 字符,断言含任一 Response Mode 词。"""
        head = " ".join(answer.split())[:150]
        print(f"[glm-e2e-crewai] {chain} | {protocol} | {model} | {elapsed:.1f}s")
        print(f"[glm-e2e-crewai] 回答前 150 字符: {head}")
        low = answer.lower()
        hits = [w for w in MODE_WORDS if w.lower() in low]
        self.assertTrue(
            hits,
            f"{self._ctx()} {chain} 回答不含任何 Response Modes 关键词"
            f" {MODE_WORDS}(backstory/SKILL.md 未真实生效?): {head!r}",
        )
        print(f"[glm-e2e-crewai] {chain} 命中模式词: {hits}")

    # ---------- a. crewai 靶 × GLM OpenAI 协议 ----------

    def test_a_crewai_glm_openai_protocol(self):
        """LLM(openai/<glm-4-flash>, api_base=v4) + crewai 产物 kickoff。"""
        from crewai import LLM

        llm = LLM(
            model="openai/" + os.environ.get("GLM_MODEL", "glm-4-flash"),
            api_key=os.environ["GLM_API_KEY"],
            api_base=(os.environ.get("GLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
            max_tokens=1024,
            timeout=TIMEOUT_S - 10,
        )
        answer, elapsed, _ = self._kickoff(llm, OUT_CREWAI)
        self._assert_modes("a:crewai×openai", "OpenAI 兼容 /api/paas/v4",
                           os.environ.get("GLM_MODEL", "glm-4-flash"), answer, elapsed)

    # ---------- b. crewai 靶 × GLM Anthropic 协议 ----------

    def test_b_crewai_glm_anthropic_protocol(self):
        """LLM(provider="anthropic", base_url=/api/anthropic) + crewai 产物 kickoff。

        crewai 1.15.27 实测:`anthropic/<model>` 前缀写法对非 claude-* 模型
        会掉到未安装的 litellm 回退(ImportError),必须显式 provider="anthropic"
        走原生 AnthropicCompletion;需要 venv 内 pip install anthropic。
        max_tokens 给 2048:glm-5.3-flash 经 anthropic 协议可能带思考开销。
        """
        try:
            from crewai.llms.providers.anthropic.completion import AnthropicCompletion  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(
                f"crewai 原生 Anthropic provider 不可用(pip install anthropic): {exc}"
            )

        from crewai import LLM

        llm = LLM(
            model=os.environ.get("GLM_ANTHROPIC_MODEL", "glm-5.3-flash"),
            provider="anthropic",
            api_key=os.environ["GLM_API_KEY"],
            base_url=(os.environ.get("GLM_ANTHROPIC_BASE_URL")
                      or "https://open.bigmodel.cn/api/anthropic").rstrip("/"),
            max_tokens=2048,
            timeout=TIMEOUT_S - 10,
        )
        answer, elapsed, _ = self._kickoff(llm, OUT_CREWAI)
        self._assert_modes("b:crewai×anthropic", "Anthropic 兼容 /api/anthropic",
                           os.environ.get("GLM_ANTHROPIC_MODEL", "glm-5.3-flash"), answer, elapsed)

    # ---------- c. crewai-skills 靶 × GLM(OpenAI 协议) ----------

    def test_c_crewai_skills_glm_openai_protocol(self):
        """Agent 挂 skills=["<out>/skills"] 真实跑一轮,证明技能目录运行时加载。

        skills 用绝对路径(产物 YAML 里是相对路径 "./skills",Agent 构造时
        相对 cwd 解析;测试环境直接给绝对路径等价)。断言两层:
        1) Agent 构造期 skills 解析出 >=1 个技能(METADATA 级真实加载);
        2) 回答含 Response Modes 词(backstory 精简版前 1200 字符含
           "## Response Modes" 节,技能命中时 load_skill 亦提供全文)。
        """
        from crewai import LLM

        llm = LLM(
            model="openai/" + os.environ.get("GLM_MODEL", "glm-4-flash"),
            api_key=os.environ["GLM_API_KEY"],
            api_base=(os.environ.get("GLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
            max_tokens=1024,
            timeout=TIMEOUT_S - 10,
        )
        answer, elapsed, _ = self._kickoff(
            llm, OUT_CREWAI_SKILLS, skills=[str(OUT_CREWAI_SKILLS / "skills")]
        )
        self._assert_modes("c:crewai-skills×openai", "OpenAI 兼容 /api/paas/v4",
                           os.environ.get("GLM_MODEL", "glm-4-flash"), answer, elapsed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
