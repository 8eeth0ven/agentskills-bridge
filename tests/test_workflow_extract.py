"""converter.workflow_extract 的测试。

纯函数部分(extract_workflow_steps)无条件可跑;skill_to_workflow_ir 依赖
converter/wir.py(并行线程提供),未就绪时 skipTest。
"""

import tempfile
import unittest
from pathlib import Path

from converter.workflow_extract import extract_workflow_steps, skill_to_workflow_ir

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SKILL = ROOT / "examples" / "agent-fullcycle-engineering"

try:
    import converter.wir as _wir  # noqa: F401

    HAS_WIR = True
except Exception:  # ModuleNotFoundError 或 wir 自身 import 失败
    HAS_WIR = False


class TestExtractRealSkill(unittest.TestCase):
    """真实 skill:examples/agent-fullcycle-engineering(## Full Lifecycle Workflow,1.-9.)。"""

    def test_fullcycle_nine_steps(self):
        if not EXAMPLE_SKILL.is_dir():
            self.skipTest("example skill not available")
        from converter.skill_loader import load_skill

        ir = load_skill(EXAMPLE_SKILL)
        steps = extract_workflow_steps(ir.system_prompt)

        self.assertEqual(len(steps), 9, "应识别出 9 个步骤")
        self.assertIn("Clarify", steps[0]["title"])
        # 第 3 步:标题 + 缩进子项都归正文,且不吞下一项
        self.assertEqual(steps[2]["title"], "Choose the simplest architecture")
        self.assertIn("simplest architecture", steps[2]["body"])
        self.assertIn("Use deterministic code", steps[2]["body"])
        self.assertNotIn("Design contracts", steps[2]["body"])
        # 列表后的"For coding workflow…"散文段不得混入第 9 步
        self.assertNotIn("For coding workflow", steps[-1]["body"])
        self.assertIn("Release in stages", steps[-1]["title"])


class TestExtractSynthetic(unittest.TestCase):
    """合成样例:中文节、编号变体、代码块免疫、Step 标题、兜底形态。"""

    def test_chinese_workflow_section(self):
        md = (
            "# 指南\n\n"
            "## 工作流程\n\n"
            "按顺序执行:\n\n"
            "1. 收集需求:先访谈业务方\n"
            "2. 分析需求:输出用例\n"
            "3. 实施改造:改代码并测试\n\n"
            "## 其他\n\n无关内容\n"
        )
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["title"], "收集需求")
        self.assertEqual(steps[1]["title"], "分析需求")
        self.assertEqual(steps[2]["title"], "实施改造")
        self.assertIn("先访谈业务方", steps[0]["body"])

    def test_numbering_variants(self):
        # 1、全角括号（2）步骤三 等混合形态
        md = (
            "## Recommended Workflow\n\n"
            "1、收集:第一步\n"
            "（2）分析:第二步\n"
            "步骤三、实施:第三步\n"
        )
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 3, "中英编号/全半角括号都应识别")
        self.assertEqual(steps[0]["title"], "收集")
        self.assertEqual(steps[1]["title"], "分析")
        self.assertEqual(steps[2]["title"], "实施")

    def test_code_block_numbers_ignored(self):
        md = (
            "## Workflow\n\n"
            "1. Prepare:准备环境\n"
            "2. Build:构建产物\n"
            "3. Verify:验证结果\n\n"
            "```bash\n"
            "# 1. fake step\n"
            "1. fake numbered item\n"
            "2. fake second\n"
            "3. fake third\n"
            "```\n"
        )
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 3)
        for s in steps:
            self.assertNotIn("fake", s["title"])
            self.assertNotIn("fake", s["body"])

    def test_indented_code_block_attached_to_step(self):
        # 围栏开栏线缩进比列表项更深 → 代码块是该步骤的正文;块内编号不当步骤
        md = (
            "## Workflow\n\n"
            "1. Install:安装\n"
            "   ```bash\n"
            "   pip install x\n"
            "   # 1. fake\n"
            "   ```\n"
            "2. Run:运行\n"
        )
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 2)
        self.assertIn("pip install x", steps[0]["body"])
        self.assertNotIn("Run", steps[0]["body"])
        self.assertEqual(steps[1]["title"], "Run")

    def test_only_code_block_numbers_yields_empty(self):
        md = "# T\n\n```text\n1. a\n2. b\n3. c\n```\n"
        self.assertEqual(extract_workflow_steps(md), [])

    def test_step_heading_sequence(self):
        md = (
            "# Doc\n\n"
            "## Step 1: Setup\n\n"
            "install deps\n\n"
            "## Step 2: Run\n\n"
            "do stuff\n\n"
            "### notes\nmore\n\n"
            "## Step 3: Verify\n\n"
            "check output\n"
        )
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["title"], "Setup")
        self.assertEqual(steps[1]["title"], "Run")
        self.assertEqual(steps[2]["title"], "Verify")
        self.assertIn("install deps", steps[0]["body"])
        self.assertIn("notes", steps[1]["body"], "Step 标题下的子标题应留在正文里")

    def test_fallback_numbered_list_without_section(self):
        # 无 workflow 节,但全文存在连续 ≥3 项编号列表(形态 b)
        md = "# Guide\n\nSome intro prose.\n\n1. First: do a\n2. Second: do b\n3. Third: do c\n"
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["title"], "First")

    def test_plain_paragraphs_yield_empty(self):
        md = "# Overview\n\nSome prose here.\n\nMore prose follows.\n\n- a bullet\n- another\n"
        self.assertEqual(extract_workflow_steps(md), [])

    def test_version_number_not_a_step(self):
        md = "## Workflow\n\n1. Alpha: first\n2. Beta: second\n\nUse 1.5 million tokens.\n"
        steps = extract_workflow_steps(md)
        self.assertEqual(len(steps), 2)
        self.assertNotIn("million", steps[-1]["body"])


class TestSkillToWorkflowIR(unittest.TestCase):
    """skill_to_workflow_ir:wir 就绪时验证节点/边/metadata;未就绪时 skipTest。"""

    def test_real_skill_nodes_and_edges(self):
        if not HAS_WIR:
            self.skipTest("wir pending")
        if not EXAMPLE_SKILL.is_dir():
            self.skipTest("example skill not available")
        wf = skill_to_workflow_ir(EXAMPLE_SKILL)
        self.assertGreaterEqual(len(wf.nodes), 2)
        self.assertEqual(len(wf.nodes), 9)
        self.assertEqual(len(wf.edges), 8)
        self.assertEqual(wf.edges[0].source, wf.nodes[0].id)
        self.assertEqual(wf.edges[0].target, wf.nodes[1].id)
        self.assertEqual(wf.edges[-1].target, wf.nodes[-1].id)
        self.assertEqual(wf.name, "agent-fullcycle-engineering")
        self.assertEqual(wf.metadata.get("steps_extracted"), 9)
        self.assertTrue(all(n.prompt for n in wf.nodes), "每个节点都应有 prompt 正文")

    def test_chinese_unique_node_ids(self):
        if not HAS_WIR:
            self.skipTest("wir pending")
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / "SKILL.md").write_text(
                "---\nname: cn-flow\ndescription: 测试\n---\n\n"
                "## 工作流程\n\n1. 收集需求:访谈\n2. 分析需求:建模\n3. 实施改造:编码\n",
                encoding="utf-8",
            )
            wf = skill_to_workflow_ir(skill)
            ids = [n.id for n in wf.nodes]
            self.assertEqual(len(ids), 3)
            self.assertEqual(len(set(ids)), 3, "中文标题 slug 为空时应用 step-N 兜底且唯一")
            self.assertTrue(all(i for i in ids))
            self.assertEqual(wf.metadata.get("steps_extracted"), 3)

    def test_import_error_when_wir_pending(self):
        if HAS_WIR:
            self.skipTest("wir already present")
        with self.assertRaises(ImportError) as cm:
            skill_to_workflow_ir(EXAMPLE_SKILL)
        self.assertIn("wir pending", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
