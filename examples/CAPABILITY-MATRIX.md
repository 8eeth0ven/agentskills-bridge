# 能力对照矩阵

skill 侧能力转换到 9 种 agent 形态后的保留情况逐项对照。每格都有可验证的证据(评测指标 / 案例 / 产物文件),不含臆断。矩阵先于文档存在——正是它暴露了「scripts/ 不迁移」的差距,已修复(见 scripts 行注)。

图例:✅ 完整保留 · ⚠️ 降级保留(形式在,语义需人工一步)· ❌ 不随迁移(IR 留名单,README 注明)

## skill → agent(正向)

| skill 侧能力 | crewai | crewai-skills | deepagents | langchain | langflow | openai | claude-subagent | autogen | generic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 触发元数据(name / description) | ✅ goal | ✅ frontmatter 原生 | ✅ frontmatter 原生 | ⚠️ 仅常量,宿主不自动触发 | ⚠️ flow description | ✅ openai.yaml | ✅ description 即触发键 | ⚠️ 仅常量 | ✅ IR 字段 |
| 主指令正文(system_prompt) | ✅ backstory 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ instructions.md 逐字 | ✅ 逐字 | ✅ 逐字 | ✅ 逐字 |
| 知识文档 references/ | ✅ knowledge/ + 任务路由 | ✅ 原生目录 | ✅ 原生目录 | ✅ knowledge/ + KNOWLEDGE 清单 | ⚠️ knowledge/ 拷贝,进 RAG 需按 KB API 上传 | ✅ knowledge/ | ✅ knowledge/ + frontmatter 清单 | ✅ knowledge/ | ✅ 内嵌 agent.json |
| 可执行脚本 scripts/ | ❌ | ✅ 原样拷贝 | ✅ 原样拷贝 | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ 路径名单在 IR |
| 工具契约(tools) | ⚠️ 名字进提示词,需代码注册 | ⚠️ 同左 | ⚠️ 同左 | ✅ @tool stub 生成 | ❌ | ❌ | ⚠️ frontmatter 工具白名单 | ✅ stub 生成 | ✅ 唯一保留 input_schema |
| 默认提示词 default_prompt | ⚠️ | ⚠️ | ⚠️ | ⚠️ 注释保留 | ⚠️ | ✅ interface 字段 | ⚠️ | ⚠️ | ✅ IR 字段 |
| 渐进披露(元数据→正文→按需读文档) | ✅ CrewAI 三级原生 | ✅ CrewAI 三级原生 | ✅ SkillsMiddleware 三级 | ⚠️ 无自动,SKILL 常量全量进上下文 | ❌ | ⚠️ | ❌ 全量正文 | ⚠️ | ⚠️ IR 平铺 |

证据:「主指令」行 = 评测 27 链 F_prompt = 1.0000(`python3 evaluation/run_eval.py`);「scripts/」行 = anthropics 官方 docx skill(59 个脚本文件)实测 crewai-skills / deepagents 迁移 59/59([SHOWCASE 案例 5](SHOWCASE.md#案例-5anthropics-官方-docx-skill--skill-目录形态scripts-完整迁移));「知识文档」行 = 案例 4 十二篇 sha256 全一致。

## agent → skill(反向)

| agent 侧能力 | crewai | crewai-skills | deepagents | langchain | langflow | openai | claude-subagent | autogen | generic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 角色定义(role/goal/backstory) | ✅ 三段还原 | ✅ 原生 | ✅ 原生 | ✅ 常量 | ✅ Prompt 组件 | ✅ openai.yaml | ✅ frontmatter | ✅ 构造参数 | ✅ IR |
| 多 agent / 多任务拓扑 | ⚠️ 取首 agent,其余记 metadata.agents_all | — | — | — | ⚠️ 记录链路 metadata.chain | — | — | — | ⚠️ tasks 保留 |
| 工具名清单 | ❌ | — | ⚠️ @tool 提取 | ✅ @tool/StructuredTool | ❌ | — | ✅ frontmatter tools(含行内逗号式) | ✅ | ✅ 含 schema |
| 知识目录回迁 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅(内嵌) |

证据:「多 agent」行 = crewAI-examples screenplay_writer 真实多 agent 项目实测([SHOWCASE 案例 2](SHOWCASE.md#案例-2第三方-crewai-项目--skill反向));「工具行内逗号式」= 真实 wshobson subagents 输入修复后的解析;「知识回迁」= 外部语料 11/11(`evaluation/external/`)。

## 差距与处理原则

- **skill 目录形态(crewai-skills / deepagents)是能力无损通道**:scripts、渐进披露、agentskills.io 合规全部原生保留 —— 脚本型技能(如 docx/pdf)优先选这两个 target;
- **scripts/ 在其余 7 个 target 不随迁移**是有意的:那些形态没有可执行脚本的挂载点(如 flow.json、subagent 定义);IR 保留 `scripts` 路径名单,`write_skill(copy_scripts_from=...)` 回程可恢复;
- **input_schema 仅 generic 完整保留**,其余 target 保留工具名与描述 —— 全链路 schema 往返在 Roadmap。
