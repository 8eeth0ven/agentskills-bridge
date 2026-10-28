# agents/openai.yaml 规范

`agents/openai.yaml` 是 skill 目录中的可选界面层文件,为 OpenAI 平台侧(Codex / ChatGPT UI)提供显示与默认输入配置。参考样例:`examples/agent-fullcycle-engineering/agents/openai.yaml`。

## 完整格式

只有一个顶层键 `interface`,下面固定三个字段,全部为字符串:

```yaml
interface:
  display_name: "Agent Fullcycle Engineering"
  short_description: "Build agents with delegation and adaptive optimization"
  default_prompt: "Use $agent-fullcycle-engineering to design, delegate, build, test, observe, deploy, and adaptively optimize an AI agent from requirements to release."
```

## 字段说明

| 字段 | 必填 | 说明 | AgentIR 去向 |
|------|------|------|--------------|
| `interface.display_name` | 是 | 人类可读显示名(标题格式,非 kebab-case),如 `"Agent Fullcycle Engineering"` | `AgentIR.display_name` |
| `interface.short_description` | 是 | 一句话 UI 简介,说明能力范围 | `AgentIR.metadata["short_description"]`(IR 本体无此字段) |
| `interface.default_prompt` | 是 | UI 默认提示词,用户打开 agent 时预填的输入 | `AgentIR.default_prompt` |

约定:

- 三字段值为纯字符串,统一带双引号,避免 YAML 裸词/特殊字符歧义。
- `default_prompt` 中的 `$<skill-name>` 语法用于引用本 skill(样例:`Use $agent-fullcycle-engineering to ...`),`<skill-name>` 与 SKILL.md frontmatter `name` 一致。
- 文件缺失时 skill_loader 容忍:三字段取默认空值/从 name 派生,不报错。

## 在双向转换中的角色

- **skill → agent**(`skill_loader.load_skill`):读取 `agents/*.yaml` 的 `interface.display_name/short_description/default_prompt`;`display_name`/`default_prompt` 进 AgentIR 本体字段,`short_description` 进 `metadata`。metadata 整体形如 `{"source_format": "skill", "source_path": <abs>, "short_description": ...}`。
- **agent → skill**(`skill_writer.write_skill`):从 AgentIR 反向生成 `agents/openai.yaml`,`display_name` 缺失时用 `ir.title()` 从 name 派生。
- **openai_agents emitter**:向 openai 目标输出时也生成同格式文件(与原仓库格式对齐),同目录伴随 `instructions.md`(完整 system_prompt)+ `knowledge/*.md` + `README.md`,详见 [openai-agents](../03-frameworks/openai-agents.md)。

## 与 SKILL.md 的分工

SKILL.md frontmatter 管**触发路由**(name + description,给宿主 agent 判断何时加载);openai.yaml 管**界面呈现**(显示名 + 简介 + 默认输入,给平台 UI 展示)。两处 `name` 引用必须一致;display_name 与 SKILL.md 正文首行 `# 标题` 保持同一写法。
