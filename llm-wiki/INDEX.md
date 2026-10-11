# llm-wiki 总目录

agentskills-bridge 项目的只读知识库:skill / agent / workflow 三形态互转的概念、格式、框架与流程参考。

**本 wiki 只读,由 `MANIFEST.sha256` 保护**——每个文件的 SHA-256 记录在清单中,`python cli.py wiki verify` 会校验。任何章节的修改都必须同步重新生成清单,否则 verify 失败。不要直接编辑已落盘的章节文件。

阅读方式:`python cli.py wiki list` 列章节,`python cli.py wiki read <chapter>` 读正文。

## 01-concepts —— 核心概念

- [skill-vs-agent](01-concepts/skill-vs-agent.md) —— skill 与 agent 的定义、本质区别(声明式知识包 vs 可执行运行时)、字段三列映射表、选型判断。
- [intermediate-representation](01-concepts/intermediate-representation.md) —— AgentIR 规范:逐字段说明(与 `converter/ir.py` 严格一致)、序列化格式与完整 JSON 示例。
- [three-forms](01-concepts/three-forms.md) —— 三种形态(Skill / Agent / Workflow)概念、3×3 互转表、WorkflowIR 契约(与 `converter/wir.py` 严格一致)与 workflow 格式族(n8n / mermaid-workflow 新增)。

## 02-skill-format —— skill 目录格式

- [skill-md](02-skill-format/skill-md.md) —— SKILL.md 规范:frontmatter 权威字段表(agentskills.io,6 字段)、正文章节骨架、references 渐进披露路由写法。
- [openai-interface-yaml](02-skill-format/openai-interface-yaml.md) —— `agents/openai.yaml` 规范:interface 三字段(display_name / short_description / default_prompt)及与 AgentIR 的对应。

## 03-frameworks —— 目标框架格式

- [crewai](03-frameworks/crewai.md) —— CrewAI `config/agents.yaml` + `config/tasks.yaml` + `knowledge/` 的目录格式与 emit/parse 规则,含 v1.12.0+ 原生 Agent Skills(`skills/` 目录 + skills 字段)。
- [langchain](03-frameworks/langchain.md) —— langchain 目标的 `agent.py` + `requirements.txt` 生成格式与 parser 提取规则;含 deepagents 官方 skills 运行时与 langgraph.json 部署清单说明。
- [langflow](03-frameworks/langflow.md) —— `flow.json` 包导出结构:节点/edges/handle(œ 转义)与 Prompt 组件的嵌入方式;含 1.12 Knowledge 上传 API。
- [openai-agents](03-frameworks/openai-agents.md) —— openai 目标的 `agents/openai.yaml` + `instructions.md` + `knowledge/` 布局;OpenAI 已采纳 agentskills.io 开放规范,含 Codex skills 目录约定。
- [autogen](03-frameworks/autogen.md) —— AutoGen(AG2):第 9 个正式 target,`AssistantAgent` 形态 agent.py 的 emit/parse 规则与新旧 API 对照。
- [llm-provider-config](03-frameworks/llm-provider-config.md) —— GLM/OpenAI/Claude 三协议对照与转换产物接 GLM/Claude 的 base_url 接法。

n8n 与 mermaid-workflow 两个 workflow target 的格式说明并入 [three-forms](01-concepts/three-forms.md) 的「workflow 格式族」一节——workflow 格式族先记于该章,后续独立成章。

## 04-conversion —— 转换流程

- [skill-to-agent](04-conversion/skill-to-agent.md) —— skill → AgentIR → 各框架的完整管线:skill_loader 字段来源、8 个 target 的 emitter 产物清单、CLI 用法。
- [agent-to-skill](04-conversion/agent-to-skill.md) —— 各框架 → AgentIR → skill 的反向管线:八入口(crewai/crewai-skills/deepagents/langchain/langflow/openai/claude-subagent/generic)parsers 的 best-effort 提取规则、skill_writer 产物与覆盖行为。

## 05-evaluation —— 转换质量评测

- [roundtrip-fidelity](05-evaluation/roundtrip-fidelity.md) —— 转换质量评测体系:7 个指标(F_name/F_desc/F_prompt/F_know_q/F_know_c/V_format/L)定义、三语料测试集、3 corpus × 8 target 实验矩阵与复现命令。

## 章节编写约定

- 每章一个 markdown 文件,以 `# 标题` 开头,UTF-8,中文为主、代码与字段名保留英文。
- 涉及代码契约(字段名、类型、签名)的章节必须与 `converter/ir.py`、`INTERFACE.md` 同步:修改任一侧必须同步另一侧。
- 不写营销话术,只写可执行的规格与判断规则。
