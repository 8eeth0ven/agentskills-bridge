"""WorkflowIR + mermaid-workflow 形态测试(第三形态:n8n 由并行线程提供)。

覆盖:
    TestWorkflowIR          WIR 序列化 roundtrip、from_agent_ir 分步成链、
                            to_agent_ir 多节点 "## Step N:" 合并
    TestMermaidEmit         emit 产物结构:mermaid 块节点/边数、知识拷贝、README
    TestMermaidParse        parse 回 name / prompt 关键句 / knowledge / source_format
    TestMermaidRoundtrip    AgentIR -> mermaid -> AgentIR 的 name/knowledge 保真
    TestWorkflowRegistry    EMITTERS/PARSERS 注册("n8n" 未落盘时不断言)
    TestWorkflowValidators  metrics.VALIDATORS 的 v_n8n / v_mermaid_workflow
"""

import importlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converter.ir import AgentIR, KnowledgeDoc, TaskStep, slugify
from converter.wir import WorkflowEdge, WorkflowIR, WorkflowNode


def make_pipeline_ir() -> AgentIR:
    """多 task 测试 IR:from_agent_ir 应生成分步节点与串联边。"""
    return AgentIR(
        name="pipeline-agent",
        display_name="Pipeline Agent",
        description="Multi-step pipeline demo",
        system_prompt="You are a pipeline agent.",
        knowledge=[
            KnowledgeDoc(filename="guide.md", title="Guide", content="# Guide\nstuff"),
            KnowledgeDoc(filename="extra.md", title="Extra", content="# Extra\nmore"),
        ],
        tasks=[
            TaskStep(name="Collect Input", description="Gather user input.",
                     expected_output="A requirements list."),
            TaskStep(name="Draft Plan", description="Write the plan.",
                     expected_output="A plan."),
        ],
        metadata={"note": "unittest"},
    )


class TestWorkflowIR(unittest.TestCase):
    def test_to_from_dict_roundtrip(self):
        w = WorkflowIR(
            name="demo-flow",
            display_name="Demo Flow",
            description="d",
            system_prompt="s",
            nodes=[WorkflowNode(id="a", name="A", prompt="pa"),
                   WorkflowNode(id="b", name="B", kind="tool", prompt="pb")],
            edges=[WorkflowEdge(source="a", target="b", label="then")],
            knowledge=[KnowledgeDoc(filename="k.md", title="K", content="# K")],
            metadata={"x": 1},
        )
        self.assertEqual(WorkflowIR.from_dict(w.to_dict()), w)
        self.assertEqual(WorkflowIR.from_json(w.to_json()), w)

    def test_from_agent_ir_multi_tasks(self):
        ir = make_pipeline_ir()
        w = WorkflowIR.from_agent_ir(ir)
        self.assertEqual([n.id for n in w.nodes], ["collect-input", "draft-plan"])
        self.assertEqual([n.name for n in w.nodes], ["Collect Input", "Draft Plan"])
        self.assertIn("Gather user input.", w.nodes[0].prompt)
        self.assertIn("Expected output: A requirements list.", w.nodes[0].prompt)
        self.assertEqual(w.nodes[0].description, "A requirements list.")
        self.assertEqual([(e.source, e.target) for e in w.edges],
                         [("collect-input", "draft-plan")])
        # 全量透传 + _workflow 标记
        self.assertEqual(w.name, ir.name)
        self.assertEqual(w.display_name, ir.display_name)
        self.assertEqual(w.description, ir.description)
        self.assertEqual(w.system_prompt, ir.system_prompt)
        self.assertEqual(w.knowledge, ir.knowledge)
        self.assertEqual(w.metadata.get("note"), "unittest")
        self.assertTrue(w.metadata.get("_workflow"))

    def test_from_agent_ir_no_tasks_single_node(self):
        ir = AgentIR(name="solo-agent", system_prompt="Only prompt.")
        w = WorkflowIR.from_agent_ir(ir)
        self.assertEqual(len(w.nodes), 1)
        self.assertEqual(w.nodes[0].id, slugify("solo-agent"))
        self.assertEqual(w.nodes[0].prompt, "Only prompt.")
        self.assertEqual(w.edges, [])

    def test_from_agent_ir_duplicate_step_names_dedup(self):
        ir = AgentIR(
            name="dup",
            tasks=[TaskStep(name="Same Step", description="one"),
                   TaskStep(name="Same Step", description="two")],
        )
        w = WorkflowIR.from_agent_ir(ir)
        self.assertEqual([n.id for n in w.nodes], ["same-step", "same-step-2"])
        self.assertEqual([(e.source, e.target) for e in w.edges],
                         [("same-step", "same-step-2")])

    def test_to_agent_ir_multi_nodes_merge(self):
        w = WorkflowIR.from_agent_ir(make_pipeline_ir())
        ir2 = w.to_agent_ir()
        self.assertIn("## Step 1: Collect Input", ir2.system_prompt)
        self.assertIn("## Step 2: Draft Plan", ir2.system_prompt)
        self.assertIn("# Pipeline Agent", ir2.system_prompt)
        self.assertEqual([t.name for t in ir2.tasks], ["Collect Input", "Draft Plan"])
        self.assertEqual([t.agent for t in ir2.tasks], ["pipeline-agent", "pipeline-agent"])
        self.assertEqual([t.description for t in ir2.tasks],
                         [n.prompt for n in w.nodes])
        self.assertEqual(len(ir2.knowledge), 2)

    def test_to_agent_ir_single_node(self):
        w = WorkflowIR(name="solo", nodes=[WorkflowNode(id="solo", name="Solo", prompt="P.")])
        ir = w.to_agent_ir()
        self.assertEqual(ir.system_prompt, "P.")
        self.assertEqual(len(ir.tasks), 1)

    def test_agent_workflow_thin_wrappers(self):
        from converter.agent_workflow import agent_to_workflow, workflow_to_agent
        ir = make_pipeline_ir()
        self.assertEqual(agent_to_workflow(ir), WorkflowIR.from_agent_ir(ir))
        self.assertEqual(workflow_to_agent(agent_to_workflow(ir)).to_dict(),
                         WorkflowIR.from_agent_ir(ir).to_agent_ir().to_dict())


class TestMermaidEmit(unittest.TestCase):
    def _emit(self, tmp: Path):
        from converter.emitters.mermaid_workflow import emit_mermaid_workflow
        out = tmp / "out"
        return emit_mermaid_workflow(make_pipeline_ir(), out), out

    def test_workflow_md_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self._emit(Path(tmp))
            md = (out / "workflow.md").read_text(encoding="utf-8")
            self.assertIn("```mermaid", md)
            self.assertIn("flowchart TD", md)
            self.assertIn("# Pipeline Agent", md)
            self.assertIn("## Step 1: Collect Input", md)
            self.assertIn("## Step 2: Draft Plan", md)
            block = re.search(r"```mermaid\n(.*?)```", md, re.DOTALL).group(1)
            node_defs = re.findall(r'^\s*[\w-]+\["[^"]*"\]\s*$', block, re.MULTILINE)
            edge_defs = re.findall(r"-->", block)
            self.assertEqual(len(node_defs), 2, "mermaid 块应有 2 个节点定义")
            self.assertEqual(len(edge_defs), 1, "mermaid 块应有 1 条边")
            self.assertIn("classDef start", block)
            self.assertIn("knowledge/guide.md", md)

    def test_knowledge_copied_and_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self._emit(Path(tmp))
            guide = out / "knowledge" / "guide.md"
            self.assertTrue(guide.is_file(), "knowledge/guide.md 应被拷贝")
            self.assertEqual(guide.read_text(encoding="utf-8"), "# Guide\nstuff")
            self.assertTrue((out / "knowledge" / "extra.md").is_file())
            self.assertTrue((out / "README.md").is_file())


class TestMermaidParse(unittest.TestCase):
    def test_parse_back_name_and_prompt(self):
        from converter.emitters.mermaid_workflow import emit_mermaid_workflow
        from converter.parsers.mermaid_workflow import parse_mermaid_workflow
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            emit_mermaid_workflow(make_pipeline_ir(), out)
            ir = parse_mermaid_workflow(out)  # 目录形态:自动定位 workflow.md
            self.assertEqual(ir.name, "pipeline-agent")
            self.assertEqual(ir.display_name, "Pipeline Agent")
            # Source Context 优先回源:system_prompt 为原文全文,步骤在 tasks
            self.assertIn("You are a pipeline agent.", ir.system_prompt)
            step_text = "\n".join(t.description for t in ir.tasks)
            self.assertIn("Gather user input.", step_text)
            self.assertIn("Expected output: A requirements list.", step_text)
            self.assertEqual([t.name for t in ir.tasks],
                             ["Collect Input", "Draft Plan"])
            self.assertEqual(ir.metadata.get("source_format"), "mermaid-workflow")
            know = {k.filename: k.content for k in ir.knowledge}
            self.assertEqual(know.get("guide.md"), "# Guide\nstuff")
            self.assertEqual(know.get("extra.md"), "# Extra\nmore")

    def test_parse_single_node_system_prompt(self):
        from converter.emitters.mermaid_workflow import emit_mermaid_workflow
        from converter.parsers.mermaid_workflow import parse_mermaid_workflow
        prompt = "You are a solo agent. Only one prompt, no steps."
        ir_in = AgentIR(name="solo-agent", display_name="Solo Agent",
                        description="solo demo",
                        system_prompt=prompt,
                        knowledge=[KnowledgeDoc(filename="g.md", content="# G")])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            emit_mermaid_workflow(ir_in, out)
            ir2 = parse_mermaid_workflow(out / "workflow.md")
            self.assertEqual(ir2.system_prompt, prompt)
            self.assertEqual(len(ir2.tasks), 1)

    def test_parse_no_mermaid_fallback_body(self):
        from converter.parsers.mermaid_workflow import parse_mermaid_workflow
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "workflow.md"
            md.write_text(
                "---\nname: plain-flow\ndescription: d\n---\n\n"
                "# Plain\n\nJust a body without graph.\n",
                encoding="utf-8",
            )
            ir = parse_mermaid_workflow(md)
            self.assertEqual(ir.name, "plain-flow")
            self.assertIn("Just a body without graph.", ir.system_prompt)


class TestMermaidRoundtrip(unittest.TestCase):
    def test_agent_to_mermaid_to_agent(self):
        from converter.emitters.mermaid_workflow import emit_mermaid_workflow
        from converter.parsers.mermaid_workflow import parse_mermaid_workflow
        ir_in = make_pipeline_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            emit_mermaid_workflow(ir_in, out)
            ir_out = parse_mermaid_workflow(out)
            self.assertEqual(ir_out.name, ir_in.name)  # F_name = 1.0
            by_name_in = {k.filename: k.content for k in ir_in.knowledge}
            by_name_out = {k.filename: k.content for k in ir_out.knowledge}
            self.assertEqual(by_name_in, by_name_out)  # F_know_q / F_know_c 满分
            # Source Context 回源:原文全文无损,步骤语义保留在 tasks
            self.assertEqual(ir_out.system_prompt.strip(), ir_in.system_prompt.strip())
            step_text = "\n".join(t.description for t in ir_out.tasks)
            for phrase in ("Gather user input.", "Write the plan."):
                self.assertIn(phrase, step_text)


class TestWorkflowRegistry(unittest.TestCase):
    def test_emitters_registry(self):
        from converter.emitters import EMITTERS
        self.assertIn("mermaid-workflow", EMITTERS)
        self.assertTrue(callable(EMITTERS["mermaid-workflow"]))
        # n8n 由并行线程提供:模块在则必须已注册,不在则不断言
        try:
            importlib.import_module("converter.emitters.n8n")
        except Exception:
            pass
        else:
            self.assertIn("n8n", EMITTERS)

    def test_parsers_registry(self):
        from converter.parsers import PARSERS
        self.assertIn("mermaid-workflow", PARSERS)
        self.assertTrue(callable(PARSERS["mermaid-workflow"]))
        try:
            importlib.import_module("converter.parsers.n8n")
        except Exception:
            pass
        else:
            self.assertIn("n8n", PARSERS)


class TestWorkflowValidators(unittest.TestCase):
    """metrics.VALIDATORS 新增两键:v_n8n / v_mermaid_workflow。"""

    @classmethod
    def setUpClass(cls):
        eval_dir = ROOT / "evaluation"
        if str(eval_dir) not in sys.path:
            sys.path.insert(0, str(eval_dir))
        cls.metrics = importlib.import_module("metrics")

    def test_validators_registered(self):
        self.assertIn("n8n", self.metrics.VALIDATORS)
        self.assertIn("mermaid-workflow", self.metrics.VALIDATORS)

    def test_v_mermaid_workflow_pass_and_fail(self):
        from converter.emitters.mermaid_workflow import emit_mermaid_workflow
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            emit_mermaid_workflow(make_pipeline_ir(), out)
            ok, reasons = self.metrics.validate_forward("mermaid-workflow", out)
            self.assertEqual(ok, 1, f"mermaid-workflow 产物应通过校验: {reasons}")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            ok2, _ = self.metrics.validate_forward("mermaid-workflow", empty)
            self.assertEqual(ok2, 0)

    def test_v_n8n_shape(self):
        v = self.metrics.VALIDATORS["n8n"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, _ = v(root)
            self.assertEqual(ok, 0, "缺 workflow.json 应不通过")
            import json
            (root / "workflow.json").write_text(
                json.dumps({"nodes": [{"id": "1", "type": "@n8n/n8n-nodes-langchain.agent"}],
                            "connections": {}}),
                encoding="utf-8",
            )
            ok, reasons = v(root)
            self.assertEqual(ok, 1, reasons)


if __name__ == "__main__":
    unittest.main()
