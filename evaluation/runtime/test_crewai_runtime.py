"""CrewAI 运行时验证:用真实安装的 crewai 框架加载 agentskills-bridge 转换产物。

不是静态检查——setUpClass 里真正 `import crewai`,用真实 Agent/Task/Crew 类
构造对象,并用 crewai 包内的 skills 加载入口加载 crewai-skills 靶的技能目录。

运行方式(项目根目录):
    python3 -m unittest evaluation.runtime.test_crewai_runtime -v

覆盖(对应任务 a-e,附 f 忠实度回归):
    a. test_a_yaml_semantic_equivalence —— pyyaml 读 config/agents.yaml,断言
       backstory 与 examples/agent-fullcycle-engineering/SKILL.md 正文 strip 后
       完全一致(`|` literal 块标量不破坏换行)。
    b. test_b_agent_construction —— 真实 crewai.Agent(role/goal/backstory/verbose)
       构造成功(不给 llm;若构造报缺少 llm 则补 llm=None 重试并记录)。
       注:crewai 1.15.x 的 Agent 是 Pydantic 模型,签名只显示 **data,
       字段存在性用 Agent.model_fields 检查。
    c. test_c_task_construction —— 真实 crewai.Task(description/expected_output/agent)
       构造成功。
    d. test_d_crew_construction —— 真实 crewai.Crew(agents/tasks/process=sequential)
       构造成功。
    e. test_e_skills_loading —— 在已装 crewai 包源码里定位 SKILL.md 加载入口,
       用公开 crewai.skills.load_skill + Agent(skills=[...]) 真实加载
       crewai-skills 靶 agents.yaml 里 emitted 的 skills 引用,断言
       name/description 被识别且 instructions 与 SKILL.md 正文一致。
       实测语义(crewai 1.15.27):skills 的路径输入一律作为"搜索目录"扫
       子目录下的 SKILL.md;单技能目录 ./skills/<name> 会加载 0 个技能,
       因此产物必须引用发现目录 ./skills。
    f. test_f_crewai_skills_yaml_fidelity —— crewai-skills 靶 backstory 用
       literal 块标量 roundtrip 后与 ir.backstory() 逐字一致(防 `>` 折叠回归)。

crewai 不可 import 时整类 skipTest(网络/环境问题不判失败)。
"""

from __future__ import annotations

import sys
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
DESC_HEAD = "End-to-end AI agent engineering workflow"


def _crewai_version() -> str:
    try:
        from importlib.metadata import version

        return version("crewai")
    except Exception:  # pragma: no cover - 兜底
        import crewai

        return getattr(crewai, "__version__", "unknown")


class CrewAIRuntimeTest(unittest.TestCase):
    """用真实 crewai 运行时加载转换产物。"""

    @classmethod
    def setUpClass(cls):
        try:
            import crewai  # noqa: F401
            import yaml  # noqa: F401
        except Exception as exc:  # 网络/安装问题不判失败
            raise unittest.SkipTest(f"crewai/pyyaml 不可 import,整类跳过: {exc}")

        cls.crewai_version = _crewai_version()
        print(f"\n[crewai runtime] crewai=={cls.crewai_version}")

        # 每次运行用当前 converter 代码重新生成产物,保证验证的是最新转换逻辑
        from converter.emitters import EMITTERS
        from converter.skill_loader import load_skill

        ir = load_skill(SKILL_DIR)
        global OUT_CREWAI, OUT_CREWAI_SKILLS
        artifacts = artifact_root(cls)
        OUT_CREWAI = artifacts / "crewai"
        OUT_CREWAI_SKILLS = artifacts / "crewai-skills"
        EMITTERS["crewai"](ir, OUT_CREWAI)
        EMITTERS["crewai-skills"](ir, OUT_CREWAI_SKILLS)

        import yaml

        cls.agents_cfg = yaml.safe_load((OUT_CREWAI / "config" / "agents.yaml").read_text())
        cls.tasks_cfg = yaml.safe_load((OUT_CREWAI / "config" / "tasks.yaml").read_text())
        cls.agent_entry = cls.agents_cfg[SKILL_NAME]
        cls.task_entry = cls.tasks_cfg[f"{SKILL_NAME}_task"]

        cls._agent_instance = None  # b/c/d 共享惰性缓存

    # ---------- 公共辅助 ----------

    def _ctx(self) -> str:
        return f"[crewai=={self.crewai_version}]"

    def _assert_fields(self, cls, *names: str):
        """字段存在性检查:Pydantic 模型查 model_fields,普通类查 __init__ 签名。

        crewai 1.15.x 的 Agent/Task/Crew 均为 Pydantic 模型,
        inspect.signature 只能看到 (self, **data),必须走 model_fields。
        """
        import inspect

        fields = getattr(cls, "model_fields", None)
        if fields is not None:
            for name in names:
                self.assertIn(name, fields, f"{self._ctx()} {cls.__name__}.model_fields 缺少 {name}: {sorted(fields)}")
        else:  # 兼容未来非 Pydantic 版本
            params = inspect.signature(cls.__init__).parameters
            for name in names:
                self.assertIn(name, params, f"{self._ctx()} {cls.__name__}.__init__ 签名缺少 {name}: {list(params)}")

    def _agent(self):
        """惰性构造并缓存真实 Agent(供 b/c/d 复用,失败信息一致)。"""
        if self.__class__._agent_instance is None:
            from crewai import Agent

            kwargs = dict(
                role=self.agent_entry["role"],
                goal=self.agent_entry["goal"],
                backstory=self.agent_entry["backstory"],
                verbose=False,
            )
            # crewai.Agent 的 llm 字段可选(默认 None,执行期才解析);
            # 若该版本构造时强制要求 llm,按真实报错补 llm=None 重试一次。
            first_error: Exception | None = None
            for extra in ({}, {"llm": None}):
                try:
                    self.__class__._agent_instance = Agent(**extra, **kwargs)
                    break
                except TypeError as exc:
                    if first_error is None:
                        first_error = exc
            else:
                self.fail(
                    f"{self._ctx()} crewai.Agent 构造失败(已尝试 llm=None):"
                    f" 错误={first_error}"
                )
        return self.__class__._agent_instance

    # ---------- a. YAML 语义等价 ----------

    def test_a_yaml_semantic_equivalence(self):
        """backstory(`|` literal 块标量)roundtrip 后与 SKILL.md 正文逐字一致。"""
        from converter.ir import parse_frontmatter

        _, body = parse_frontmatter((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        expected = body.strip()
        actual_raw = self.agent_entry.get("backstory")
        self.assertIsInstance(actual_raw, str, f"{self._ctx()} backstory 应为 str,实际 {type(actual_raw)}")
        actual = actual_raw.strip()
        self.assertEqual(
            actual,
            expected,
            f"{self._ctx()} backstory 与 SKILL.md 正文不一致:"
            f" yaml_len={len(actual)} md_len={len(expected)};"
            f" 首个差异位置="
            f"{next((i for i, (x, y) in enumerate(zip(actual, expected)) if x != y), min(len(actual), len(expected)))}",
        )
        # literal 块标量必须保留换行结构(折叠会破坏 markdown 列表/代码块)
        self.assertIn("\n", actual, f"{self._ctx()} backstory 丢失全部换行(疑似被折叠)")
        self.assertEqual(
            actual.count("\n"), expected.count("\n"),
            f"{self._ctx()} backstory 换行数不一致: yaml={actual.count(chr(10))} md={expected.count(chr(10))}",
        )

    # ---------- b. 真实 Agent 构造 ----------

    def test_b_agent_construction(self):
        """用 agents.yaml 解析出的 role/goal/backstory 构造真实 crewai.Agent。"""
        from crewai import Agent

        self._assert_fields(Agent, "role", "goal", "backstory")
        agent = self._agent()
        self.assertIsInstance(agent, Agent, f"{self._ctx()} 构造产物不是 crewai.Agent: {type(agent)}")
        # 构造出的实例字段应与 YAML 值一致
        for field in ("role", "goal", "backstory"):
            self.assertEqual(
                getattr(agent, field, None),
                self.agent_entry[field],
                f"{self._ctx()} Agent.{field} 与 agents.yaml 不一致",
            )

    # ---------- c. 真实 Task 构造 ----------

    def test_c_task_construction(self):
        """用 tasks.yaml 的 description/expected_output/agent 构造真实 crewai.Task。

        crewai.Task 真实签名(Task.__init__(self, /, **data),Pydantic 模型):
        description/expected_output/agent 均为合法关键字字段,无需适配。
        """
        from crewai import Task

        self._assert_fields(Task, "description", "expected_output", "agent")
        task = Task(
            description=self.task_entry["description"],
            expected_output=self.task_entry["expected_output"],
            agent=self._agent(),
        )
        self.assertIsInstance(task, Task, f"{self._ctx()} 构造产物不是 crewai.Task: {type(task)}")
        self.assertEqual(task.description, self.task_entry["description"],
                         f"{self._ctx()} Task.description 与 tasks.yaml 不一致")

    # ---------- d. 真实 Crew 构造 ----------

    def test_d_crew_construction(self):
        """Crew(agents=[...], tasks=[...], process=Process.sequential) 构造成功。"""
        from crewai import Crew, Process, Task

        self._assert_fields(Crew, "agents", "tasks", "process")
        crew = Crew(
            agents=[self._agent()],
            tasks=[Task(
                description=self.task_entry["description"],
                expected_output=self.task_entry["expected_output"],
                agent=self._agent(),
            )],
            process=Process.sequential,
        )
        self.assertIsInstance(crew, Crew, f"{self._ctx()} 构造产物不是 crewai.Crew: {type(crew)}")
        self.assertEqual(len(crew.agents), 1, f"{self._ctx()} Crew.agents 数量异常")
        self.assertEqual(len(crew.tasks), 1, f"{self._ctx()} Crew.tasks 数量异常")

    # ---------- e. crewai-skills 靶的技能加载 ----------

    def test_e_skills_loading(self):
        """用 crewai 包内真实 skills 加载入口加载技能目录并识别 name/description。

        实测 crewai 1.15.27:loader 把 skills 的路径输入一律当"搜索目录",
        只扫其子目录下的 SKILL.md;因此 agents.yaml 必须引用发现目录
        ./skills(单技能目录 ./skills/<name> 会解析出 0 个技能)。
        本测试直接拿产物 agents.yaml 里 emitted 的 skills 值做端到端加载。
        """
        import crewai
        import yaml
        from crewai import Agent
        from crewai.skills import load_skill as crewai_load_skill

        skill_dir = OUT_CREWAI_SKILLS / "skills" / SKILL_NAME
        self.assertTrue((skill_dir / "SKILL.md").is_file(),
                        f"{self._ctx()} 产物缺技能文件: {skill_dir}/SKILL.md")

        # 1) 在已装 crewai 包源码里找 SKILL.md 加载入口(等价 grep -r "SKILL.md")
        pkg_dir = Path(crewai.__file__).parent
        hits = [
            str(p.relative_to(pkg_dir))
            for p in sorted(pkg_dir.rglob("*.py"))
            if "SKILL.md" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertTrue(
            hits,
            f"{self._ctx()} crewai=={self.crewai_version} 包内找不到任何 SKILL.md 引用,"
            f" 不支持原生 Agent Skills: {pkg_dir}",
        )
        print(f"[crewai runtime] SKILL.md 引用入口({len(hits)} 处): {hits[:6]}")

        # 2) Agent 必须提供公开 skills 挂载参数
        self._assert_fields(Agent, "skills")

        # 3) 产物 agents.yaml 的 skills 值端到端真实加载(路径相对产物根解析)
        skills_cfg = yaml.safe_load(
            (OUT_CREWAI_SKILLS / "config" / "agents.yaml").read_text()
        )[SKILL_NAME].get("skills")
        self.assertIsInstance(skills_cfg, list, f"{self._ctx()} agents.yaml 缺 skills 列表: {skills_cfg!r}")
        self.assertTrue(skills_cfg, f"{self._ctx()} agents.yaml 的 skills 列表为空")
        loaded = []
        for ref in skills_cfg:
            self.assertIsInstance(ref, str, f"{self._ctx()} skills 引用应为 str: {ref!r}")
            resolved = Path(ref) if Path(ref).is_absolute() else (OUT_CREWAI_SKILLS / ref)
            loaded.extend(crewai_load_skill(resolved))  # activate=True → INSTRUCTIONS 级
        matched = [s for s in loaded if s.name == SKILL_NAME]
        self.assertTrue(
            matched,
            f"{self._ctx()} agents.yaml 的 skills={skills_cfg} 经真实 crewai.skills.load_skill"
            f" 解析出 0 个技能(已知约束:1.15.27 loader 把路径当搜索目录,单技能目录引用无效;"
            f" 必须引用 ./skills 发现目录)",
        )
        sk = matched[0]
        desc = sk.description or ""
        self.assertTrue(
            desc.strip().startswith(DESC_HEAD),
            f"{self._ctx()} 技能 description 未被识别: {desc[:120]!r}",
        )
        # instructions(激活后的完整正文)与源 SKILL.md 正文逐字一致
        from converter.ir import parse_frontmatter

        _, body = parse_frontmatter((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(
            (sk.instructions or "").strip(), body.strip(),
            f"{self._ctx()} 技能 instructions 与 SKILL.md 正文不一致:"
            f" got_len={len((sk.instructions or '').strip())} want_len={len(body.strip())}",
        )
        print(f"[crewai runtime] 公开 API 加载 OK: name={sk.name}, desc_len={len(desc)},"
              f" disclosure={sk.disclosure_level}")

        # 4) 真实 Agent(skills=[...]) 构造期把技能解析进 agent.skills(METADATA 级)
        resolved_first = skills_cfg[0]
        resolved_first = str(resolved_first) if Path(resolved_first).is_absolute() else str(OUT_CREWAI_SKILLS / resolved_first)
        agent = Agent(
            role=self.agent_entry["role"],
            goal=self.agent_entry["goal"],
            backstory=self.agent_entry["backstory"],
            verbose=False,
            skills=[resolved_first],
        )
        records = self._collect_skill_records(agent)
        self.assertTrue(
            any(r["name"] == SKILL_NAME for r in records),
            f"{self._ctx()} Agent(skills=[...]) 构造期未解析出 name={SKILL_NAME};"
            f" 发现的记录={records}; agent.skills={getattr(agent, 'skills', None)!r}",
        )
        hit = next(r for r in records if r["name"] == SKILL_NAME)
        print(f"[crewai runtime] Agent(skills=[...]) 加载 OK: {hit['py']},"
              f" disclosure={getattr(agent.skills[0], 'disclosure_level', None)}")

        # 记录(非断言):单技能目录引用在 1.15.27 加载为空,产物不得再产出该写法
        single = Agent(role="r", goal="g", backstory="b", verbose=False, skills=[str(skill_dir)])
        print(f"[crewai runtime] 参考: 单技能目录引用加载结果 = {single.skills!r}"
              f" (None=0 技能,印证 loader 搜索目录语义)")

    def _collect_skill_records(self, agent) -> list:
        """从 Agent 实例递归抓出已解析的技能记录(name/description 字典)。"""
        records: list = []
        seen: set = set()
        stack = [agent]
        while stack:
            obj = stack.pop()
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            if isinstance(obj, (str, int, float, bool, bytes)):
                continue
            name = getattr(obj, "name", None)
            desc = getattr(obj, "description", None)
            if isinstance(name, str) and name == SKILL_NAME and isinstance(desc, str):
                records.append({"name": name, "description": desc,
                                "py": type(obj).__module__ + "." + type(obj).__name__})
            for attr in ("skills", "_skills", "loaded_skills", "agent_skills"):
                val = getattr(obj, attr, None)
                if val is None:
                    continue
                if isinstance(val, (list, tuple, set)):
                    stack.extend(val)
                else:
                    stack.append(val)
            if isinstance(obj, dict):
                stack.extend(v for v in obj.values() if not isinstance(v, (str, int, float, bool, bytes)))
        return records

    # ---------- f. crewai-skills 靶 YAML 忠实度(防折叠回归) ----------

    def test_f_crewai_skills_yaml_fidelity(self):
        """crewai-skills 靶 backstory roundtrip 与 ir.backstory() 逐字一致。

        历史 bug:_folded_entry 曾用 `>` 折叠块标量,单换行被折叠成空格,
        markdown 列表/标题结构被破坏;现已与 crewai 靶统一为 `|` 字面块标量。
        """
        import yaml

        from converter.skill_loader import load_skill as load_skill_ir

        ir = load_skill_ir(SKILL_DIR)
        expected = ir.backstory().strip()
        entry = yaml.safe_load((OUT_CREWAI_SKILLS / "config" / "agents.yaml").read_text())[SKILL_NAME]
        actual = (entry.get("backstory") or "").strip()
        self.assertEqual(
            actual, expected,
            f"{self._ctx()} crewai-skills backstory roundtrip 不一致(疑似折叠块标量回归):"
            f" yaml_len={len(actual)} want_len={len(expected)};"
            f" 换行数 yaml={actual.count(chr(10))} want={expected.count(chr(10))}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
