# agent → skill 反向转换规则

本章定义 crewai / crewai-skills / deepagents / langchain / langflow / openai / claude-subagent / generic / autogen 九种 agent 工程反向组装为 skill 目录的规则——与正向章节(`/llm-wiki/04-conversion/skill-to-agent.md`)的 9 个 emit target 一一对应,共用同一份 AgentIR(`converter/ir.py`,字段名严格一致)。

- 入口:`converter/parsers/*.py`(既有四个:`parse_crewai` / `parse_langchain` / `parse_langflow` 均为 best-effort,generic 直接 `AgentIR.from_json`;2026-10 扩 crewai-skills / deepagents / openai / claude-subagent 四入口,见 §1.5–§1.8;第 9 入口 autogen:`parse_autogen` 读 agent.py 的 AGENT_NAME/SKILL_DESCRIPTION/SYSTEM_MESSAGE 自描述常量,回退 AssistantAgent/ConversableAgent 构造参数)
- 出口:`converter/skill_writer.py` 的 `write_skill(ir, out_dir, copy_scripts_from=None) -> Path`
- CLI:`python cli.py agent2skill <path> --from crewai|crewai-skills|deepagents|langchain|langflow|openai|claude-subagent|generic|autogen --out <dir>`(`--from` 名对应 §1 的九个解析入口;`openai` 入口按 §1.7 读 `instructions.md` + `agents/openai.yaml`,与 `load_skill` 直读 skill 目录的路径并存)

```
crewai(config/agents.yaml + tasks.yaml)    ─┐
crewai-skills(skills/*/SKILL.md)            │
deepagents(skills/ 优先,agent.py 回退)    │
langchain(agent.py)                         ├─▶ parsers ─▶ AgentIR ─▶ write_skill ─▶ SkillDir
langflow(flow.json)                         │              (metadata.source_format 标来源)
openai(instructions.md + openai.yaml)       │
claude-subagent(.claude/agents/*.md)        │
generic(agent.json = ir.to_json())         ─┘
```

## 1. 各框架解析入口

| 框架 | 函数签名 | 输入文件 | 提取物 |
|------|----------|----------|--------|
| crewai | `parse_crewai(config_dir: str \| Path) -> AgentIR` | `config/agents.yaml` + `config/tasks.yaml` | role/goal/backstory/verbose + 任务 description/expected_output/agent |
| crewai-skills | `parse_crewai_skills(root: str \| Path) -> AgentIR` | 产物根目录 `skills/*/SKILL.md` | frontmatter(name/description)+ 正文(system_prompt)原样读回 |
| deepagents | `parse_deepagents(root: str \| Path) -> AgentIR` | 产物根目录:`skills/` 优先,`agent.py` 回退 | skills/ 命中时同 crewai-skills;回退按 §1.2 从 agent.py 提取 |
| langchain | `parse_langchain(py_file: str \| Path) -> AgentIR` | 单个 `agent.py`(.py) | system prompt 字符串、`@tool` 函数 → tools |
| langflow | `parse_langflow(flow_file: str \| Path) -> AgentIR` | `flow.json` | SystemPrompt 组件的 `data.template` |
| openai | `parse_openai(root: str \| Path) -> AgentIR` | 产物根目录 `instructions.md` + `agents/openai.yaml`(同根 `knowledge/` 一并读回) | instructions.md → system_prompt;interface 三字段 → display_name / short_description / default_prompt |
| claude-subagent | `parse_claude_subagent(root: str \| Path) -> AgentIR` | 产物根目录 `.claude/agents/*.md` | frontmatter name/description(+ 可选 tools)+ 正文 → system_prompt |
| generic | 无独立 parser,直接 `AgentIR.from_json(text)` | `agent.json` | 全字段零损(与 `to_json` 互逆) |

通用约定:

- YAML 解析:优先 `import yaml`(环境有),失败退回 `ir.py` 提供的工具或模块内最小平面解析。
- 解析出的 AgentIR 一律带 `metadata = {"source_format": ...}`,取值必须落在 `ir.py` 的 `SOURCE_FORMATS`(`"skill"/"crewai"/"langchain"/"langflow"/"generic"`)内;新增四入口取最近似既有值(crewai-skills→`crewai`、deepagents→`langchain`、openai/claude-subagent 产物与 SKILL.md 同构→`skill`),原始 target 名另记 `metadata` 备查。
- 全部 best-effort:字段缺失给默认值(空串/空列表),不抛噪音。

### 1.1 crewai:`config/agents.yaml` + `config/tasks.yaml`

| agents.yaml 键 | AgentIR 字段 | 规则 |
|----------------|--------------|------|
| `name` | `name` | 经 `slugify()` 规范化成 kebab-case(原值可留 `metadata`) |
| `role` | `display_name` | 人类可读名 |
| `goal` | `description` | "何时用/目标"语义对齐 skill frontmatter description |
| `backstory` | 参与 `system_prompt` 组装 | 见 §2.1 三段式 |
| `verbose` | 丢弃 | 无 IR 对应(固定 false 的展示开关,无语义) |

tasks.yaml:每条任务 → 一个 `TaskStep`(`name` / `description` / `expected_output` / `agent`),整体写入 `tasks: list[TaskStep]`,供组装 SKILL.md 的 Reference Routing 段(§2.3)。

### 1.2 langchain:`.py` 正则/AST 提取(best-effort)

| 目标 | 提取方式 |
|------|----------|
| system prompt | 正则优先:匹配 `SystemMessage(content=...)`、`SystemMessagePromptTemplate.from_template(...)`、`PromptTemplate.from_template(...)` 等形式中的字符串字面量(含三引号);正则失手再用 AST 找模块级/调用参数里的字符串常量 |
| tools | `@tool` 装饰函数 → `ToolSpec(name=函数名, description=docstring 首段, input_schema=从类型注解 best-effort 推导的 JSON Schema, side_effects=False)` |
| `name` | `slugify(py 文件名 stem)` |
| `display_name` | 注释/变量名里的 agent 名,无则留空由 `title()` 兜底 |

已知盲区:变量插值、条件拼接、外部模板文件加载的 prompt 提取不完整——这是 best-effort 的边界,必须人工复核(见 §3.2)。

### 1.3 langflow:`flow.json` 找 SystemPrompt 组件

| 要素 | 规则 |
|------|------|
| 定位 | 遍历 `data.nodes[]`,取 `type` 为 SystemPrompt/Prompt 的节点(多 agent flow 只取第一个,AgentIR 是单 agent 模型) |
| 取值 | `node["data"]["template"]`(需兼容 str 与 `{"template": "..."}` 两种形态,best-effort)→ `system_prompt` |
| `name` | `slugify(flow 文件名 stem)` |
| 丢弃 | 节点 `position`、`edges` 拓扑、`viewport`——编排信息不进 IR |

### 1.4 generic:`agent.json`

`AgentIR.from_json(text)` 直接反序列化(`from_dict` 逐字段恢复:`name/display_name/description/system_prompt/default_prompt/tools/knowledge/tasks/scripts/metadata`),`knowledge` 每项按 `filename/title/content/source_path` 恢复为 `KnowledgeDoc`。零损,不需要独立 parser。

### 1.5 crewai-skills:`skills/*/SKILL.md` 原生保真

正向产物本身就是 skill 目录(见正向章节 §3.6),反向直接按 skill 形态读回:扫描 `skills/*/SKILL.md`,frontmatter `name`/`description` 与正文 `system_prompt` 逐字段原样,`references/`、`scripts/` 从 skill 目录结构恢复,不走三段式重组。有损点:agents.yaml 片段中 agent 侧的 `skills` 挂载写法(目录引用 vs 精准挂载)与 `compatibility` pin 不进 IR,回程由 emitter 按默认规则重新生成;`scripts/` 本体仍需 `write_skill(..., copy_scripts_from=...)` 才回拷。

### 1.6 deepagents:`skills/` 优先,`agent.py` 回退

先扫产物根目录 `skills/*/SKILL.md`——deepagents 运行时的真身就是 SKILL.md,命中即按 §1.5 原生读回。无 `skills/`(或为空)时回退解析 `agent.py`:提取 `create_deep_agent(...)` 调用周边的 system prompt 字符串与 `@tool` 函数,规则同 §1.2。有损点:回退路径继承 langchain 式 best-effort 盲区(变量插值/外部模板提取不完整);`skills=` 挂载参数、`metadata.include_tools` 等运行时配置只能存档进 `metadata`。

### 1.7 openai:`instructions.md` + `agents/openai.yaml`

`instructions.md` 全文 → `system_prompt`(正向即全文不截断,回读无损);`agents/openai.yaml` 的 `interface` 三字段 → `display_name` / `metadata["short_description"]` / `default_prompt`;同根 `knowledge/*.md` 整文件读回。有损点:openai.yaml 中三字段之外的可选扩展键(policy/dependencies 等)不进 IR;`short_description` 与 `default_prompt` 再转回非 openai/generic 目标时无槽位(同正向 §5 有损点)。

### 1.8 claude-subagent:`.claude/agents/*.md`

Markdown + YAML frontmatter、正文即 system prompt,与 SKILL.md 同构:frontmatter 必需键 `name`/`description` → IR 同名字段,正文全文 → `system_prompt`,可选 `tools`(逗号分隔或 YAML 列表)→ 工具名单。有损点:`tools` 只剩名字,`ToolSpec` 的 schema/side_effects 不可恢复;`model`/`maxTurns`/`disallowedTools` 等 camelCase 运行时字段无 IR 槽位(存档进 `metadata` 或丢弃);`---` 不在文件第一行则整个文件被当正文——与 Claude Code 加载规则一致。

## 2. 组装 SKILL.md 的规则(write_skill)

产物结构(已存在则覆盖文件):

```
out_dir/
 ├── SKILL.md              frontmatter(name/description)+ system_prompt 正文
 ├── agents/openai.yaml    interface: display_name / short_description / default_prompt
 ├── references/*.md       每个 KnowledgeDoc 一个文件
 └── (可选)scripts/        仅当 copy_scripts_from 指向原 skill 目录时拷贝
```

### 2.1 system_prompt 组装格式(role/goal/backstory → 三段式)

对 crewai 源,`system_prompt` 按固定格式组装(与 `INTERFACE.md` 逐字一致,保证再正向转 crewai 时三段可拆回):

```
# {display_name}\n\n## Role\n{role}\n\n## Goal\n{goal}\n\n## Backstory\n{backstory}
```

| 段 | 来源 |
|----|------|
| `# {display_name}` | `ir.title()`(display_name 优先,缺失由 name 派生) |
| `## Role` | agents.yaml `role`(= IR `display_name`) |
| `## Goal` | agents.yaml `goal`(= IR `description`) |
| `## Backstory` | agents.yaml `backstory` |

langchain / langflow 源只有单块 prompt:已符合三段式结构则原样作为 `system_prompt`;否则整块作为正文(不强行套段落)。

### 2.2 frontmatter 自动生成

SKILL.md frontmatter 只写平面字符串键(`name`、`description`)——与 `parse_frontmatter` 只解析平面 `key: value` 的能力严格对齐,禁止嵌套/列表。

| 键 | 生成规则 |
|----|----------|
| `name` | `slugify(原 agent 名/role/display_name, fallback="agent")`:非字母数字连续段 → `-`,strip 首尾 `-`,小写。注意:纯中文名会被整体替换为 `-` 再 strip 成空串,触发 fallback `"agent"`——需人工改名 |
| `description` | 优先 `goal`(crewai);无 goal 用 `system_prompt` 首句/首行;压成单行,YAML 值正确引号 |

### 2.3 tasks → Reference Routing 段

`ir.tasks` 非空时(典型:crewai tasks.yaml),SKILL.md 正文自动追加 `## Reference Routing` 小节:每个 `TaskStep` 渲染为一项,呈现"何时做什么(name + description)→ 期望产出(expected_output)→ 对应 references 文件"的路由语义,把 agent 的任务编排翻译成 skill 的渐进式加载指引。`TaskStep.agent` 仅 multi-agent 时有意义,单 agent 留空不渲染。

### 2.4 knowledge → references/

每个 `KnowledgeDoc` 写成 `references/{filename}`:`content` 原样落盘;若 `title` 非空且 content 首行不是 `#` 标题,则补一行 `# {title}` 作为首标题(保证正向 `load_skill` 读回时 `title` 稳定)。

### 2.5 agents/openai.yaml

| interface 键 | 来源 |
|---------------|------|
| `display_name` | `ir.title()` |
| `short_description` | `metadata["short_description"]`,缺省用 `description` |
| `default_prompt` | `ir.default_prompt`(可为空) |

## 3. 有损点与最佳实践

### 3.1 有损点(agent 侧 → skill 侧)

| # | agent 侧特性 | 去向 | 说明 |
|---|--------------|------|------|
| 1 | 运行时配置(memory 开关、llm 型号、max_iter、temperature 等) | `metadata`(如 `metadata["llm"]`、`metadata["memory"]`) | IR 无一等字段;skill 是提示词工程载体,运行时配置只能存档备查,不参与行为 |
| 2 | crewai `verbose`/`process` 等编排开关 | 丢弃 | 无语义价值 |
| 3 | langflow 节点拓扑 / 多 agent 编排(edges、多 Prompt 链) | 不进 IR | AgentIR 是单 agent 模型;多 agent flow 只解析第一个 SystemPrompt,编排结构丢失 |
| 4 | `@tool` 复杂闭包、动态 schema、运行时副作用 | `ToolSpec` best-effort | `input_schema` 从注解推导,`side_effects` 默认 False,运行时行为不可还原 |
| 5 | scripts | 无法恢复 | agent 工程没有 scripts 概念;仅当 `write_skill(..., copy_scripts_from=<原 skill 目录>)` 才回拷 |
| 6 | langchain 变量插值/外部模板 prompt | 提取不完整 | best-effort 边界(§1.2) |

### 3.2 最佳实践

1. parse 后先 `ir.to_json()` 打印,人工核对 `name` / `display_name` / `system_prompt` 三字段再落盘——langchain 尤其要确认 prompt 提取完整。
2. 三段式组装必须逐字用 §2.1 格式,保证 agent→skill→agent 往返时 Role/Goal/Backstory 可再拆分。
3. frontmatter 只写平面键值,值含冒号/引号时按 YAML 规则加引号。
4. `metadata["source_format"]` 必须取 `SOURCE_FORMATS`(`"skill"/"crewai"/"langchain"/"langflow"/"generic"`)内的值,roundtrip 对账靠它。
5. 中文名 agent 转 skill 后立刻检查 `name` 是否退化为 fallback `"agent"`,手工改成有意义的 kebab-case id。
6. roundtrip 口径:agent→skill→agent 允许**结构等价**(system_prompt 重组、name 经 `slugify` 规范化、knowledge 文件名规范化),不要求逐字节一致;`slugify` 幂等(`slugify(slugify(x)) == slugify(x)`),二次往返后 name 稳定。
