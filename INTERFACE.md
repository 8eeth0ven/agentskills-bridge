# 转换引擎接口契约(subagent 必读)

项目:agentskills-bridge —— skill ↔ agent 双向转换器 + 只读 llm-wiki。

## 数据流

```
skill(SkillDir) ──skill_loader──▶ AgentIR ──emitters──▶ crewai / langchain / langflow / openai / generic
crewai / langchain / langflow ──parsers──▶ AgentIR ──skill_writer──▶ skill(SkillDir)
```

## AgentIR(converter/ir.py,已定稿,不得修改)

字段:`name`(kebab-case)、`display_name`、`description`(何时用)、`system_prompt`(主指令)、`default_prompt`、`tools: list[ToolSpec]`、`knowledge: list[KnowledgeDoc]`(filename/title/content/source_path)、`tasks: list[TaskStep]`、`scripts: list[str]`、`metadata: dict`。

辅助方法:`title()`、`backstory(max_chars)`(system_prompt 精简)、`slugify(text)`、`parse_frontmatter(text)->(meta, body)`。

## 模块接口(必须严格一致)

### converter/skill_loader.py
```python
def load_skill(skill_dir: str | Path) -> AgentIR
```
读取 `<skill_dir>/SKILL.md`(frontmatter → name/description,正文 → system_prompt)、`agents/*.yaml`(interface.display_name/short_description/default_prompt,容忍缺失)、`references/*.md` → KnowledgeDoc(filename/title=首个 `#` 标题/content/source_path)、`scripts/*` → scripts 列表。metadata: `{"source_format": "skill", "source_path": <abs>, "short_description": ...}`。

### converter/skill_writer.py
```python
def write_skill(ir: AgentIR, out_dir: str | Path, copy_scripts_from: str | Path | None = None) -> Path
```
产出完整 skill 目录:`SKILL.md`(frontmatter name/description + system_prompt 正文)、`agents/openai.yaml`(interface: display_name/short_description/default_prompt)、`references/*.md`(每个 KnowledgeDoc 一个文件)、可选拷贝 scripts。返回 out_dir。已存在则覆盖文件。

### converter/emitters/*.py(每个模块一个函数)
```python
def emit_<fmt>(ir: AgentIR, out_dir: str | Path) -> Path   # fmt ∈ crewai/langchain/langflow/openai_agents/generic
```
- `crewai`: `config/agents.yaml`(name/role/goal/backstory/verbose:false)+ `config/tasks.yaml`(单任务 description/expected_output/agent)+ `knowledge/*.md`(knowledge 拷贝)+ `README.md`(如何 crewai run)。YAML 手写生成(不依赖 pyyaml),值需正确引号/缩进。
- `langchain`: `agent.py`(可运行:SystemMessagePromptTemplate + tools stub + create_agent/或通用 create_react_agent 形式,内嵌 system_prompt 与知识清单注释)+ `requirements.txt` + `README.md`。纯文本生成,不需要真跑 langchain。
- `langflow`: `flow.json` —— 合法 Langflow 包导出格式:`{"id":..., "data": {"nodes": [...], "edges": [...], "viewport": {...}}}`。节点含 ChatInput→Prompt(SystemPrompt 组件,template 里嵌 system_prompt)→OpenAIAgent/LLM→ChatOutput,edges 带源/目标 handle;每个节点需 id/type/position/data.template。知识文件作为同目录 `knowledge/` 拷贝 + README 说明导入方式。
- `openai_agents`: `agents/openai.yaml`(interface: display_name/short_description/default_prompt)+ `instructions.md`(完整 system_prompt)+ `knowledge/*.md` + `README.md`(Codex/ChatGPT UI 用法)。与原仓库格式对齐。
- `generic`: `agent.json`(ir.to_json())+ `knowledge/*.md` + `README.md`。

### converter/parsers/*.py(每个模块一个函数,best-effort)
```python
def parse_crewai(config_dir: str | Path) -> AgentIR          # 读 config/agents.yaml + tasks.yaml
def parse_langchain(py_file: str | Path) -> AgentIR          # 从 .py 提取 prompt/tools(正则/AST,best-effort)
def parse_langflow(flow_file: str | Path) -> AgentIR         # 从 flow.json 提取 SystemPrompt 组件
```
YAML 解析:优先 `import yaml`(环境有),失败则用 ir.py 提供的工具/自行写最小平面解析。解析出的 AgentIR:`metadata={"source_format": "crewai"/...}`。role/goal/backstory 组装成 system_prompt 格式:`# {display_name}\n\n## Role\n...\n## Goal\n...\n## Backstory\n...`。

### CLI 约定(cli.py,主线程负责)
```
python cli.py skill2agent <skill_dir> --target crewai|langchain|langflow|openai|generic --out <dir>
python cli.py agent2skill <path> --from crewai|langchain|langflow|generic --out <dir>
python cli.py wiki list|read <chapter>|verify
python cli.py convert ir <in> ...   # 可选
```
target 名 `openai` → emitters.openai_agents;`--from` 名对应 parsers。

## 通用要求

- Python ≥3.10,零强制第三方依赖(pyyaml 可用时优先用,不可用时走内置路径)。
- 所有文件 UTF-8,函数带 docstring,不 print 噪音(返回值说话)。
- 不得修改 converter/ir.py、llm-wiki/、cli.py(主线程所有)。
- 子模块内部可自由加 helper,但上述公开函数签名不可变。
