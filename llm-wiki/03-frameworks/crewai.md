# CrewAI

CrewAI 是角色驱动的多 agent 编排框架:agent 属性放 `config/agents.yaml`,任务放 `config/tasks.yaml`,Python 端用 `Crew`/`Agent`/`Task` 装配执行;`Flow` 提供事件驱动的多步骤编排;`knowledge/` 目录存放可检索的知识文件。自 v1.12.0(2026-03-25)起原生支持 Anthropic 风格 Agent Skills(`./skills/` 目录 + SKILL.md),见下文专节。

## 最小可用示例

标准目录结构(可由 `crewai create crew my_crew` 生成后精简):

```text
my_crew/
├── .env                    # OPENAI_API_KEY=sk-...
├── main.py                 # 入口
├── crew.py                 # 装配 YAML 的 Python 层
├── config/
│   ├── agents.yaml
│   └── tasks.yaml
└── knowledge/
    └── agentir.md          # 知识片段,按需挂载
```

`config/agents.yaml`(单 agent 最小配置):

```yaml
note_writer:
  role: >
    技术笔记撰写助手
  goal: >
    根据用户给的主题,写出一篇结构清晰、可直接使用的技术笔记
  backstory: >
    你是一名资深技术作者,擅长把零散信息整理成结构化笔记。
    只依据给定信息与自身可靠知识写作,不编造事实,输出 Markdown。
  llm: openai/gpt-4o-mini
  verbose: false
```

`config/tasks.yaml`(单任务最小配置):

```yaml
write_note_task:
  description: >
    围绕用户输入的主题 {topic},撰写一篇技术笔记,
    必须包含「概述 / 要点 / 示例」三节。
  expected_output: >
    一篇 Markdown 笔记,含概述、要点、示例三节,正文 300 字以内。
  agent: note_writer
  context: []
```

`crew.py`(把 YAML 装配成可运行的 Crew):

```python
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.knowledge.source.text_knowledge_source import TextKnowledgeSource


@CrewBase
class NoteCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def note_writer(self) -> Agent:
        return Agent(config=self.agents_config["note_writer"])

    @task
    def write_note_task(self) -> Task:
        return Task(config=self.tasks_config["write_note_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,          # @agent 装饰的方法自动汇入
            tasks=self.tasks,            # @task 装饰的方法自动汇入
            process=Process.sequential,
            knowledge_sources=[
                TextKnowledgeSource(file_paths=["knowledge/agentir.md"]),
            ],
            verbose=True,
        )
```

`main.py`:

```python
from crew import NoteCrew

if __name__ == "__main__":
    result = NoteCrew().crew().kickoff(inputs={"topic": "AgentIR"})
    print(result.raw)
```

Flow 编排(独立于 Crew 的事件流,装饰器驱动):

```python
from crewai.flow.flow import Flow, listen, router, start


class NoteFlow(Flow[dict]):
    @start()
    def collect_topic(self) -> dict:
        return {"topic": "AgentIR"}

    @listen(collect_topic)
    def write_note(self, data: dict) -> str:
        return NoteCrew().crew().kickoff(inputs=data).raw

    @router(write_note)
    def check(self, note: str) -> str:
        return "ok" if len(note) > 100 else "retry"

    @listen("retry")
    def retry(self, _ignored: str) -> None:
        print("笔记过短,触发重试分支")
```

CLI 常用命令:

| 命令 | 作用 |
|---|---|
| `crewai create crew <name>` | 生成标准项目骨架 |
| `crewai run` | 执行 main.py(kickoff) |
| `crewai test` | 对 crew 跑评测,需 evaluations/ 配置 |
| `crewai replay <task_id>` | 重放历史执行中的单个任务(旧版本为 `crewai replay -s <session_id> <task_id>`) |
| `crewai log-tasks-outputs` | 列出各任务输出,便于核对 expected_output |
| `crewai flow kickoff` | 运行 Flow 入口 |

## 字段说明

`config/agents.yaml`:

| 字段 | 类型 | 说明 |
|---|---|---|
| (顶层 key) | str | agent 标识(snake_case),Python 端 `self.agents_config["note_writer"]` 按此取 |
| `role` | str | 角色头衔,进入 system prompt 的角色段 |
| `goal` | str | 目标:该 agent 要达成什么 |
| `backstory` | str | 背景与行为约束,与 role/goal 共同拼成 system prompt |
| `llm` | str | 模型标识,如 `openai/gpt-4o-mini` |
| `verbose` | bool | 是否打印执行日志 |

常用可选字段:`tools`(工具名列表,需 Python 端注入实例)、`allow_delegation`、`max_iter`、`memory`、`step_callback`。

`config/tasks.yaml`:

| 字段 | 类型 | 说明 |
|---|---|---|
| (顶层 key) | str | 任务标识(snake_case) |
| `description` | str | 任务描述,支持 `{variable}` 占位,kickoff 时用 inputs 填充 |
| `expected_output` | str | 期望输出格式的自然语言描述,是输出契约 |
| `agent` | str | 执行者,必须与 agents.yaml 顶层 key 一致 |
| `context` | list[str] | 依赖的其他任务 key,前置任务输出会注入本任务 |

常用可选字段:`output_file`(结果写盘)、`async_execution`、`human_input`、`output_json`、`output_pydantic`、`tools`。

Flow 装饰器:

| 装饰器 | 说明 |
|---|---|
| `@start()` | 流程起点,一个 Flow 至少一个 |
| `@listen(method)` | 监听上游方法,上游返回值作为参数传入;也可监听字符串别名 |
| `@router(method)` | 根据返回值路由,返回值匹配 `@listen("别名")` 分支 |

## 原生 Agent Skills 支持(v1.12.0+)

CrewAI 自 **v1.12.0(2026-03-25,changelog "Implement agent skills")** 起原生支持与 Anthropic Agent Skills 同构的 SKILL.md 机制。以下结论来源:docs.crewai.com `/concepts/skills`(版本化快照 v1.15.27)+ 官方 changelog + PyPI `crewai==1.15.27`(2026-10-11 调研核实)。注意区分:`docs.crewai.com/en/skills` 的 crewaiinc/skills 技能包是"教编码代理怎么写 CrewAI"的 SKILL.md 库,与运行时机制无关。

**目录约定**:crew 项目根 `./skills/{skill-name}/`,必须含 `SKILL.md`(YAML frontmatter + markdown 正文),可选 `scripts/`、`references/`、`assets/`;目录名必须与 frontmatter `name` 一致。项目外共享缓存为 `~/.crewai/skills/{org-uuid}/{name}/`。`crewai create crew`(默认 JSON-first 模板与 `--classic` 模板)都自带空 `skills/` 目录。

**启用字段**是 Agent/Crew 的 `skills`(复数列表;没有 `use_skills`/`skills_path`)。源码定义 `skills: list[Path | Skill | str] | None`;Crew 同名字段对全体 agent 生效,同名 skill 时 agent 级优先、按 name 去重。四种取值(`crewai/skills/loader.py::load_skill`):

| 取值 | 示例 | 运行时语义 |
|---|---|---|
| 目录路径 | `skills=["./skills"]` 或 `skills=["./skills/security-audit"]` | 目录引用=渐进发现(模型按需 `load_skill`);单 skill 子目录引用=always-on 全文常驻 |
| registry 引用 | `skills=["@org-uuid/code-review@1.2.0"]` | 从本地缓存/项目 skills/ 解析;版本 pin 依赖 frontmatter `metadata.version`(registry v1.15.4 转正) |
| inline 字符串(v1.15.2+) | `skills=["---\nname: ...\n---\n正文"]` | 以 `---` 开头的整段 SKILL.md,always-on(CRLF 兼容需 v1.15.22) |
| 预激活 Skill 对象 | `discover_skills(Path("./skills"))` + `activate_skill(s)` 后传入 | always-on |

**YAML/JSONC 声明式同样可写**:`config/agents.yaml` 的键经 `process_config` 映射到 Agent 任意 model_field(`skills` 是公开字段),直接写 `skills: ["./skills"]`;新式 `agents/<name>.jsonc` 支持任何公开 Agent 字段顶层出现,同样可用。

```yaml
researcher:
  role: "{topic} Senior Data Researcher"
  goal: "Uncover cutting-edge developments in {topic}"
  backstory: "..."
  skills: ["./skills"]        # v1.12.0+ 可用,解析同 Python 构造参数
```

**CLI 命令**(源码 `lib/cli/src/crewai_cli/skills/main.py`):

| 命令 | 说明 |
|---|---|
| `crewai create skill <name>` | 脚手架生成 `./skills/<name>/`(SKILL.md 模板 + scripts/references/assets);旧命令 `crewai skill create` 已弃用(仍可用,有警告) |
| `crewai skill publish` | 在 skill 目录内执行,读 frontmatter 的 name/description/metadata.version 推送注册表(org 私有;`--org <slug>`、`--force`) |
| `crewai skill install @org-uuid/name` | 安装到项目 `./skills/` 或全局缓存;必须用 org UUID(`crewai org list` 查) |
| `crewai skill list` | 列出项目与全局已装 skill(版本、路径) |

没有 `crewai add skill` / `crewai import-skill`(创建叫 `crewai create skill`)。

**运行时三级渐进披露**(v1.15.9 "Implement progressive disclosure for skills";源码 DisclosureLevel = METADATA/INSTRUCTIONS/RESOURCES):

1. **Discovery**:Agent 初始化(`set_skills()`)只加载每个 skill 的 frontmatter,name+description 渲染进系统提示目录块(`<skill name="...">` XML 包裹,官方称作为 prompt-cache 稳定锚点);
2. **Activation**:存在 metadata 级 skill 时运行时自动给 agent 挂内部工具 `load_skill`(与其他工具重名时自动改名 `load_skill_2`…);模型按需调用拉取完整 SKILL.md 正文,以 `<skill name="...">description+instructions</skill>` XML 块注入当次执行,作用域仅当次、不累积;
3. **Resources**:`scripts/`/`references/`/`assets/` 清单显式 `load_resources()` 时才读。

**版本门槛**:`crewai>=1.12.0`(skills 字段)、`>=1.15.2`(inline)、`>=1.15.4`(registry 转正);SKILL.md 可写 `compatibility: crewai>=1.12.0`。frontmatter 字段与 Anthropic 规范同构(name/description/license/compatibility/metadata/allowed-tools;`allowed-tools` 为实验性元数据,不注入任何工具)。另外 skills ≠ knowledge(方法论整体注入 prompt vs ChromaDB 语义检索)、skills ≠ tools(不提供可调用函数,tools/mcps/apps 需另行配置)。

## 与 AgentIR 的映射

| AgentIR 字段 | CrewAI 落点 |
|---|---|
| `name` | agents.yaml 顶层 key(kebab-case 转 snake_case);README 项目名 |
| `display_name` | `role` |
| `description` | `goal` |
| `system_prompt` | `backstory`(经 `ir.backstory(max_chars)` 精简) |
| `default_prompt` | README 中的 kickoff 示例输入,不进 YAML |
| `tools` | 不进 YAML;README/crew.py 模板注明需人工补 `Agent(tools=[...])` |
| `knowledge` | 逐文件拷贝到 `knowledge/*.md`,README 说明 knowledge_sources 装配 |
| `tasks` | tasks.yaml 单任务:TaskStep → `description`,期望格式 → `expected_output` |
| `scripts` / `metadata` | 不映射,README 记录来源信息 |
| —(产物形态) | `./skills/<name>/` 目录本身就是一种转换产物形态(对应工具的 **crewai-skills** target,见 [skill-to-agent](../04-conversion/skill-to-agent.md)):SKILL.md + scripts/references/assets 原样落位,另在 agents.yaml 对应 agent 上补 `skills: ["./skills"]` 挂载 |

反向 `parse_crewai(config_dir)`:role/goal/backstory 按固定格式拼回 system_prompt——

```text
# {display_name}

## Role
{role}

## Goal
{goal}

## Backstory
{backstory}
```

并写入 `metadata={"source_format": "crewai"}`。

## 转换注意事项

1. **一对三拆分有损**:AgentIR 只有一个整段 `system_prompt`,CrewAI 拆成 role/goal/backstory 三段。emit 侧靠 `ir.backstory()` 截断会丢长文;parse 侧靠 `## Role/## Goal/## Backstory` 标题识别,手改过的 YAML 拼回后结构会乱,需人工核对。
2. **YAML 手写生成**:emit 不依赖 pyyaml,值中的引号、换行、缩进必须自行转义,否则解析失败;含冒号或多行的 backstory 要走块标量(`>-`)。
3. **执行参数无对应**:`llm`(模型选择)、`max_iter`、`memory`、`process` 等在 AgentIR 中没有字段,转换后需人工补。
4. **Flow 编排丢失**:AgentIR 无流程图概念,emit 只生成单任务 Crew,不生成 Flow;反向遇到 Flow 工程也只解析主链上的 Crew,`@listen`/`@router` 分支结构全部丢失。
5. **任务依赖丢失**:tasks.yaml 的 `context` 在单任务形态下无意义;多任务工程 parse 时任务间依赖顺序不保留。
6. **纯 YAML 不能独立运行**:`crewai run` 需要 Python 装配层(crew.py + main.py)。emit 只产 YAML + knowledge + README,装配代码由用户按 README 模板补齐。
7. `crewai replay` / `crewai log-tasks-outputs` 依赖本地执行记录(outputs/ 或 SQLite),只对真实跑过的工程有意义,转换产物首次运行后才有可重放内容。
