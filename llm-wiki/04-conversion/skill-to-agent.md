# skill → agent 转换规则全解

本章定义 skill 目录到九种转换目标(既有五个:crewai / langchain / langflow / openai / generic;2026-10 官方调研后新增三个:crewai-skills / deepagents / claude-subagent;第 9 个 autogen:AG2 `AssistantAgent` 形态)的正向转换规则。所有规则以 `converter/ir.py` 的 AgentIR 字段与 `INTERFACE.md` 契约为准,字段名一律与代码严格一致。

- 入口:`converter/skill_loader.py` 的 `load_skill(skill_dir: str | Path) -> AgentIR`
- 出口:`converter/emitters/*.py` 的 `emit_<fmt>(ir: AgentIR, out_dir: str | Path) -> Path`
- CLI:`python cli.py skill2agent <skill_dir> --target crewai|langchain|langflow|openai|generic|crewai-skills|deepagents|claude-subagent|autogen --out <dir>`(target 名 `openai` 映射到 `emitters.openai_agents`)

## 1. 转换流水线总览

```
SkillDir
 ├── SKILL.md            frontmatter(name/description) + 正文(system_prompt)
 ├── agents/*.yaml       interface.display_name / short_description / default_prompt
 ├── references/*.md     knowledge: list[KnowledgeDoc]
 └── scripts/*           scripts: list[str](相对路径)
          │
          ▼  load_skill()
       AgentIR(converter/ir.py,已定稿,不得修改)
          │
          ├─▶ emit_crewai        → config/agents.yaml + config/tasks.yaml + knowledge/ + README.md
          ├─▶ emit_langchain     → agent.py + requirements.txt + README.md(+ knowledge/)
          ├─▶ emit_langflow      → flow.json + knowledge/ + README.md
          ├─▶ emit_openai_agents → agents/openai.yaml + instructions.md + knowledge/ + README.md
          ├─▶ emit_generic       → agent.json(ir.to_json())+ knowledge/ + README.md
          ├─▶ emit_crewai_skills   → skills/<name>/ 目录 + agents.yaml 补 skills 字段(2026-10 新增)
          ├─▶ emit_deepagents      → agent.py 用 create_deep_agent(skills=...)(2026-10 新增)
          └─▶ emit_claude_subagent → .claude/agents/<name>.md frontmatter+正文(2026-10 新增)
```

阶段职责:

| 阶段 | 模块 | 职责 | 失败语义 |
|------|------|------|----------|
| 装载 | `skill_loader.load_skill` | 把 skill 目录读成规范 AgentIR | `agents/*.yaml` 键缺失容忍;`references/`、`scripts/` 缺失视为空列表 |
| 中转 | AgentIR | 唯一中间表示,不做任何框架特化 | — |
| 发射 | `emit_<fmt>` | 把同一份 IR 落到目标框架目录 | 已存在则覆盖文件 |

## 2. load_skill:skill → AgentIR 字段映射

| skill 源 | AgentIR 字段 | 规则 |
|----------|--------------|------|
| `SKILL.md` frontmatter `name` | `name` | 原样读入;约定源文件已是 kebab-case(如 `agent-fullcycle-engineering`) |
| `SKILL.md` frontmatter `description` | `description` | 原样读入("何时使用"语义) |
| `SKILL.md` 正文(frontmatter 之后) | `system_prompt` | 全文原样,不做裁剪/改写 |
| `agents/*.yaml` → `interface.display_name` | `display_name` | 容忍缺失;下游用 `ir.title()` 兜底(见 §2.1) |
| `agents/*.yaml` → `interface.short_description` | `metadata["short_description"]` | 容忍缺失 |
| `agents/*.yaml` → `interface.default_prompt` | `default_prompt` | 容忍缺失 |
| `references/*.md` | `knowledge: list[KnowledgeDoc]` | 每文件一个 `KnowledgeDoc`:`filename`=相对文件名(如 `crewai-patterns.md`)、`title`=文件内首个 `#` 标题(缺失则空串)、`content`=全文、`source_path`=源文件路径(拷贝时用) |
| `scripts/*` | `scripts: list[str]` | scripts/ 下相对路径清单 |
| —(skill 源无此概念) | `tools` / `tasks` | 空列表 |
| — | `metadata` | `{"source_format": "skill", "source_path": <abs>, "short_description": ...}` |

约束:

- `knowledge` 内 `filename` 必须唯一,否则落盘互相覆盖。
- frontmatter 解析用 `ir.parse_frontmatter(text)`:只认平面 `key: value` 字符串字段,因此 `SKILL.md` frontmatter 不应出现嵌套结构/列表。
- `metadata["source_format"]` 只能取 `ir.py` 的 `SOURCE_FORMATS`(`"skill"`, `"crewai"`, `"langchain"`, `"langflow"`, `"generic"`)之一。

### 2.1 IR 派生工具(ir.py 自带,emitter 直接调用)

| 方法/函数 | 行为 | 正向转换用途 |
|-----------|------|--------------|
| `title()` | `display_name` 非空则返回;否则把 `name` 按 `-` 切分、逐段首字母大写拼出 | crewai 的 `role`、openai.yaml 的 `display_name` |
| `backstory(max_chars=1200)` | `system_prompt.strip()` ≤ max_chars 时原样返回;否则取 `text[:max_chars]`,在 `\n\n` → `\n` → `". "` 中找最后一个边界(位置须 > max_chars//2)截断并追加 `"\n..."`,找不到则硬截加 `"..."` | crewai 的 `backstory` |
| `slugify(text, fallback="agent")` | 非字母数字连续段替换为 `-`,strip 首尾 `-`,小写;结果为空返回 `fallback` | 兜底生成合法 `name` |

## 3. 逐框架 emitter 规则

总表(IR 字段 → 各框架落点):

| IR 字段 | crewai | langchain | langflow | openai_agents | generic |
|---------|--------|-----------|----------|---------------|---------|
| `name` | `config/agents.yaml` 的 `name` 键 | agent.py 内 agent 变量/文件命名 | flow.json 的 `id`(文件名沿用) | 产物目录内 `agents/openai.yaml` 所属 skill 名 | `agent.json` 的 `name` |
| `display_name` | `role` | agent.py 头部注释 | — | `agents/openai.yaml` → `interface.display_name` | `agent.json` 的 `display_name` |
| `description` | `goal` | — | — | `interface.short_description` 的来源之一 | `agent.json` 的 `description` |
| `system_prompt` | `backstory` = `ir.backstory()` 精简版 | `SystemMessagePromptTemplate` 内嵌全文 | SystemPrompt 组件 `data.template` | `instructions.md` 全文 | `agent.json` 的 `system_prompt` |
| `default_prompt` | 无槽位(降级) | 无槽位(降级) | 无槽位(降级) | `interface.default_prompt` | `agent.json` 的 `default_prompt` |
| `knowledge` | `knowledge/*.md` 整文件拷贝 | `knowledge/*.md` + agent.py 注释清单 | 同目录 `knowledge/` 拷贝 | `knowledge/*.md` | `knowledge/*.md`(内容另完整存于 `agent.json`) |
| `tasks` | `config/tasks.yaml` 单任务 | — | — | — | `agent.json` 的 `tasks` |
| `tools` | — | agent.py tools stub | — | — | `agent.json` 的 `tools` |
| `scripts` | 不拷贝(仅 IR 留名单) | 不拷贝 | 不拷贝 | 不拷贝 | `agent.json` 的 `scripts` 名单 |
| `metadata` | — | — | — | `short_description` 来源 | `agent.json` 的 `metadata` |

### 3.1 crewai

产物:`config/agents.yaml` + `config/tasks.yaml` + `knowledge/*.md` + `README.md`(如何 `crewai run`)。

`config/agents.yaml` 键映射:

| agents.yaml 键 | 来源 | 说明 |
|----------------|------|------|
| `name` | `ir.name` | agent 标识,tasks.yaml 通过它引用 |
| `role` | `ir.title()` | display_name 优先,缺失由 name 派生 |
| `goal` | `ir.description` | "何时用"语义映射为 crewai 目标 |
| `backstory` | `ir.backstory()` | system_prompt 精简版,默认 `max_chars=1200` |
| `verbose` | 固定 `false` | 契约规定 |

`config/tasks.yaml` 单任务:

| tasks.yaml 键 | 来源 |
|---------------|------|
| `description` | `tasks[0].description`,skill 源通常为空 → 用 `system_prompt`(完整主指令兜底,弥补 backstory 截断) |
| `expected_output` | `tasks[0].expected_output`,缺省给默认文案 |
| `agent` | 指向 agents.yaml 的 `name`(即 `ir.name`) |

实现约束:YAML 手写生成(不依赖 pyyaml),值需正确引号/缩进。

### 3.2 langchain

产物:`agent.py` + `requirements.txt` + `README.md`。纯文本生成,不需要真跑 langchain。

- `agent.py`:`SystemMessagePromptTemplate` + tools stub + `create_agent`(或通用 `create_react_agent`)形式;
  - system prompt:`SystemMessagePromptTemplate.from_template(...)` 内嵌 `ir.system_prompt` **全文**;
  - knowledge:以**文件清单/相对路径**注入——agent.py 顶部注释逐行列 `knowledge/<filename> — <title>`,prompt 中引用该路径;
  - tools:`ir.tools` 为空时生成占位 tool stub(skill 源常态)。
- `knowledge/*.md` 整文件拷贝到输出目录(与清单路径对应)。

### 3.3 langflow

产物:`flow.json` + 同目录 `knowledge/` + `README.md`(说明导入方式)。

`flow.json` 必须是合法 Langflow 包导出格式:

```json
{"id": "...", "data": {"nodes": [...], "edges": [...], "viewport": {...}}}
```

| 要素 | 规则 |
|------|------|
| 节点链 | `ChatInput` → `Prompt`(SystemPrompt 组件)→ `OpenAIAgent`/`LLM` → `ChatOutput` |
| SystemPrompt 组件 | `data.template` 内嵌 `ir.system_prompt` 全文 |
| 每个节点 | 必含 `id` / `type` / `position` / `data.template` 四键 |
| edges | 带 source/target 节点 id 与 handle 名 |

### 3.4 openai_agents

产物:`agents/openai.yaml` + `instructions.md` + `knowledge/*.md` + `README.md`(Codex/ChatGPT UI 用法),与原仓库格式对齐。

| 文件 | 内容 |
|------|------|
| `agents/openai.yaml` | `interface.display_name`(=`ir.title()`)/ `interface.short_description`(=`metadata["short_description"]`,缺省用 `description`)/ `interface.default_prompt`(=`ir.default_prompt`) |
| `instructions.md` | `ir.system_prompt` **完整全文**,不截断 |
| `knowledge/*.md` | 整文件拷贝 |

这是唯一同时保留 `display_name` + `short_description` + `default_prompt` 三件套的非 generic 目标。

### 3.5 generic

产物:`agent.json` + `knowledge/*.md` + `README.md`。

- `agent.json` = `ir.to_json()`(`to_dict` → `json.dumps(indent=2, ensure_ascii=False)`),含全部字段:`name/display_name/description/system_prompt/default_prompt/tools/knowledge/tasks/scripts/metadata`——**零信息损失**的兜底格式,序列化/反序列化走 `AgentIR.to_json()/from_json()`。
- `knowledge/*.md` 仍整文件拷贝(`agent.json` 里虽有 `content`,落盘保证框架无关可用)。

### 3.6 新增目标(2026-10 官方调研后)

三个新 target 的 IR→产物要点(来源:各框架官方文档/源码调研,2026-10-11;版本与机制详见对应框架章):

| target | 产物 | IR→产物要点 |
|--------|------|-------------|
| `crewai-skills` | `skills/<name>/`(SKILL.md + scripts/references/assets)+ agents.yaml 片段 | skill 目录本身就是产物形态(CrewAI v1.12.0+ 原生支持,frontmatter 与 Anthropic 规范同构);在对应 agent 上补 `skills: ["./skills"]`(目录引用=渐进发现),精准挂载写 `skills: ["./skills/<name>"]`(=always-on);要求 crewai>=1.12.0(inline >=1.15.2);`compatibility: crewai>=1.12.0`、`metadata.version` 供 registry pin |
| `deepagents` | `agent.py`(入口)+ `skills/<name>/` | agent.py 用 `create_deep_agent(skills=["./skills/"])` 原生解析 SKILL.md(渐进披露/`metadata.include_tools`/源可直接用 `~/.claude/skills`);依赖 `deepagents>=0.7`(当前 0.7.23);system_prompt 全文保留在 SKILL.md,不手工拼进代码 |
| `claude-subagent` | `.claude/agents/<name>.md` | Markdown + YAML frontmatter + 正文即 system prompt:`name`/`description` 必需(name ≤256、不含 `:`、不以 `-` 开头);多词字段 camelCase(`disallowedTools`/`maxTurns`);`---` 必须是文件第一行,否则整个文件被当正文 |

与 §5 有损点清单的关系:crewai-skills / deepagents 以 SKILL.md 原生形态为产物,渐进披露语义与 scripts/ 迁移不降级;claude-subagent 与既有 Markdown 目标同级。

## 4. 知识(references)迁移策略

统一策略:**整文件拷贝 + prompt 内列路由清单**,两级缺一不可。

| 框架 | 文件落盘 | 路由清单落点 |
|------|----------|--------------|
| crewai | `out/knowledge/<filename>` | `backstory`/task `description` 末尾列 `filename — title` |
| langchain | `out/knowledge/<filename>` | agent.py 顶部注释清单 + prompt 引用路径 |
| langflow | flow.json 同目录 `knowledge/<filename>` | SystemPrompt template 末尾追加(或 README 说明) |
| openai_agents | `out/knowledge/<filename>` | `instructions.md` 末尾清单 |
| generic | `out/knowledge/<filename>` | `agent.json` 的 `knowledge` 数组(filename/title/content/source_path)即机器可读清单 |

规则:

1. 拷贝以 `KnowledgeDoc.filename` 为目标文件名、`content` 为内容(或经 `source_path` 直拷),**不拆分、不摘要**——保住 roundtrip 逐字节回读的可能。
2. 路由清单格式统一 `knowledge/<filename> — <title>`,让目标框架的 agent 知道"何时读哪份"。
3. `title` 为空(reference 无 `#` 标题)时清单里退化为只列文件名;建议源 skill 每份 reference 首行写 `#` 标题。

## 5. 有损点清单

| # | skill 特性 | IR 承载 | 降级情况(按框架) | 人工补法 |
|---|-----------|---------|--------------------|----------|
| 1 | `scripts/*` 可执行 | `scripts: list[str]` 仅路径名单 | 既有五个 emitter 产物契约均**不含 scripts/ 目录拷贝**:可执行文件本体不随迁移(新增 crewai-skills/deepagents 目标以 skill 目录为产物,scripts/ 随目录保留) | 手动把 skill 的 `scripts/` 拷到目标工程并在 README 标注调用方式;回程 `write_skill(..., copy_scripts_from=<原skill目录>)` 可恢复;或改用 crewai-skills/deepagents 目标 |
| 2 | 渐进式路由语义(SKILL.md 正文"何时读哪份 reference",按需加载) | 体现在 `system_prompt` 正文 | crewai:`backstory()` 截断到 1200 字符,长路由清单可能被裁;langflow:template 是单文本框,无文件按需加载;langchain/openai/generic:system_prompt 全文保留,但"按需加载"退化为"一次性注入 + 文件在旁边" | crewai 把完整路由写进 tasks.yaml `description`;langflow 把路由段粘进 template;其余框架确认 agent 运行时真能读到 `knowledge/` 目录 |
| 3 | frontmatter 额外键(license、allowed-tools 等) | 无 IR 字段 | `parse_frontmatter` 只取平面字符串;除 name/description 外全部丢弃 | 转换前手工把需要的键记入 `metadata` |
| 4 | `agents/*.yaml` 的 `interface.default_prompt` | `default_prompt` | 仅 openai_agents 与 generic 有落点;crewai/langchain/langflow 无对应槽位 | 用 generic 目标保底,或转后手工补 |
| 5 | `interface.short_description` | `metadata["short_description"]` | 仅 openai_agents 使用 | 同上 |
| 6 | reference 无 `#` 标题 | `KnowledgeDoc.title = ""` | 各框架路由清单缺标题列 | 源头补标题 |

## 6. roundtrip 保真要求

两级口径,验收 `python cli.py wiki verify` 亦可引用:

**一级:skill → IR → skill(`load_skill` → `write_skill`)——逐字段完全一致**

| 校验项 | 判定 |
|--------|------|
| `name` | 字符串相等 |
| `description` | 字符串相等 |
| `system_prompt` | 字符串相等(SKILL.md 正文原样进原样出) |
| `knowledge` | 列表逐项相等:每个 `KnowledgeDoc` 的 `filename` / `title` / `content` / `source_path` 四字段均字符串相等 |

允许的差异:产出目录多出的 `agents/openai.yaml`、可选 scripts 拷贝(不参与一致性判定)。

**二级:skill → agent → skill(经任一 emitter 再 parse 回来)——允许结构等价**

| 校验项 | 判定 |
|--------|------|
| `system_prompt` | 允许被重组(截断恢复、段落重排),但语义内容等价、无幻觉新增 |
| `name` | 允许经 `slugify` 规范化(大小写/分隔符变化);注意 `slugify` 幂等:`slugify(slugify(x)) == slugify(x)` |
| `knowledge` | `content` 一致;`filename`/`title` 允许规范化 |
| 结构 | 各框架只保各自字段(见 §3 总表),丢的字段以 generic/`agent.json` 为对账基准 |
