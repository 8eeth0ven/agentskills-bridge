"""Langflow 真实引擎运行时验证:用 pip 安装的 langflow 加载 agentskills-bridge 产物。

不是静态 schema 校验——setUpClass 里真正 `import langflow`(pip 包,不起 docker),
用官方加载入口 langflow.load.load_flow_from_json(JSON -> Graph)把 emit_langflow
生成的 flow.json 交给引擎解析,断言四个组件被识别、实例化,Prompt 提示词经引擎
往返文本无损。

运行方式(项目根目录):
    python3 -m unittest evaluation.runtime.test_langflow_runtime -v

引擎与入口(2026-10 实测,langflow==1.12.5 / lfx==1.12.5,Python 3.13 venv):
    - 主入口:langflow.load.load_flow_from_json(flow: Path|str|dict) -> Graph
      (asyncore 壳 aload_flow_from_json;内部 Graph.from_payload(graph_data));
    - 底层:lfx.graph.graph.base.Graph.from_payload(payload, instantiate_components=
      True) —— 解析 nodes/edges、构建 Vertex、并同步实例化每个组件(
      vertex.instantiate_component -> instantiate_class,params.pop("code") 为
      必需,组件类由 eval_custom_component_code(template.code.value) exec 而来);
    - 边解析用 e["data"]["sourceHandle"/"targetHandle"] 结构化对象(官方导出
      双写,引擎只读结构化那份)。

覆盖(对应任务 b-d;a 为产物前提):
    a. test_a_emit_artifacts —— demo IR(中文+中英引号 system_prompt)emit 到
       临时产物目录 langflow,断言 flow.json 含 4 个官方类型节点且模板带 code 字段
       (真实引擎实例化的必需字段,见下方修复记录)。
    b. test_b_engine_load —— load_flow_from_json(flow.json) 不抛异常,
       Graph 识别出 4 个 vertex(ChatInput/Prompt/LanguageModelComponent/
       ChatOutput),vertex_type/base_type 全部解析为 component。
    c. test_c_prompt_roundtrip —— 引擎解析后 Prompt 节点
       data.node.template.template.value 与我们的 system_prompt 逐字一致
       (中文、全角引号「」《》、英文引号、em-dash、{message} 变量全部无损)。
    d. test_d_component_instantiation_and_build —— Graph.from_payload 默认
       instantiate_components=True:4 个组件类型全部实例化成功
       (ChatInput/PromptComponent/LanguageModelComponent/ChatOutput);
       无需凭据的 ChatInput 与 Prompt 节点再走 graph.build_vertex 真实 build,
       断言 build 出的 prompt template 文本与 system_prompt 一致。
       LanguageModelComponent 的 build_model/run(run_flow_from_json) 需要
       OPENAI_API_KEY 凭据,属凭据层,本测试不执行(结构层已覆盖)。

2026-10 修复记录(改 converter/emitters/langflow.py,由本测试驱动):
    - bug1:模板缺 template.code 字段。引擎实例化组件时
      instantiate_class 里 custom_params.pop("code") 直接 KeyError('code'),
      修复前 load_flow_from_json 必炸;官方导出一律内嵌组件完整源码。
      修复:四个节点模板补 code 字段,value 取 1.12.5 发行包
      lfx/_assets/component_index.json 的规范源码(与官方导出逐字一致)。
    - bug2:ChatInput field_order 写了不存在的 "store_message"(实际字段名
      should_store_message),顺手改正。

langflow 不可 import 时整类 skipTest(pip/网络问题不判失败)。
"""

from __future__ import annotations

import sys
import traceback
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runtime._artifacts import artifact_root

OUT_LANGFLOW: Path

# demo system_prompt:中文 + 全角引号「」《》+ 英文双引号 + em-dash + {message} 变量
DEMO_PROMPT = (
    "你是「全周期工程」agent —— 《交付手册》v3 授权执行者。\n"
    "规则:\n"
    "1. 接到任务先复述 \"验收标准\",不确定就问,禁止自猜\n"
    "2. 全程中文回复,结论引用《交付手册》条款号(如 DH-7.2)\n"
    "3. 用户消息 {message} 一律先确认再动手;拒绝偷懒 —— \"差不多\"不算交付\n"
)

# 引擎实例化后预期的组件类名(与 1.12.5 规范源码里的 class 定义一一对应)
EXPECTED_COMPONENT_CLASSES = {
    "ChatInput": "ChatInput",
    "Prompt": "PromptComponent",
    "LanguageModelComponent": "LanguageModelComponent",
    "ChatOutput": "ChatOutput",
}


def _version(pkg: str) -> str:
    from importlib.metadata import version

    return version(pkg)


class LangflowRuntimeTest(unittest.TestCase):
    """用真实 langflow 1.12.5 引擎加载转换产物 flow.json。"""

    @classmethod
    def setUpClass(cls):
        try:
            import langflow  # noqa: F401
            from langflow.load import load_flow_from_json  # noqa: F401
        except Exception as exc:  # pip/网络问题不判失败
            raise unittest.SkipTest(f"langflow 不可 import,整类跳过: {exc}")

        cls.lf_version = _version("langflow")
        print(f"\n[langflow runtime] langflow=={cls.lf_version}")

        # 每次运行用当前 converter 代码重新生成产物,保证验证的是最新转换逻辑
        from converter.emitters.langflow import emit_langflow
        from converter.ir import AgentIR

        ir = AgentIR(
            name="demo-langflow-runtime",
            display_name="Demo Langflow Runtime",
            description="langflow 真实引擎加载验证用 demo",
            system_prompt=DEMO_PROMPT,
            metadata={"model": "gpt-4.1"},
        )
        cls.demo_prompt = DEMO_PROMPT
        global OUT_LANGFLOW
        OUT_LANGFLOW = artifact_root(cls) / "langflow"
        emit_langflow(ir, OUT_LANGFLOW)

    # ---------- 公共辅助 ----------

    def _ctx(self) -> str:
        return f"[langflow=={self.lf_version}]"

    def _fail_with_tb(self, message: str, exc: BaseException) -> None:
        """失败信息带 traceback 首行,便于定位引擎内部断点。"""
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        first = next((ln.strip() for ln in lines if ln.strip().startswith("File ")), "")
        self.fail(f"{message}: {type(exc).__name__}: {exc} | tb首行: {first}")

    def _load_graph(self):
        """引擎主入口加载 flow.json,任何异常都转成带 traceback 的失败。"""
        from langflow.load import load_flow_from_json

        try:
            return load_flow_from_json(OUT_LANGFLOW / "flow.json")
        except Exception as exc:
            self._fail_with_tb(f"{self._ctx()} load_flow_from_json 加载产物失败", exc)

    def _vertex(self, graph, vertex_type: str):
        matched = [v for v in graph.vertices if v.vertex_type == vertex_type]
        self.assertTrue(
            matched,
            f"{self._ctx()} 引擎未识别出 {vertex_type} 节点:"
            f" {[v.vertex_type for v in graph.vertices]}",
        )
        return matched[0]

    # ---------- a. 产物前提(emit 到 tmp) ----------

    def test_a_emit_artifacts(self):
        """demo IR(中文+引号 system_prompt)emit 产物含 4 官方类型节点且带 code 字段。"""
        import json

        flow_path = OUT_LANGFLOW / "flow.json"
        self.assertTrue(flow_path.is_file(), f"{self._ctx()} 产物缺 flow.json: {flow_path}")
        flow = json.loads(flow_path.read_text(encoding="utf-8"))
        nodes = flow["data"]["nodes"]
        types = [n["data"]["type"] for n in nodes]
        for want in ("ChatInput", "Prompt", "LanguageModelComponent", "ChatOutput"):
            self.assertIn(want, types, f"{self._ctx()} flow.json 缺 {want} 节点: {types}")
        # code 字段是真实引擎实例化的必需字段(bug1 修复的回归锚点)
        for n in nodes:
            code = n["data"]["node"]["template"].get("code")
            self.assertTrue(
                code and isinstance(code.get("value"), str) and "class " in code["value"],
                f"{self._ctx()} 节点 {n['data']['type']} 模板缺可用 code 字段(引擎会 KeyError)",
            )
        # 源文件里 Prompt 提示词文本就是 system_prompt(后续 c 步在引擎侧对照)
        prompt_node = next(n for n in nodes if n["data"]["type"] == "Prompt")
        self.assertEqual(
            prompt_node["data"]["node"]["template"]["template"]["value"],
            DEMO_PROMPT,
            f"{self._ctx()} 源文件 Prompt template.value 与 system_prompt 不一致",
        )
        print(f"[langflow runtime] emit OK: nodes={types}, prompt_len={len(DEMO_PROMPT)}")

    # ---------- b. 真实引擎加载 ----------

    def test_b_engine_load(self):
        """load_flow_from_json(flow.json) 不抛异常,识别出 4 个节点。"""
        graph = self._load_graph()
        self.assertEqual(
            len(graph.vertices), 4,
            f"{self._ctx()} 引擎解析出的节点数异常: {[v.vertex_type for v in graph.vertices]}",
        )
        got = {v.vertex_type for v in graph.vertices}
        self.assertEqual(
            got, set(EXPECTED_COMPONENT_CLASSES),
            f"{self._ctx()} 节点类型集合不符: {got}",
        )
        # base_type 解析成功(解析失败会是 None,instantiate_class 会拒载)
        for v in graph.vertices:
            self.assertEqual(v.base_type, "component",
                             f"{self._ctx()} {v.vertex_type} base_type 未解析: {v.base_type!r}")
        # 边也被引擎接受:3 条边全部建立连接
        self.assertEqual(len(graph.edges), 3,
                         f"{self._ctx()} 引擎建边数异常: {len(graph.edges)}")
        print(f"[langflow runtime] engine load OK: "
              f"{sorted(v.vertex_type for v in graph.vertices)}, edges={len(graph.edges)}")

    # ---------- c. 引擎往返提示词无损 ----------

    def test_c_prompt_roundtrip(self):
        """引擎解析后 Prompt 节点 template.template.value 与 system_prompt 完全一致。"""
        graph = self._load_graph()
        pv = self._vertex(graph, "Prompt")
        engine_value = pv.data["node"]["template"]["template"]["value"]
        self.assertEqual(
            engine_value, DEMO_PROMPT,
            f"{self._ctx()} 引擎往返后 Prompt template 漂移:"
            f" len(engine)={len(engine_value)} len(ours)={len(DEMO_PROMPT)}",
        )
        # params 视角(引擎 build_params 处理后的同一文本)同样无损
        self.assertEqual(pv.params.get("template"), DEMO_PROMPT,
                         f"{self._ctx()} 引擎 params['template'] 与 system_prompt 不一致")
        for needle in ("「全周期工程」", "《交付手册》", '"验收标准"', "{message}", "——"):
            self.assertIn(needle, engine_value,
                          f"{self._ctx()} 引擎往返丢失特殊字符: {needle}")
        print(f"[langflow runtime] prompt roundtrip OK: len={len(engine_value)},"
              f" 中文/引号/变量无损")

    # ---------- d. 组件实例化 + 无凭据 build ----------

    def test_d_component_instantiation_and_build(self):
        """4 组件类型实例化成功;ChatInput/Prompt 再真实 build(不碰凭据层)。

        LanguageModelComponent 的 build_model 与整图 run(run_flow_from_json)
        需要 OPENAI_API_KEY(SecretStrInput load_from_db 凭据层),本测试
        不执行;其结构层(类型解析 + 组件实例化)已覆盖。
        """
        import asyncio

        graph = self._load_graph()

        # 1) 默认 instantiate_components=True:所有组件类已由引擎 exec+实例化
        for vertex_type, expect_cls in EXPECTED_COMPONENT_CLASSES.items():
            v = self._vertex(graph, vertex_type)
            cc = v.custom_component
            self.assertIsNotNone(
                cc,
                f"{self._ctx()} {vertex_type} 组件实例为 None(引擎未实例化)",
            )
            self.assertEqual(type(cc).__name__, expect_cls,
                             f"{self._ctx()} {vertex_type} 实例化成 "
                             f"{type(cc).__name__},应为 {expect_cls}")

        # 2) 无凭据路径的真实 build:ChatInput -> Prompt(按依赖序)
        cv = self._vertex(graph, "ChatInput")
        pv = self._vertex(graph, "Prompt")

        async def _build_pair() -> None:
            await graph.build_vertex(cv.id)
            await graph.build_vertex(pv.id)

        try:
            asyncio.run(_build_pair())
        except Exception as exc:
            self._fail_with_tb(f"{self._ctx()} ChatInput/Prompt build_vertex 失败", exc)
            return

        # 3) build 出的 prompt 模板文本与 system_prompt 逐字一致
        self.assertIn("prompt", pv.results,
                      f"{self._ctx()} Prompt build 后缺 prompt 输出: {list(pv.results)}")
        built = pv.built_object
        prompt_obj = built.get("prompt") if isinstance(built, dict) else None
        template_data = getattr(prompt_obj, "data", None) if prompt_obj is not None else None
        self.assertTrue(
            isinstance(template_data, dict) and "template" in template_data,
            f"{self._ctx()} build 产物缺 template 数据: {type(template_data).__name__}",
        )
        self.assertEqual(
            template_data["template"], DEMO_PROMPT,
            f"{self._ctx()} build 出的 prompt template 与 system_prompt 不一致",
        )
        print(f"[langflow runtime] instantiate OK: "
              f"{ {t: type(self._vertex(graph, t).custom_component).__name__ for t in EXPECTED_COMPONENT_CLASSES} },"
              f" ChatInput+Prompt build OK (LLM build/run 需凭据,未执行)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
