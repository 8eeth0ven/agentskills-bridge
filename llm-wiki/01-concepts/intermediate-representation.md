# AgentIR 规范(中间表示)

AgentIR(`converter/ir.py` 中的 `AgentIR` dataclass)是所有转换的枢纽:

```
skill ──skill_loader──▶ AgentIR ──emitters──▶ crewai / langchain / langflow / openai_agents / generic
crewai / langchain / langflow ──parsers──▶ AgentIR ──skill_writer──▶ skill
```

本文字段名与类型**与 `converter/ir.py` 严格一致**(该文件已定稿不得修改);修改任一侧必须同步另一侧。

## 顶层字段(AgentIR)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | 必填 | kebab-case id,例如 `"agent-fullcycle-engineering"`。工具函数 `slugify()` 可从任意名字生成 |
| `display_name` | `str` | `""` | 人类可读名,例如 `"Agent Fullcycle Engineering"`;未提供时 `title()` 从 name 派生 |
| `description` | `str` | `""` | 何时使用(对应 skill frontmatter `description`,即触发条件描述) |
| `system_prompt` | `str` | `""` | 主指令(对应 SKILL.md 正文 / agent 侧 instructions) |
| `default_prompt` | `str` | `""` | UI 默认提示词(对应 openai.yaml `interface.default_prompt`) |
| `tools` | `List[ToolSpec]` | `[]` | agent 可调用的工具契约列表 |
| `knowledge` | `List[KnowledgeDoc]` | `[]` | 知识文档列表,对应 skill 的 `references/<file>.md` |
| `tasks` | `List[TaskStep]` | `[]` | 任务步骤;单 agent 通常只有一步,multi-agent 编排会有多步 |
| `scripts` | `List[str]` | `[]` | skill 侧 `scripts/` 相对路径列表 |
| `metadata` | `Dict[str, Any]` | `{}` | 杂项:至少含 `source_format`(取值见常量),常见还有 `source_path`、`short_description`、`model` |

模块常量:`SOURCE_FORMATS = ("skill", "crewai", "langchain", "langflow", "generic")`,`TARGET_FORMATS = ("crewai", "langchain", "langflow", "openai", "generic")`。

## ToolSpec(工具契约)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | 必填 | 工具名 |
| `description` | `str` | `""` | 工具用途描述 |
| `input_schema` | `Dict[str, Any]` | `{}` | JSON Schema,描述工具入参 |
| `side_effects` | `bool` | `False` | 是否有副作用(写操作);True 时调用方应考虑确认/幂等 |

## KnowledgeDoc(知识文档)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `filename` | `str` | 必填 | 文件名,例如 `"crewai-patterns.md"` |
| `title` | `str` | `""` | 章节标题,例如 `"CrewAI Patterns"`(loader 取文件首个 `#` 标题) |
| `content` | `str` | `""` | markdown 正文 |
| `source_path` | `str` | `""` | 来源文件绝对/相对路径(拷贝时用) |

## TaskStep(任务步骤)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | 必填 | 步骤名 |
| `description` | `str` | `""` | 步骤描述 |
| `expected_output` | `str` | `""` | 期望产出 |
| `agent` | `str` | `""` | 承担该步骤的 agent 名;单 agent 留空 |

## 序列化与辅助方法

- `to_dict()` / `from_dict(data)`:dict 双向;`to_json(indent=2)` / `from_json(text)`(`ensure_ascii=False`,中文原样)。字段顺序固定:name → display_name → description → system_prompt → default_prompt → tools → knowledge → tasks → scripts → metadata。
- `title() -> str`:display_name 未显式提供时,把 kebab-case name 按 `-` 拆分、逐段首字母大写生成。
- `backstory(max_chars=1200) -> str`:system_prompt 精简版,供 CrewAI backstory / UI 摘要;超长时在段落/句子边界(`"\n\n"` / `"\n"` / `". "`)截断并追加 `"\n..."`。
- `slugify(text, fallback="agent") -> str`:任意文本规范成 kebab-case id(非 `[A-Za-z0-9]` 连续段折叠为 `-`,小写化;结果为空返回 fallback)。
- `parse_frontmatter(text) -> (Dict[str, str], str)`:解析平面 YAML frontmatter(只取顶层字符串字段),返回 `(meta, body)`;文本不以 `---` 开头时返回 `({}, text)`。

## 完整 JSON 示例

`AgentIR.to_json()` 的输出形状(各嵌套对象字段与上表一致):

```json
{
  "name": "agent-fullcycle-engineering",
  "display_name": "Agent Fullcycle Engineering",
  "description": "Use when Codex needs to plan or implement agent systems, tool calling, RAG, memory, orchestration, prompts, safety controls, evals, tests, observability, release handoff, or production debugging.",
  "system_prompt": "# Agent Fullcycle Engineering\n\n## Overview\n\nUse this skill to turn an agent idea into a working, testable, operable system...",
  "default_prompt": "Use $agent-fullcycle-engineering to design, delegate, build, test, observe, deploy, and adaptively optimize an AI agent from requirements to release.",
  "tools": [
    {
      "name": "scaffold_agent_project",
      "description": "Create starter planning artifacts for a new agent project",
      "input_schema": {
        "type": "object",
        "properties": {
          "name": { "type": "string", "description": "project name" },
          "output": { "type": "string", "description": "output directory", "default": "." }
        },
        "required": ["name"]
      },
      "side_effects": true
    }
  ],
  "knowledge": [
    {
      "filename": "crewai-patterns.md",
      "title": "CrewAI Patterns",
      "content": "# CrewAI Patterns\n\nCrewAI crews, flows, YAML, memory, tracing, deployment, and CLI verification...",
      "source_path": "/tmp/CrewAI-AgentCodingSkills/crewskills/skills/agent-fullcycle-engineering/references/crewai-patterns.md"
    }
  ],
  "tasks": [
    {
      "name": "deliver-agent",
      "description": "Clarify the job, choose the simplest architecture, build a vertical slice, add tests and evals, then release in stages.",
      "expected_output": "A working, tested agent with runbook, observability, and PR handoff.",
      "agent": ""
    }
  ],
  "scripts": ["scripts/scaffold_agent_project.py"],
  "metadata": {
    "source_format": "skill",
    "source_path": "/tmp/CrewAI-AgentCodingSkills/crewskills/skills/agent-fullcycle-engineering",
    "short_description": "Build agents with delegation and adaptive optimization"
  }
}
```

注意 `metadata.short_description`:它不是 AgentIR 本体字段,loader 从 `agents/openai.yaml` 读到后放进 metadata;writer 反向生成 openai.yaml 时再取出来。

## 使用约束

- IR 是唯一枢纽:emitter/parser/skill_writer/skill_loader 都只认 AgentIR,不允许格式间点对点直转。
- `name` 必须 kebab-case;外部名字不可靠时先过 `slugify()`。
- `generic` emitter 直接输出 `agent.json`(`ir.to_json()`),本文的 JSON 形状即 generic 目标格式。
