"""from_agent_ir 角色对齐升级(按序启发式 → 文本相似度最优分配)的测试。

覆盖(wir 未就绪时整文件 skip,对齐 test_workflow_extract 的条件化 import):
    TestBagOfWords            词袋 token 化:英文停用词/≥2 字符、中文停用字 + 2-gram
    TestMisalignedOrder       错位纠正:task 顺序与 agent 顺序不一致 → 文本匹配
                              胜过按序兜底(task0 描述全是 review 词 → reviewer)
    TestExplicitBindingWins   task.agent 显式绑定优先,不被文本匹配覆盖
    TestNoSimilarityFallback  完全无相似(乱码)回退 positional / none,不崩
    TestScreenplayRegression  真实回归:screenplay_writer 5 agents / 5 tasks
                              无绑定 → 5/5 挂角色(文本匹配或按序兜底均可)
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converter.ir import AgentIR, TaskStep

try:
    from converter.wir import WorkflowIR

    HAS_WIR = True
except Exception:  # ModuleNotFoundError 或 wir 自身 import 失败
    HAS_WIR = False


def make_agents_meta(*specs):
    """specs: (name, role, goal) 三元组 → metadata["agents"] 列表。"""
    return [{"name": n, "role": r, "goal": g} for n, r, g in specs]


WER_AGENTS = make_agents_meta(
    ("writer-agent", "writer",
     "Write the manuscript draft with clear prose and creative storytelling"),
    ("editor-agent", "editor",
     "Edit the draft for grammar, style and structural coherence"),
    ("reviewer-agent", "reviewer",
     "Review the final text and give critical feedback on quality"),
)


@unittest.skipUnless(HAS_WIR, "converter/wir.py 未就绪")
class TestBagOfWords(unittest.TestCase):
    """_bag_of_words 的 token 化规则(设计契约:小写/停用词/≥2 字符/CJK 2-gram)。"""

    def test_english_stopwords_and_min_length(self):
        from converter.wir import _bag_of_words

        tokens = _bag_of_words("The Write and Edit of a dot to In For With")
        self.assertEqual(tokens, {"write", "edit", "dot"})
        # 单字符词与停用词全部剔除
        self.assertNotIn("a", tokens)
        self.assertNotIn("the", tokens)

    def test_cjk_stopword_chars_split_and_bigram(self):
        from converter.wir import _bag_of_words

        # 中文停用字(的/与/和/在/对)当分隔符,剩余连续段取 2-gram
        tokens = _bag_of_words("审阅文稿与编辑稿件")
        self.assertEqual(tokens, {"审阅", "阅文", "文稿", "编辑", "辑稿", "稿件"})
        self.assertNotIn("与编", tokens)
        # 孤立单字不保留
        self.assertEqual(_bag_of_words("写"), set())

    def test_jaccard_empty_side_is_zero(self):
        from converter.wir import _jaccard, _bag_of_words

        self.assertEqual(_jaccard(set(), {"a"}), 0.0)
        self.assertEqual(_jaccard(_bag_of_words(""), {"a"}), 0.0)
        self.assertEqual(_jaccard({"a", "b"}, {"b", "c"}), 1 / 3)


@unittest.skipUnless(HAS_WIR, "converter/wir.py 未就绪")
class TestMisalignedOrder(unittest.TestCase):
    """错位纠正:agents 按 writer/editor/reviewer 排,task 顺序打乱
    (task0 全 review 词、task1 全 write 词、task2 全 edit 词)——
    旧按序对齐会把 writer 挂到 task0(错位),文本匹配应全局最优纠偏。"""

    def setUp(self):
        self.ir = AgentIR(
            name="misaligned-crew",
            system_prompt="Multi-agent writing crew.",
            metadata={"agents": WER_AGENTS},
            tasks=[
                TaskStep(name="Review chapter",
                         description="Review the finished chapter and provide "
                                     "critical feedback on quality issues."),
                TaskStep(name="Write draft",
                         description="Write the first draft manuscript with "
                                     "creative prose."),
                TaskStep(name="Edit draft",
                         description="Edit the draft to fix grammar and style "
                                     "problems."),
            ],
        )
        self.w = WorkflowIR.from_agent_ir(self.ir)

    def test_text_match_beats_positional(self):
        self.assertEqual(self.w.metadata.get("role_alignment"), "text-match")
        # task0(描述全是 review 词)→ reviewer,而非按序错配的 writer
        self.assertTrue(self.w.nodes[0].prompt.startswith("As reviewer."),
                        f"task0 应挂 reviewer,实际: {self.w.nodes[0].prompt[:40]}")
        self.assertFalse(self.w.nodes[0].prompt.startswith("As writer."),
                         "按序错位(writer)不应再出现")
        self.assertTrue(self.w.nodes[1].prompt.startswith("As writer."))
        self.assertTrue(self.w.nodes[2].prompt.startswith("As editor."))

    def test_all_nodes_carry_role_prefix(self):
        self.assertEqual(
            sum(1 for n in self.w.nodes if n.prompt.startswith("As ")), 3)


@unittest.skipUnless(HAS_WIR, "converter/wir.py 未就绪")
class TestExplicitBindingWins(unittest.TestCase):
    """task.agent 显式绑定是最高优先级:描述文本偏向另一 agent 也不被
    文本匹配覆盖;且显式绑定的 agent 列被占用,不再参与文本匹配。"""

    def test_explicit_not_overridden(self):
        ir = AgentIR(
            name="explicit-crew",
            system_prompt="Explicit binding wins.",
            metadata={"agents": make_agents_meta(
                ("writer-agent", "writer",
                 "Write the manuscript draft with clear prose and creative storytelling"),
                ("editor-agent", "editor",
                 "Edit the draft for grammar, style and structural coherence"),
            )},
            tasks=[
                # 显式绑 writer,但描述全是 edit 词 → 文本匹配本会选 editor
                TaskStep(name="Bound task", agent="writer-agent",
                         description="Edit the draft for grammar and style."),
                # 未绑定,edit 词 → 文本匹配到未被占用的 editor
                TaskStep(name="Free task",
                         description="Edit the second draft for grammar and "
                                     "style improvements."),
            ],
        )
        w = WorkflowIR.from_agent_ir(ir)
        self.assertTrue(w.nodes[0].prompt.startswith("As writer."),
                        f"显式绑定应保留 writer,实际: {w.nodes[0].prompt[:40]}")
        self.assertFalse(w.nodes[0].prompt.startswith("As editor."))
        self.assertTrue(w.nodes[1].prompt.startswith("As editor."))
        self.assertEqual(w.metadata.get("role_alignment"), "explicit")


@unittest.skipUnless(HAS_WIR, "converter/wir.py 未就绪")
class TestNoSimilarityFallback(unittest.TestCase):
    """乱码 task 与任何 agent 无词面相似 → 整体回退,不崩。"""

    def test_zero_similarity_equal_counts_positional(self):
        ir = AgentIR(
            name="gibberish-crew",
            system_prompt="No overlap at all.",
            metadata={"agents": WER_AGENTS},
            tasks=[
                TaskStep(name="Qqq", description="qqq zzxx vvv kkk"),
                TaskStep(name="Www", description="wwvv uuuu tttt ssss"),
                TaskStep(name="Eee", description="eeee rrrr nnnn mmmm"),
            ],
        )
        w = WorkflowIR.from_agent_ir(ir)  # 不崩
        self.assertEqual(len(w.nodes), 3)
        self.assertEqual(w.metadata.get("role_alignment"), "positional")
        # 数量相等 → 按序兜底(与历史行为一致)
        self.assertTrue(w.nodes[0].prompt.startswith("As writer."))
        self.assertTrue(w.nodes[1].prompt.startswith("As editor."))
        self.assertTrue(w.nodes[2].prompt.startswith("As reviewer."))

    def test_zero_similarity_unequal_counts_none(self):
        ir = AgentIR(
            name="unequal-crew",
            system_prompt="Counts differ, no positional.",
            metadata={"agents": WER_AGENTS[:2]},  # 2 agents vs 3 tasks
            tasks=[
                TaskStep(name="Qqq", description="qqq zzxx vvv kkk"),
                TaskStep(name="Www", description="wwvv uuuu tttt ssss"),
                TaskStep(name="Eee", description="eeee rrrr nnnn mmmm"),
            ],
        )
        w = WorkflowIR.from_agent_ir(ir)  # 不崩
        self.assertEqual(len(w.nodes), 3)
        self.assertEqual(w.metadata.get("role_alignment"), "none")
        self.assertEqual(
            [n.prompt.startswith("As ") for n in w.nodes],
            [False, False, False],
            "数量不等且无相似 → 不挂角色",
        )

    def test_no_agents_metadata_none(self):
        ir = AgentIR(
            name="no-agent-meta",
            system_prompt="No agents metadata.",
            tasks=[TaskStep(name="Only", description="Just do the write work.")],
        )
        w = WorkflowIR.from_agent_ir(ir)
        self.assertEqual(w.metadata.get("role_alignment"), "none")
        self.assertFalse(w.nodes[0].prompt.startswith("As "))


@unittest.skipUnless(HAS_WIR, "converter/wir.py 未就绪")
class TestScreenplayRegression(unittest.TestCase):
    """真实回归:crewAI-examples screenplay_writer(5 agents / 5 tasks,
    tasks.yaml 无 agent 绑定)仍 5/5 挂角色前缀(文本匹配或按序兜底均可)。"""

    AGENTS = make_agents_meta(
        ("spamfilter", "spamfilter", "Decide whether a text is spam or not."),
        ("analyse", "analyse",
         "You will distill all arguments from all discussion members and find "
         "the consensus points and unclear points."),
        ("scriptwriter", "scriptwriter",
         "Turn a conversation into a movie script with proper scene headings "
         "and dialogue."),
        ("formatter", "formatter",
         "Format the text as asked by the user, keeping the content unchanged."),
        ("scorer", "scorer",
         "You score a dialogue assessing various aspects like creativity, "
         "coherence and dramatic quality."),
    )

    def test_five_tasks_all_rolemounted(self):
        ir = AgentIR(
            name="screenplay-writer",
            display_name="Screenplay Writer",
            system_prompt="Turn conversations into movie scripts.",
            metadata={"agents": self.AGENTS},
            tasks=[
                TaskStep(name="Filter spam",
                         description="Check the incoming text and decide whether "
                                     "it is spam or an advertisement."),
                TaskStep(name="Analyse discussion",
                         description="Distill all arguments from the discussion "
                                     "members and mark consensus and unclear points."),
                TaskStep(name="Write script",
                         description="Turn the conversation into a movie script "
                                     "with scene headings and dialogue."),
                TaskStep(name="Format output",
                         description="Format the script text as asked, keeping "
                                     "the content unchanged."),
                TaskStep(name="Score dialogue",
                         description="Score the dialogue assessing creativity, "
                                     "coherence and dramatic aspects."),
            ],
        )
        w = WorkflowIR.from_agent_ir(ir)
        self.assertEqual(len(w.nodes), 5)
        self.assertIn(w.metadata.get("role_alignment"),
                      ("text-match", "positional"))
        self.assertEqual(
            sum(1 for n in w.nodes if n.prompt.startswith("As ")), 5,
            "5 个节点应全部挂上角色前缀")


if __name__ == "__main__":
    unittest.main()
