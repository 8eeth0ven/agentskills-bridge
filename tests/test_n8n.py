"""n8n workflow(workflow 族第一个引擎格式)emitter/parser 的条件化测试。

converter.wir 由并行线程提供:未落盘时 emit 侧(依赖 WorkflowIR.from_agent_ir)
skipTest;parser 侧自包含,不依赖 wir,可独立运行。
"""

import json
import tempfile
import unittest
from pathlib import Path

from converter.ir import AgentIR, KnowledgeDoc, TaskStep

try:
    from converter.emitters.n8n import emit_n8n
    from converter.emitters import n8n as _n8n_emitter
    if _n8n_emitter.WorkflowIR is None:
        emit_n8n = None  # converter.wir 未落盘
except Exception:  # pragma: no cover - 并行线程未落盘
    emit_n8n = None

try:
    from converter.parsers.n8n import parse_n8n
except Exception:  # pragma: no cover
    parse_n8n = None

try:
    from converter.skill_loader import load_skill
    from converter.skill_writer import write_skill
except Exception:  # pragma: no cover
    load_skill = None
    write_skill = None


def make_demo_ir() -> AgentIR:
    """标准测试用 IR:2 个 tasks 步骤 + 1 篇 knowledge。"""
    return AgentIR(
        name="demo-n8n-agent",
        display_name="Demo N8n Agent",
        description="A demo agent converted to an n8n workflow.",
        system_prompt=(
            "# Demo N8n Workflow\n\n"
            "You are the demo workflow agent. Handle steps \"carefully\"."
        ),
        default_prompt="Run the demo workflow",
        tasks=[
            TaskStep(
                name="Collect",
                description="Collect the raw demo input and validate every field.",
                expected_output="validated item list",
            ),
            TaskStep(
                name="Summarize",
                description="Summarize the validated list into a short plain-text report.",
                expected_output="short report",
            ),
        ],
        knowledge=[
            KnowledgeDoc(filename="guide.md", title="Guide", content="# Guide\ncontent\n"),
        ],
        metadata={"note": "unittest"},
    )


class TestEmitN8n(unittest.TestCase):
    def _emit(self, ir, out):
        if emit_n8n is None:
            self.skipTest("converter.wir not available yet (emit side)")
        return emit_n8n(ir, out)

    def test_emit_structure(self):
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._emit(ir, out)
            wf_file = out / "workflow.json"
            self.assertTrue(wf_file.is_file(), "workflow.json 应存在")
            wf = json.loads(wf_file.read_text(encoding="utf-8"))

            # 顶层:name/nodes/connections/settings/active/meta
            self.assertEqual(wf["name"], "Demo N8n Agent")
            self.assertEqual(wf["settings"].get("executionOrder"), "v1")
            self.assertFalse(wf["active"])
            self.assertTrue(wf["meta"].get("templateCredsSetupCompleted"))

            # 节点:1 个 Chat Trigger + >=2 个 AI Agent
            types = [n["type"] for n in wf["nodes"]]
            self.assertEqual(
                types.count("@n8n/n8n-nodes-langchain.chatTrigger"), 1, "应恰有 1 个 chatTrigger"
            )
            agents = [n for n in wf["nodes"] if n["type"] == "@n8n/n8n-nodes-langchain.agent"]
            self.assertGreaterEqual(len(agents), 2, "应有 >=2 个 agent 节点")
            for n in wf["nodes"]:
                self.assertIn("id", n)
                self.assertIn("typeVersion", n)
                self.assertIn("position", n)

            # agent 参数:promptType=define + options.systemMessage 含各步文本
            by_name = {n["name"]: n for n in agents}
            msgs = [n["parameters"]["options"]["systemMessage"] for n in agents]
            self.assertTrue(all(n["parameters"]["promptType"] == "define" for n in agents))
            self.assertTrue(any("Collect the raw demo input" in m for m in msgs))
            self.assertTrue(any("Summarize the validated list" in m for m in msgs))

            # position 按序横排 (i*300, 300)
            ordered = sorted(agents, key=lambda n: n["position"][0])
            self.assertEqual([n["position"][0] for n in ordered], [0, 300])
            self.assertTrue(all(n["position"][1] == 300 for n in ordered))

            # connections 链:Chat Trigger -> 首个 -> 第二个(main/index 结构)
            conns = wf["connections"]
            self.assertIn("Chat Trigger", conns)
            first_link = conns["Chat Trigger"]["main"][0][0]
            self.assertEqual(first_link["type"], "main")
            self.assertEqual(first_link["index"], 0)
            first_agent = ordered[0]["name"]
            second_agent = ordered[1]["name"]
            self.assertEqual(first_link["node"], first_agent)
            self.assertEqual(
                conns[first_agent]["main"][0][0]["node"], second_agent, "链应首尾相接"
            )

            # knowledge 拷贝 + README
            self.assertEqual(
                (out / "knowledge" / "guide.md").read_text(encoding="utf-8"),
                "# Guide\ncontent\n",
            )
            self.assertTrue((out / "README.md").is_file(), "README.md 应存在")
            readme = (out / "README.md").read_text(encoding="utf-8")
            self.assertIn("Import from File", readme)
            self.assertIn("open.bigmodel.cn/api/paas/v4", readme, "README 应含 GLM 接线一句")

    def test_emit_without_tasks_single_agent(self):
        ir = AgentIR(
            name="solo-agent",
            display_name="Solo Agent",
            system_prompt="You are the solo agent. Do one thing well.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._emit(ir, out)
            wf = json.loads((out / "workflow.json").read_text(encoding="utf-8"))
            agents = [n for n in wf["nodes"] if n["type"].endswith(".agent")]
            self.assertEqual(len(agents), 1, "无 tasks 时应只有 1 个 agent 节点")
            self.assertIn("solo agent", agents[0]["parameters"]["options"]["systemMessage"])
            self.assertFalse((out / "knowledge").exists(), "无 knowledge 时不建目录")


class TestParseN8n(unittest.TestCase):
    def _parse(self, path):
        if parse_n8n is None:
            self.skipTest("converter.parsers.n8n not available yet")
        return parse_n8n(path)

    def test_emit_then_parse_roundtrip(self):
        if emit_n8n is None:
            self.skipTest("converter.wir not available yet (emit side)")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "n8n"
            emit_n8n(ir, out)
            back = self._parse(out)  # 目录形态:自动定位 workflow.json
            self.assertEqual(back.name, "demo-n8n-agent", "name 应 slugify 回读一致")
            self.assertEqual(back.metadata.get("source_format"), "n8n")
            # x-source-skill 优先回源:system_prompt 为原文全文(非步骤重组)
            self.assertIn("demo workflow agent", back.system_prompt)
            self.assertIn('Handle steps "carefully"', back.system_prompt)
            # 步骤语义保留在 tasks(节点链只是骨架)
            step_text = "\n".join(t.description for t in back.tasks)
            self.assertIn("Collect the raw demo input", step_text)
            self.assertIn("Summarize the validated list", step_text)
            # tasks 重建(执行顺序按 connections BFS)
            self.assertEqual([t.name for t in back.tasks], ["Collect", "Summarize"])
            # knowledge 回流
            by_name = {k.filename: k.content for k in back.knowledge}
            self.assertEqual(by_name, {"guide.md": "# Guide\ncontent\n"})
            self.assertEqual(back.metadata.get("chain"), ["Collect", "Summarize"])

    def test_parse_single_node_direct_prompt(self):
        """单 agent 节点:system_prompt 直取,不带 Step 分节头。"""
        wf = {
            "name": "Solo Agent",
            "nodes": [
                {
                    "parameters": {
                        "promptType": "define",
                        "options": {"systemMessage": "=You are the solo agent. Be brief."},
                    },
                    "id": "a1",
                    "name": "Solo",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "typeVersion": 1.7,
                    "position": [0, 0],
                }
            ],
            "connections": {},
            "settings": {"executionOrder": "v1"},
            "active": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "workflow.json"
            f.write_text(json.dumps(wf), encoding="utf-8")
            back = self._parse(f)
            self.assertEqual(back.name, "solo-agent")
            self.assertEqual(back.system_prompt, "You are the solo agent. Be brief.")
            self.assertNotIn("## Step", back.system_prompt)

    def test_parse_no_connections_falls_back_to_node_order(self):
        """无 connections:按 nodes 数组顺序重建步骤。"""
        wf = {
            "name": "Ordered Flow",
            "nodes": [
                {
                    "parameters": {"options": {"systemMessage": "First stage prompt text."}},
                    "id": "n1", "name": "First",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "typeVersion": 1.7, "position": [0, 0],
                },
                {
                    "parameters": {"options": {"systemMessage": "Second stage prompt text."}},
                    "id": "n2", "name": "Second",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "typeVersion": 1.7, "position": [300, 0],
                },
            ],
            "connections": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "workflow.json"
            f.write_text(json.dumps(wf), encoding="utf-8")
            back = self._parse(f)
            self.assertEqual([t.name for t in back.tasks], ["First", "Second"])
            self.assertIn("## Step 1: First", back.system_prompt)
            self.assertIn("## Step 2: Second", back.system_prompt)

    def test_parse_fallback_non_agent_node_with_text(self):
        """无 agent 节点:回退任意含 text/prompt 参数的节点(长文本)。"""
        wf = {
            "name": "Fallback Flow",
            "nodes": [
                {
                    "parameters": {
                        "prompt": "You are a helpful research assistant with long instructions."
                    },
                    "id": "p1", "name": "Prompt Node",
                    "type": "n8n-nodes-base.set",
                    "typeVersion": 3, "position": [0, 0],
                }
            ],
            "connections": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "workflow.json"
            f.write_text(json.dumps(wf), encoding="utf-8")
            back = self._parse(f)
            self.assertIn("helpful research assistant", back.system_prompt)

    def test_parse_model_extraction_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertRaises(FileNotFoundError, self._parse, d / "nope")  # 目录缺文件
            bad = d / "bad.json"
            bad.write_text("{ not json", encoding="utf-8")
            self.assertRaises(ValueError, self._parse, bad)
            # 模型子节点 -> metadata.model
            wf = {
                "name": "Model Flow",
                "nodes": [
                    {
                        "parameters": {
                            "model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}
                        },
                        "id": "m1", "name": "OpenAI Chat Model",
                        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                        "typeVersion": 1.2, "position": [0, 200],
                    },
                    {
                        "parameters": {"options": {"systemMessage": "Summarize everything."}},
                        "id": "a1", "name": "Agent",
                        "type": "@n8n/n8n-nodes-langchain.agent",
                        "typeVersion": 1.7, "position": [0, 0],
                    },
                ],
                "connections": {
                    "OpenAI Chat Model": {
                        "ai_languageModel": [[{"node": "Agent", "type": "ai_languageModel", "index": 0}]]
                    }
                },
            }
            f = d / "workflow.json"
            f.write_text(json.dumps(wf), encoding="utf-8")
            back = self._parse(f)
            self.assertEqual(back.metadata.get("model"), "gpt-4o-mini")
            # ai_languageModel 连线不参与 main 执行顺序,agent 仍是唯一步骤
            self.assertEqual([t.name for t in back.tasks], ["Agent"])

    def test_parse_real_export_shape(self):
        """用真实导出形态(带 settings/meta/webhookId/表达式前缀)冒烟。"""
        wf = {
            "name": "Deep Research",
            "nodes": [
                {
                    "parameters": {"options": {}}, "webhookId": "w-1",
                    "id": "t1", "name": "When chat message received",
                    "type": "@n8n/n8n-nodes-langchain.chatTrigger",
                    "typeVersion": 1.1, "position": [-300, 300],
                },
                {
                    "parameters": {
                        "promptType": "define",
                        "text": "={{ $json.chatInput }}",
                        "options": {"systemMessage": "=# Planner\nBreak the task into steps."},
                    },
                    "id": "a1", "name": "Planner",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "typeVersion": 1.7, "position": [0, 300],
                },
                {
                    "parameters": {
                        "promptType": "define",
                        "text": "={{ $json.output }}",
                        "options": {"systemMessage": "=# Writer\nWrite the final report."},
                    },
                    "id": "a2", "name": "Writer",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "typeVersion": 1.7, "position": [300, 300],
                },
            ],
            "connections": {
                "When chat message received": {
                    "main": [[{"node": "Planner", "type": "main", "index": 0}]]
                },
                "Planner": {"main": [[{"node": "Writer", "type": "main", "index": 0}]]},
            },
            "settings": {"executionOrder": "v1"},
            "active": False,
            "meta": {"templateCredsSetupCompleted": True},
            "pinData": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "workflow.json"
            f.write_text(json.dumps(wf), encoding="utf-8")
            back = self._parse(f)
            self.assertEqual(back.name, "deep-research")
            self.assertEqual([t.name for t in back.tasks], ["Planner", "Writer"],
                             "执行顺序应从触发器 BFS 重建")
            self.assertIn("## Step 1: Planner", back.system_prompt)
            self.assertIn("Break the task into steps.", back.system_prompt)


class TestN8nFullChain(unittest.TestCase):
    """emit -> parse -> write_skill -> load_skill 的 name/knowledge 一致。"""

    def test_full_chain(self):
        if emit_n8n is None:
            self.skipTest("converter.wir not available yet (emit side)")
        if parse_n8n is None:
            self.skipTest("converter.parsers.n8n not available yet")
        if load_skill is None or write_skill is None:
            self.skipTest("skill_loader/skill_writer not available yet")
        ir = make_demo_ir()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            n8n_dir = tmp_path / "n8n"
            emit_n8n(ir, n8n_dir)
            ir_mid = parse_n8n(n8n_dir)
            skill_dir = tmp_path / "skill-back"
            write_skill(ir_mid, skill_dir)
            ir_out = load_skill(skill_dir)

            self.assertEqual(ir_out.name, ir.name, "name 经 n8n roundtrip 后一致")
            by_name_in = {k.filename: k.content for k in ir.knowledge}
            by_name_out = {k.filename: k.content for k in ir_out.knowledge}
            self.assertEqual(by_name_in, by_name_out, "knowledge 内容应逐篇一致")
            self.assertEqual(sorted(by_name_out), ["guide.md"])
            self.assertTrue(
                (skill_dir / "references" / "guide.md").is_file(),
                "references/guide.md 应落盘",
            )


if __name__ == "__main__":
    unittest.main()
