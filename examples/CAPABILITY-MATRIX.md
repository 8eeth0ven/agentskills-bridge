# 能力对照矩阵

> 本表记录原生格式投影能力。2026-10-29 新增的 Preservation Capsule 在全部 11 种格式上运输完整 IR 与源文件；这不改变目标框架自身的执行能力。完整资产恢复契约见 [INTERFACE.md](../INTERFACE.md)。

skill 侧能力转换到 11 种目标形态(9 种 agent 形态 + n8n / mermaid-workflow 两种 workflow 形态)后的保留情况逐项对照。本表说明目标原生格式的映射与接入要求，不代替目标运行时验证。语义级验证(结构 / 术语 / 行为三层)见 [semantic-equivalence](../llm-wiki/05-evaluation/semantic-equivalence.md)(L1/L2/L3)。

图例:✅ 完整保留 · ⚠️ 降级保留(形式在,语义需人工一步)· ❌ 不随迁移(IR 留名单,README 注明)

## 三形态说明

本矩阵覆盖三种一等形态,互转语义与 WorkflowIR 契约见 [three-forms](../llm-wiki/01-concepts/three-forms.md):

- **skill**:声明式知识包——触发元数据 + 正文 + 资源(references / scripts),自身不运行;
- **agent**:可执行运行时定义——单角色 prompt + tools;
- **workflow**:多步骤编排 DAG——节点 = 步骤 / 子 agent,边 = 依赖顺序。crewai(tasks.yaml 多任务)与 langflow(flow.json 节点图)本身就是 workflow 形态的成员;n8n 与 mermaid-workflow 为本轮新增的两个 workflow target,在下方正向矩阵中以独立两列呈现。

## skill → agent / workflow(正向)

| skill 侧能力 | crewai | crewai-skills | deepagents | langchain | langflow | openai | claude-subagent | autogen | generic | n8n | mermaid-workflow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 触发元数据(name / description) | ✅ goal | ✅ frontmatter 原生 | ✅ frontmatter 原生 | ⚠️ 仅常量,宿主不自动触发 | ⚠️ flow description | ✅ openai.yaml | ✅ description 即触发键 | ⚠️ 仅常量 | ✅ IR 字段 | ⚠️ workflow.name | ⚠️ workflow.name |
| 主指令正文(system_prompt) | ✅ backstory 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ instructions.md 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ options.systemMessage 分步 | ✅ Step 分节 |
| 知识文档 references/ | ✅ knowledge/ + 任务路由 | ✅ 原生目录 | ✅ 原生目录 | ✅ knowledge/ + KNOWLEDGE 清单 | ⚠️ knowledge/ 拷贝,进 RAG 需按 KB API 上传 | ✅ knowledge/ | ✅ knowledge/ + frontmatter 清单 | ✅ knowledge/ | ✅ 内嵌 agent.json | ✅ knowledge/ 同目录 | ✅ knowledge/ 同目录 |
| 可执行脚本 scripts/ | ❌ | ✅ 原样拷贝 | ✅ 原样拷贝 | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ 路径名单在 IR | ❌ | ⚠️ 同目录拷贝,图内无执行挂载点 |
| 工具契约(tools) | ⚠️ 名字进提示词,需代码注册 | ⚠️ 同左 | ⚠️ 同左 | ✅ @tool stub 生成 | ❌ | ❌ | ⚠️ frontmatter 工具白名单 | ✅ stub 生成 | ✅ 完整 IR schema | ❌(需人工补凭据节点) | ❌ |
| 默认提示词 default_prompt | ⚠️ | ⚠️ | ⚠️ | ⚠️ 注释保留 | ⚠️ | ✅ interface 字段 | ⚠️ | ⚠️ | ✅ IR 字段 | ❌ | ❌ |
| 渐进披露(元数据→正文→按需读文档) | ✅ CrewAI 三级原生 | ✅ CrewAI 三级原生 | ✅ SkillsMiddleware 三级 | ⚠️ 无自动,SKILL 常量全量进上下文 | ❌ | ⚠️ | ❌ 全量正文 | ⚠️ | ⚠️ IR 平铺 | ⚠️ | ⚠️ |

原生文件布局可结合 [SHOWCASE](SHOWCASE.md) 中的转换案例阅读。脚本型技能可优先使用 crewai-skills / deepagents 的原生技能目录；其他目标的原始文件仍由 capsule 保存。

## agent → skill(反向)

| agent 侧能力 | crewai | crewai-skills | deepagents | langchain | langflow | openai | claude-subagent | autogen | generic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 角色定义(role/goal/backstory) | ✅ 三段还原 | ✅ 原生 | ✅ 原生 | ✅ 常量 | ✅ Prompt 组件 | ✅ openai.yaml | ✅ frontmatter | ✅ 构造参数 | ✅ IR |
| 多 agent / 多任务拓扑 | ⚠️ 取首 agent,其余记 metadata.agents_all | — | — | — | ⚠️ 记录链路 metadata.chain | — | — | — | ⚠️ tasks 保留 |
| 工具名清单 | ❌ | — | ⚠️ @tool 提取 | ✅ @tool/StructuredTool | ❌ | — | ✅ frontmatter tools(含行内逗号式) | ✅ | ✅ 含 schema |
| 知识目录回迁 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅(内嵌) |

第三方原生工程的解析范围取决于各 parser 可识别的静态字段；没有 capsule 的输入不能恢复原格式中不存在的信息。

## 差距与处理原则

- **skill 目录形态(crewai-skills / deepagents)** 原生提供脚本和参考资源位置；实际执行仍受目标运行时和依赖配置影响；
- **其他目标不自动执行 scripts/**：完整普通文件随 capsule 运输，但 flow.json、subagent 定义等格式没有相同的脚本执行挂载点；
- **input_schema 往返**:langchain / autogen / deepagents(继承 langchain)三链已支持字典级往返 + side_effects 回读(2026-10-11 补);generic 直接序列化完整 IR；其他原生格式按其可表达字段映射，capsule 独立保存完整契约；
- **n8n 的 tools / 凭据节点不自动生成**:工具契约留在 IR,AI Agent 节点的 tool 子节点与凭据需人工在 n8n 界面补挂;mermaid-workflow 为纯文本格式,无工具挂载点。
