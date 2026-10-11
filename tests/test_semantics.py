"""语义级指标 S_struct / S_terms 测试(条件化 import 风格,见 test_convert.py)。

覆盖:
    TestSemanticSynthetic   三档 ir_out 方向验证:完全相同(S=1)/ 步骤乱序但齐全
                            (S_struct<1, S_terms=1)/ 否定词被删(S_terms<1,数字类保留)
    TestRealChainMermaid    真实链抽测:examples skill → mermaid-workflow
                            roundtrip 的 S_struct/S_terms 均为 1.0
                            (Source Context 保全文 + tasks 结构保真)
    TestRunEvalSmoke        run_eval 集成冒烟:单 corpus × 2 target,
                            确认 S_struct/S_terms 两列出现在汇总表与结果行
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                # converter 包 / evaluation 命名空间包
sys.path.insert(0, str(ROOT / "evaluation"))  # metrics / semantics 顶层模块名

from converter.ir import AgentIR, KnowledgeDoc, TaskStep  # noqa: E402

try:
    from evaluation.semantics import semantic_metrics
except ImportError:  # pragma: no cover - 直接以脚本运行本文件时的兜底
    from semantics import semantic_metrics  # type: ignore

EXAMPLE_SKILL = ROOT / "examples" / "agent-fullcycle-engineering"

# 数字/量词、限定词、否定、强命令、专有名词五类俱全的正文
BASE_PROMPT = (
    "# Demo\n\n"
    "You MUST call at most 3 tools and no more than 5 files.\n"
    "Do not delete data; never skip tests. 不要删除备份,禁止关闭审计,不能跳过评审。\n"
    "至少保存 2 份报告,最多重试 3 次,不超过 9 个步骤。\n"
    "Use CrewAI or LangChain with RAG. The API returns 99.5% accuracy.\n"
    "You must always finish 三步之内,九点前完成。\n"
)

# 否定词全删(do not/never/不要/禁止/不能),其余(数字、限定词、专有名词)不动
NEGATION_STRIPPED_PROMPT = (
    "# Demo\n\n"
    "You MUST call at most 3 tools and no more than 5 files.\n"
    "delete data; skip tests. 删除备份,关闭审计,跳过评审。\n"
    "至少保存 2 份报告,最多重试 3 次,不超过 9 个步骤。\n"
    "Use CrewAI or LangChain with RAG. The API returns 99.5% accuracy.\n"
    "You must always finish 三步之内,九点前完成。\n"
)


def make_semantic_ir() -> AgentIR:
    """9 步 tasks + 五类语义关键 token 俱全的标准测试 IR。"""
    return AgentIR(
        name="demo-agent",
        display_name="Demo Agent",
        description="Demo skill for semantic metrics",
        system_prompt=BASE_PROMPT,
        knowledge=[
            KnowledgeDoc(filename="guide.md", title="Guide", content="# Guide\ncontent")
        ],
        tasks=[TaskStep(name=f"Step {i}", description=f"do step {i}")
               for i in range(1, 10)],
        metadata={"note": "unittest"},
    )


class TestSemanticSynthetic(unittest.TestCase):
    """三档 ir_out:指标方向必须正确(相同=1 / 乱序只降 S_struct / 删否定只降 S_terms)。"""

    def test_identical_ir_scores_one(self):
        ir_in = make_semantic_ir()
        ir_out = AgentIR.from_dict(ir_in.to_dict())
        result = semantic_metrics(ir_in=ir_in, ir_out=ir_out)
        self.assertEqual(result["S_struct"], 1.0)
        self.assertEqual(result["S_terms"], 1.0)
        self.assertEqual(set(result["terms_detail"]),
                         {"numbers", "qualifiers", "negation", "strong_cmd", "proper_nouns"})
        for detail in result["terms_detail"].values():
            self.assertEqual(detail["score"], 1.0)
            self.assertEqual(detail["lost"], [])

    def test_shuffled_tasks_drop_struct_only(self):
        ir_in = make_semantic_ir()
        ir_out = AgentIR.from_dict(ir_in.to_dict())
        ir_out.tasks.reverse()  # 步骤乱序但齐全:LCS=1/9
        result = semantic_metrics(ir_in=ir_in, ir_out=ir_out)
        self.assertLess(result["S_struct"], 1.0)
        self.assertGreater(result["S_struct"], 0.6)  # 其余分量仍满分
        self.assertEqual(result["S_terms"], 1.0)     # 正文未动,术语保留满格
        # 方向:乱序的 S_struct 必须低于完全相同的一档
        self.assertLess(result["S_struct"],
                        semantic_metrics(ir_in, AgentIR.from_dict(ir_in.to_dict()))["S_struct"])

    def test_deleted_negation_drops_terms_only(self):
        ir_in = make_semantic_ir()
        ir_out = AgentIR.from_dict(ir_in.to_dict())
        ir_out.system_prompt = NEGATION_STRIPPED_PROMPT
        result = semantic_metrics(ir_in=ir_in, ir_out=ir_out)
        self.assertEqual(result["S_struct"], 1.0)     # 结构未动
        self.assertLess(result["S_terms"], 1.0)
        self.assertEqual(result["terms_detail"]["numbers"]["score"], 1.0,
                         "数字类应全部保留")
        self.assertLess(result["terms_detail"]["negation"]["score"], 1.0)
        lost = result["terms_detail"]["negation"]["lost"]
        self.assertIn("do not", lost)
        self.assertIn("不要", lost)
        self.assertNotIn("no", lost)  # "no more than" 仍在正文,否定类仅部分丢失
        self.assertGreater(result["S_terms"], 0.7)    # 只降一类,等权平均不塌方


class TestRealChainMermaid(unittest.TestCase):
    """examples skill → mermaid-workflow roundtrip:两指标都应为 1.0。"""

    def test_example_skill_mermaid_roundtrip(self):
        try:
            from converter.emitters.mermaid_workflow import emit_mermaid_workflow
            from converter.parsers.mermaid_workflow import parse_mermaid_workflow
            from converter.skill_loader import load_skill
            from converter.skill_writer import write_skill
        except Exception:
            self.skipTest("mermaid emitter/parser / skill_loader/writer not available yet")
        if not (EXAMPLE_SKILL / "SKILL.md").is_file():
            self.skipTest("examples/agent-fullcycle-engineering 不存在")
        ir_in = load_skill(EXAMPLE_SKILL)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            agent_dir = work / "mermaid"
            emit_mermaid_workflow(ir_in, agent_dir)
            ir_mid = parse_mermaid_workflow(agent_dir)
            skill_out = work / "roundtrip.skill"
            write_skill(ir_mid, skill_out, copy_scripts_from=EXAMPLE_SKILL)
            ir_out = load_skill(skill_out)
        result = semantic_metrics(ir_in=ir_in, ir_out=ir_out)
        self.assertEqual(result["S_struct"], 1.0,
                         f"结构应保真: {result}")
        self.assertEqual(result["S_terms"], 1.0,
                         f"Source Context 应保全术语: {result['terms_detail']}")


class TestRunEvalSmoke(unittest.TestCase):
    """run_eval 集成冒烟:单 corpus × 2 target,S_struct/S_terms 两列出现且为 1.0。"""

    def _import_run_eval(self):
        try:
            from evaluation import run_eval
            return run_eval
        except Exception:
            self.skipTest("run_eval not importable")

    def test_columns_present_in_summary(self):
        run_eval = self._import_run_eval()
        if "crewai" not in run_eval.EMITTERS or "mermaid-workflow" not in run_eval.PARSERS:
            self.skipTest("EMITTERS/PARSERS 缺键(并行线程未落盘)")
        if not (EXAMPLE_SKILL / "SKILL.md").is_file():
            self.skipTest("examples/agent-fullcycle-engineering 不存在")
        old_corpora, old_targets = run_eval.CORPORA, run_eval.TARGETS
        run_eval.CORPORA = [("S1_real", EXAMPLE_SKILL)]
        run_eval.TARGETS = ["crewai", "mermaid-workflow"]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                forward_rows, roundtrip_rows, notes = run_eval.run_matrix(Path(tmp))
            self.assertEqual(len(roundtrip_rows), 2)
            for row in roundtrip_rows:
                self.assertEqual(row["status"], "ok", row.get("error"))
                self.assertIn("S_struct", row["metrics"])
                self.assertIn("S_terms", row["metrics"])
                self.assertIn("terms_detail", row)
            summary = run_eval.summarize(forward_rows, roundtrip_rows)
            md = run_eval.build_markdown(summary, notes, "unittest")
            self.assertIn("S_struct", md)
            self.assertIn("S_terms", md)
            for target in ("crewai", "mermaid-workflow"):
                self.assertEqual(summary["per_target"][target]["S_struct"], 1.0)
                self.assertEqual(summary["per_target"][target]["S_terms"], 1.0)
        finally:
            run_eval.CORPORA, run_eval.TARGETS = old_corpora, old_targets


if __name__ == "__main__":
    unittest.main()
