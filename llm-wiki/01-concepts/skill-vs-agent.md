# Skill 与 Agent:概念、区别与选型

本项目做的是 skill ↔ agent 双向转换,所以先把两个词的定义钉死。下文所有字段名以 `converter/ir.py` 和 `INTERFACE.md` 为准。

## 什么是 skill

skill 是**声明式知识包**:一个目录,描述"某类任务该怎么做",自身不运行,由宿主 agent(如 Codex、Claude Code 等 coding agent)在判断命中触发条件时按需加载。

最小目录结构:

```
<skill-dir>/
  SKILL.md            # frontmatter(name/description)+ 正文(主指令)
  agents/openai.yaml  # 可选:UI 界面三字段(display_name/short_description/default_prompt)
  references/*.md     # 可选:分章节知识文档,按需读取
  scripts/*           # 可选:可执行脚本,宿主 agent 直接调用
```

关键机制是**渐进披露**:SKILL.md 正文常驻,references 只在路由条件命中时才读,scripts 只在明确需要执行时才跑。skill 不自带模型、不自带工具注册表、不自带编排循环——这些全部依赖宿主。

## 什么是 agent

agent 是**可执行运行时**:一个真实跑起来的程序/服务,自己持有模型调用、工具执行、编排与状态。最小要素:

- prompt(system_prompt 定义角色与行为)
- tools(工具契约:名称、入参 schema、副作用标记)
- 编排(任务步骤、循环、多 agent 委派)
- 状态(会话记忆、checkpoint、输出产物)

典型落地形态:CrewAI crew(`config/agents.yaml` + `config/tasks.yaml`)、langchain agent(`agent.py`)、langflow flow(`flow.json`)、OpenAI 平台 agent(`agents/openai.yaml` + `instructions.md`)。

## 本质区别

| 维度 | skill | agent |
|------|-------|-------|
| 形态 | 静态文件目录(知识 + 少量脚本) | 可执行运行时(进程/服务) |
| 谁执行 | 宿主 agent 代为执行 | 自身执行 |
| 模型/密钥 | 无,复用宿主的 | 自带配置 |
| 工具 | 无注册表,scripts 只是可调用资源 | 显式 tools 契约(input_schema/side_effects) |
| 编排/状态 | 无,只有正文里的流程描述 | tasks 步骤、循环、记忆、checkpoint |
| 加载方式 | 触发条件命中后按需读 | 常驻运行或被调起 |
| 交付成本 | 零基础设施,放进目录即生效 | 需要部署/运行环境 |

一句话:**skill 是"给 agent 看的操作手册",agent 是"自己会干活的系统"**。转换器做的事就是在"手册"与"系统"之间搬运同一份能力定义,AgentIR 是搬运中的标准货箱。

## 字段映射表

skill 侧字段 ↔ agent 侧字段(以 openai/CrewAI 为代表)↔ AgentIR 字段三列对照:

| skill 侧 | agent 侧 | AgentIR 字段 |
|----------|----------|--------------|
| `SKILL.md` frontmatter `name`(kebab-case) | agent id | `AgentIR.name` |
| `SKILL.md` frontmatter `description` | 触发条件 / "何时用"描述 | `AgentIR.description` |
| `SKILL.md` 正文 | `instructions.md` / CrewAI role+goal+backstory 组装 | `AgentIR.system_prompt` |
| `agents/openai.yaml` `interface.display_name` | UI 显示名 / CrewAI role | `AgentIR.display_name` |
| `agents/openai.yaml` `interface.short_description` | UI 一句话简介 | `AgentIR.metadata["short_description"]`(IR 本体无此字段) |
| `agents/openai.yaml` `interface.default_prompt` | UI 默认输入 | `AgentIR.default_prompt` |
| `references/*.md` 每个文件 | `knowledge/*.md` / CrewAI knowledge | `AgentIR.knowledge[i]`(`KnowledgeDoc`) |
| `scripts/*` 相对路径 | 可执行资源 | `AgentIR.scripts`(list[str]) |
| ——(skill 无工具契约) | 工具定义(CrewAI/langchain tools) | `AgentIR.tools[i]`(`ToolSpec`) |
| ——(skill 无任务步骤) | `config/tasks.yaml` 任务 | `AgentIR.tasks[i]`(`TaskStep`) |
| —— | 来源/模型等环境信息 | `AgentIR.metadata`(dict,至少含 `source_format`) |

反向(agent → skill)时,agent 独有的 `tools`/`tasks` 在 skill 侧没有落点:tools 的调用说明会被并进 system_prompt 正文,tasks 退化为正文里的 Workflow 章节描述——这是有损方向,见 [agent-to-skill](../04-conversion/agent-to-skill.md)。

## 何时该用哪个

用 **skill**,当:

- 能力本质是"知识 + 流程 + 规范",执行者是宿主 coding agent(交互式、人在环上)。
- 想零基础设施交付:版本化、拷目录即生效、随 git 走。
- 内容以 references 为主、需要渐进披露控制上下文占用。

用 **agent**,当:

- 需要独立运行:定时任务、无人值守、服务化 API、并发多实例。
- 需要显式工具契约与编排状态:多步任务链、multi-agent 委派、checkpoint 恢复。
- 需要与特定框架生态集成(CrewAI crew、langflow 可视化流等)。

边界情况:同一个能力常常两种形态都要——开发期作为 skill 被宿主加载迭代,交付期转成 agent 独立部署。这正是本项目双向转换器存在的理由;字段如何搬运见 [skill-to-agent](../04-conversion/skill-to-agent.md) 与 [agent-to-skill](../04-conversion/agent-to-skill.md)。
