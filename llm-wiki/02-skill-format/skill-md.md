# SKILL.md 规范

SKILL.md 是 skill 目录的入口文件:frontmatter 提供元数据,正文是宿主 agent 常驻加载的主指令。本文以真实样例 `examples/agent-fullcycle-engineering/SKILL.md` 为参照。字段约束以 **Agent Skills 开放规范**(agentskills.io/specification;Anthropic 2025-10 随 Claude 推出、2025-12-18 移交开放标准;2026-10-11 调研核实)为权威——claude.ai 上传与 Anthropic Skills API 只接受规范 6 字段,多一个键即硬报错。

## 整体结构

```markdown
---
name: <kebab-case-id>
description: <触发条件描述,一段话>
---

# <Display Name>

## Overview
...

## Response Modes
...

## Reference Routing
...

## Workflow
...

## 工程默认值(Engineering Defaults)
...
```

## YAML frontmatter

只有两个必填字段,平面字符串(与 `ir.py` 的 `parse_frontmatter` 能力匹配——它只解析顶层 `key: value`,不支持嵌套结构):

- **`name`**:skill 的 id,**必须 kebab-case**(全小写,单词用 `-` 连接),如 `agent-fullcycle-engineering`;规范约束:1–64 字符,`^[a-z0-9]+(-[a-z0-9]+)*$`,不得以连字符开头/结尾、不得连续 `--`,且**必须与父目录名一致**。载入 AgentIR 后即 `AgentIR.name`。不可靠的名称先过 `slugify()`。
- **`description`**:**触发条件描述**,不是功能简介。写清楚"什么情况下宿主 agent 应当加载本 skill",面向的是做路由决策的模型。样例的写法:先一句概括能力,再 `Use when Codex needs to ...` 列举触发场景(计划/实现 agent 系统、tool calling、RAG、evals、调试、部署等)。description 质量直接决定触发命中率,应当穷举用户可能的说法。规范约束:1–1024 字符、非空。

权威字段表(agentskills.io/specification,2026-10 校准):

| 字段 | 必需 | 约束 |
|---|---|---|
| `name` | 是 | 1–64 字符;仅小写字母数字与连字符;不得首尾连字符、不得连续 `--`;必须与父目录名一致 |
| `description` | 是 | 1–1024 字符,非空 |
| `license` | 否 | 许可证名或指向捆绑 license 文件的引用;建议短 |
| `compatibility` | 否 | 1–500 字符;环境要求(目标产品、系统包、网络),确有要求才写 |
| `metadata` | 否 | string→string 自由 map;**顶层无 `version` 字段,版本号只能放 `metadata.version`** |
| `allowed-tools` | 否 | 空格分隔预授权工具串(如 `Bash(git:*) Read`);**实验性**,各实现支持不一 |

注意:`metadata` 是嵌套 map,本项目 `ir.py` 的 `parse_frontmatter` 只解析顶层平面 `key: value`,读入时该键不承载——需要保留的额外键(license/version 等)转换前手工记入,见 [skill-to-agent](../04-conversion/skill-to-agent.md) 有损点清单。

渐进披露三层体量约束(规范建议):①metadata 层(name+description)启动时常驻,约 100 tokens/skill;②instructions 层命中时整文加载,**建议 <5000 tokens、SKILL.md <500 行**;③resources 层(scripts/references/assets)按需读取,引用路径相对 skill 根、深度保持一层。

frontmatter 之外的字段(如 display_name、default_prompt)不放这里,放 `agents/openai.yaml`(见 [openai-interface-yaml](openai-interface-yaml.md))。

## 正文结构

正文整体成为 `AgentIR.system_prompt`,宿主 agent 命中触发后常驻。推荐章节骨架(参考样例逐章对应):

1. **`# 标题`**:display_name 形式的人类可读名(如 `# Agent Fullcycle Engineering`)。
2. **Overview**:一两段说清本 skill 把什么变成什么(样例:把 agent 想法变成可运行、可测试、可运维的系统),点出能力覆盖面。
3. **Response Modes**:按用户意图分流响应方式。样例列出四种模式(Beginner learning / Interview preparation / Project delivery / Debugging or review),每种给判定标准和该模式的输出要求;对新手还规定了讲解顺序。这章解决"同一个知识包服务不同意图"的路由问题。
4. **Reference Routing**:references 路由表,写法见下节。
5. **Workflow**(样例为 "Full Lifecycle Workflow"):默认执行顺序的编号步骤。样例 9 步:clarify the job → map the environment → choose the simplest architecture → design contracts → plan the development loop → build a vertical slice → add tests and evals → add operations → release in stages。架构选择内置升级链:deterministic code → single LLM call → tool calling → RAG → workflow orchestration → planner/executor 或 multi-agent,能简单不复杂。
6. **工程默认值**(样例为 "Engineering Defaults"):硬性工程约束清单,每条可执行可判定。样例要点:优先最简架构;subagent 只做边界清晰、可独立验证的委派且默认并发不超过 3、写所有权不重叠;模型生成的工具参数一律视为不可信输入;副作用工具尽量幂等、不可逆操作需确认;RAG 生产化前置条件(chunk 策略/权限过滤/引用/no-answer 行为);日志要能重放(request id、model、prompt 版本、工具调用、延迟、token/成本);先定 eval gate 再发布;调试只 patch 最窄失败层并先补回归用例。

可按需扩展领域章节:样例另加了 Adaptive Scheduled Optimization(自适应定时优化的启用条件与安全约束)、Senior Acceptance Gates(交付前自检清单)、CrewAI Development Mode(框架特化打法)、Project Scaffold(脚手架脚本用法)、Minimum Done Definition(完成定义)。原则:默认骨架保序可裁,领域章节追加在骨架之后。

## references 路由写法

references 的价值在**渐进披露**:正文只放路由规则,内容放 `references/*.md`,宿主按需读取。路由写法两种,样例都有:

**逐文件推荐句**(适合长文/主参考):

```markdown
For a complete beginner-friendly article with examples, terms, and use cases,
read `references/beginner-agent-engineer-guide.md`.
For a shorter beginner-friendly learning path, read `references/agent-engineer-roadmap.md`.
```

**场景 → 文件 bullet 表**(适合任务型参考,一行一个触发场景):

```markdown
- Architecture selection, state, memory, planner/executor, or multi-agent
  choices: `references/architecture-patterns.md`.
- Tests, eval datasets, quality metrics, release gates: `references/evaluation-testing.md`.
- Runtime failures, broken tools, loops, root-cause isolation: `references/debugging-playbook.md`.
```

写法规则:

- 路径写 skill 目录内相对路径 `references/<file>.md`,文件名 kebab-case。
- 每条路由 = 触发场景关键词 + 文件路径;场景描述用用户问题的词汇,便于语义匹配。
- 少数高风险参考可加前置条件,如样例:"Read it before delegating substantial work or defining adaptive automation"。
- Workflow 章末尾可重复一遍"做某步读某文件"的短路由,把流程与参考挂钩。
- 每个 reference 文件首行是 `# 标题`,loader 取它作 `KnowledgeDoc.title`。

## 加载与反向生成

- `skill_loader.load_skill()`:frontmatter → `AgentIR.name/description`,正文 → `system_prompt`,`references/*.md` → `knowledge`,详见 [skill-to-agent](../04-conversion/skill-to-agent.md)。
- `skill_writer.write_skill()`:反向生成 SKILL.md 时,frontmatter 只写 `name`/`description`,system_prompt 整体作为正文,详见 [agent-to-skill](../04-conversion/agent-to-skill.md)。
