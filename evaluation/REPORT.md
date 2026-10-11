# Skill ↔ Agent 双向转换评测报告(2 轮迭代累计)

**日期**:2026-10-11 · **工具**:agentskills-bridge @ 本仓库 · **复现**:`python3 evaluation/run_eval.py`(矩阵)/ `evaluation/runtime/`(运行时)/ `evaluation/external/`(外部语料)

## Abstract

对 8 个主流 agent 形态(CrewAI、CrewAI 原生 skills、deepagents、LangChain、Langflow、OpenAI/Codex、Claude subagent、generic IR)的 skill→agent→skill roundtrip 保真度做了系统评测。基线全局 F_prompt=0.9189、F_name=0.875;通过根因分析修复 6 类缺陷后,3 corpus × 8 target = 24 条链路的 6 项指标(F_name/F_desc/F_prompt/F_know_q/F_know_c/V_format)全部达到 1.0000。剩余风险与下一轮路线见 §5-§6。

## 1. Metrics & Setup

指标定义、corpus 构成与实验矩阵见 `llm-wiki/05-evaluation/roundtrip-fidelity.md`(与 `evaluation/metrics.py` 实现逐条对齐)。摘要:

| 指标 | 定义 | 粒度 |
|---|---|---|
| F_name | slugify 归一后 name 全等 | 1/0 |
| F_desc | description 归一化后全等=1,否则 1−lev/max_len | [0,1] |
| F_prompt | system_prompt 归一化后全等=1,否则 1−lev/max_len | [0,1] |
| F_know_q / F_know_c | knowledge 数量比 / sha256 内容一致率 | [0,1] |
| V_format | forward 产物静态格式校验通过率 | 1/0 |
| L | Loss points(丢失字段+原因) | 列表 |

Corpus:**S1_real**(上游仓库真实 skill,12 references,prompt 13,286 字符)、**S2_cn**(中文合成:多级列表/代码块/引号/emoji)、**S3_min**(仅 SKILL.md 极简)。

## 2. Results

### 2.1 迭代轨迹(全局均值)

| 迭代 | F_name | F_desc | F_prompt | F_know | V_format |
|---|---|---|---|---|---|
| 基线 | 0.8750 | 0.8610 | 0.9189 | 1.0000 | 1.0000 |
| 修复 R1-R3 | 1.0000 | 1.0000 | 0.9541 | 1.0000 | 1.0000 |
| 修复 R4-R6(终版) | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **1.0000** |

### 2.2 终版明细(3 corpus × 8 target 全 1.0,机器生成全文见 `results/results.md`)

| target | F_name | F_desc | F_prompt | F_know_q | F_know_c | V_format |
|---|---|---|---|---|---|---|
| crewai / crewai-skills / deepagents / langchain / langflow / openai / claude-subagent / generic | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

## 3. Failure Analysis(基线缺陷 → 根因 → 修复)

| # | 症状(基线) | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| R1 | crewai F_prompt=0.408 | emit 时 `backstory()` 按 1200 字符截断,而 backstory 是该链唯一 prompt 载体 | backstory 承载完整 system_prompt,截断仅保留给 UI 摘要场景 | 0.408→0.95+ |
| R2 | langchain F_name=0, F_desc=0.141 | parse 按文件名词干取名(`agent.py`→"agent"),desc 取 prompt 首句 | 生成的 agent.py 内嵌自描述常量 `AGENT_NAME`/`SKILL_DESCRIPTION`,parser 优先提取 | →1.0 |
| R3 | openai F_desc=0.747 | short_description(截 120 字)是 description 唯一回源 | openai.yaml 增加 `x-source-skill:` 扩展段(x- 命名空间,Codex 宽容忽略)携带全文 | →1.0 |
| R4 | crewai F_prompt 最低 0.356(S3_min) | ① YAML `>` 折叠标量破坏 markdown 换行(列表/代码块被并成空格);② parse 组装的 `## Role/Goal/Backstory` 包装头与正文自身标题层重复 | ① 改用 `\|` literal 标量;② parse 检测 backstory 以 `#` 开头(即本工具产物形态)时直接作为正文,不再包三段 | 0.356→1.0 |
| R5 | claude-subagent F_prompt 0.87-0.96 | emitter 把知识文件清单附加在 prompt 正文末尾,污染唯一载体 | 清单移入 frontmatter `knowledge:` 键(knowledge 内容仍由 knowledge/ 目录承载) | →1.0 |
| R6 | langchain S2_cn F_prompt=0.997 | emitter 按字面量规则转义(`\s`→`\\s`),parser 正则取"源码字面"未还原"运行时值" | parser 用 `ast.literal_eval` 按定界符完整还原字面量语义 | →1.0 |

**共性教训**:六类缺陷中五类(R1/R2/R3/R5/R6)源于同一设计反模式——**载体不自描述**:prompt/name/description 的唯一承载处被截断、替换或附加内容。修复策略统一为"生成物自描述 + 解析端字面量级还原"。

## 4. 测试与验证

- 单元/矩阵测试:`python3 -m unittest discover tests` → **64/64 通过**(含 8×2 全矩阵 forward/backward、roundtrip 保真、writer 规范校验、边界 sink、wiki 完整性)。
- 评测:`python3 evaluation/run_eval.py` → 24 链全 1.0,`results/results.{json,md}` 可复现。
- 完整性:llm-wiki 13 章,MANIFEST.sha256 重建 + `chmod -R a-w`,`wiki verify` 通过。

## 5. Threats to Validity

1. **字符级 ≠ 语义级**:F_prompt 用 levenshtein,不度量语义漂移;对"语义等价、字符不同"的合法变体(如人工改写)会低估。
2. **V_format 是静态校验**:未安装各框架做端到端运行(crewai load、deepagents run、Langflow UI 导入未经真实 UI 回放)。
3. **Corpus 同源风险**:corpus 由本工具生态生成/转换,字段形态与 emitter 输出同分布;真实第三方 skill(如 anthropics/skills 官方库、Codex community skills)可能暴露未见形态(frontmatter 扩展键、非 markdown 正文)。
4. **启发式自洽性**:R4 修复依赖"backstory 以 # 开头"启发式,对本工具产物自洽;对恰好以 # 开头的原生 crewai 人格化 backstory 可能误判(损失可控:正文仍完整保留)。
5. **单 skill 粒度**:multi-agent(multi-task/multi-crew)仅 tasks 级保留,未评测多 agent 拓扑的往返。

## 6. Round 2:运行时验证 + 外部真实语料(2026-10-11 第二轮)

第 1 轮 Threats #2(静态校验)与 #3(corpus 同源)在本轮正面解决,并新增第 9 格式 autogen。

### 6.1 运行时验证(skills→agent 真实框架加载/执行)

| 框架(真实版本) | 验证内容 | 结果 | 修复 |
|---|---|---|---|
| crewai 1.15.27 | YAML 语义等价;真实 `Agent/Task/Crew` 构造;**真实 `crewai.skills.load_skill` 加载我们的 skills/ 目录**(disclosure 分级识别);`Agent(skills=[...])` 构造期解析为 `crewai.skills.models.Skill` | 6/6 PASS | 零修复(产物原生兼容);实证:单技能目录引用会加载 0 技能,产物正确引用发现目录 |
| langchain 1.4.4 + core 1.6.9 | 生成 agent.py 真实导入;`GenericFakeChatModel` 跑完整一轮 `agent.invoke`;stub 工具直调 | PASS | **R7**:顶层 `init_chat_model` 导入即炸 → 改 `build_agent(model=None)` 工厂 + main 块(`create_agent(model, tools=, system_prompt=)` 签名实测兼容) |
| deepagents 0.7.23 | 真实 `create_deep_agent` 签名对照;`_list_skills`+FilesystemBackend 加载我们的 skills/;fake model 跑一轮且技能元数据注入 system prompt | PASS | **R8**:默认 StateBackend 下 `skills=["./skills"]` **不从磁盘加载**(隐蔽坑)→ 改 `FilesystemBackend(root_dir=AGENT_DIR)` + `skills=["skills"]` |

复现:`evaluation/runtime/test_{crewai,langchain}_runtime.py`(框架缺失自动 skip;venv 安装见脚本注释)。

### 6.2 外部真实语料泛化(第 1 轮 Threat #3 的正面测试)

14 份第三方输入(全部非本工具生成):crewAI-examples 4 个真实项目、langflow 官方 fixtures 4 个真实 flow(含 1 个无 Prompt 组件的 1.6.0 老格式)、anthropics/skills 3 个真实 skill(docx/pdf/pptx)、wshobson/agents 3 个真实 Claude subagent。

| 方向 | 结果 |
|---|---|
| agent→skill(真实输入 parse) | **11/11 成功**,write_skill+load_skill 回读 11/11 |
| skill→agent(anthropic 真实 skill × emitter) | V_format **24/24**;四链 F_name/F_desc/F_prompt **12/12 满分** |

修复 5 处真实兼容缺陷:**R9** crewai 真实模板路径 `src/<pkg>/config/` 探测;**R10** 多 agent 项目取首 agent 并 metadata 记录全部;**R11** langflow 无 Prompt 组件的 flow 从 Agent 组件 system_prompt/Note 兜底;**R12** subagent 行内 `tools: Read, Grep` 逗号格式解析(原为空);**R13** `>-` 折叠块脏前缀与 YAML 转义漂移(F_desc 0.9840→1.0)。

### 6.3 Schema 深度一致性(对官方真实结构逐字段 diff)

langflow/openai/claude-subagent 三格式**必需级差异全部归零**(`evaluation/schema_diff.py`,报告 `schema_diff_report.md`):langflow 补 `data.display_name`/`data.description`/`data.node.custom_fields`;claude-subagent name 空白规范化 + model 值域过滤;openai interface 三字段长度 clamp(64/1024)。x-source-skill 扩展经 Codex 源码证实宽容忽略。

### 6.4 autogen 第 9 格式

AG2 0.7.x `AssistantAgent(name=, system_message=, model_client=)` 形态;roundtrip 全 1.0;纳入评测矩阵后 **9 target × 3 corpus = 27 链全指标 1.0000**;测试 70/70 绿。

### 6.5 Round 2 后残余 Threats(下一轮)

1. langflow 仍未做真实 UI/服务端导入回放(重依赖,留 docker 方案);
2. autogen 产物未装真实 autogen-agentchat 跑 runtime(静态+AST+roundtrip 已过);
3. openai 产物未在真实 Codex CLI 会话加载;
4. 外部语料规模 14 份,可再扩(Codex community plugins、Gemini CLI skills);
5. tools 的 input_schema 仍未在全部链路往返。

## 6R. Round 3:真实 LLM 双协议端到端(2026-10-11 第三轮)

Round 2 残余 #2(autogen 真跑)在本轮解决,并把"真实模型调用"补进所有可执行链。**关键实测发现:GLM 提供两条协议路径且免费档模型不同** —— OpenAI 兼容 `/api/paas/v4`(免费档 glm-4-flash)与 **Anthropic 兼容 `/api/anthropic`(x-api-key + anthropic-version,免费档 glm-5.3-flash)**;同一把 key,glm-5.3-flash 必须走 Anthropic 路径(v4 路径报 1113)。已沉淀至 `llm-wiki/03-frameworks/llm-provider-config.md`。

### 真实调用矩阵(9 链全绿,统一问题"这个 skill 有哪几种 Response Modes",命中模式词=证明 system prompt/技能目录真实生效)

| 链 | 协议 × 模型 | 耗时 | 结果 |
|---|---|---|---|
| langchain | OpenAI × glm-4-flash | 3.9s | ✅ 4/4 模式词 |
| langchain | **Anthropic × glm-5.3-flash** | 8.9s | ✅ 4/4 |
| deepagents | OpenAI × glm-4-flash | 4.9s | ✅ 4/4(skills 目录注入生效) |
| deepagents | **Anthropic × glm-5.3-flash** | 9.2s | ✅ 4/4 |
| crewai | OpenAI × glm-4-flash | 4.7s | ✅ 4/4(backstory=SKILL.md 正文生效) |
| crewai | **Anthropic × glm-5.3-flash** | 9.3s | ✅ 4/4 |
| crewai-skills | OpenAI × glm-4-flash | 5.2s | ✅ skills 构造期加载+4/4 |
| autogen | OpenAI × glm-4-flash | 4.8s | ✅ 4/4 |
| autogen | **Anthropic × glm-5.3-flash** | 7.3s | ✅ 4/4 |

复现:在装有对应框架的 venv 中(参照 `evaluation/runtime/` 各测试文件 docstring 的依赖说明)执行 `python -m unittest evaluation.runtime.test_glm_e2e_langchain evaluation.runtime.test_glm_e2e_autogen evaluation.runtime.test_glm_e2e_crewai`;需先设置环境变量 `GLM_API_KEY` / `GLM_BASE_URL` / `GLM_MODEL` / `GLM_ANTHROPIC_BASE_URL` / `GLM_ANTHROPIC_MODEL`(未设置或依赖缺失自动 skip;密钥只经环境变量,不入仓库)。

### 本轮修复(只有真实调用才能暴露)

- **R14**(autogen emitter):产物 agent name 为 kebab-case,AG2 真跑抛 ValueError → `_runtime_name()` 运行期归一;
- **R15**(接线增强):langchain/deepagents/autogen/crewai 产物的 build_agent/README 补 GLM 双端点 + Claude base_url 接法,key 全走 env;autogen 产物 main 支持环境变量选协议;
- **R16**(供应商行为差异):GLM v4 兼容层在「system 为 content-blocks 数组且 ~15k 长文」时模型未收到完整 system 内容 → 测试侧 FlattenSystemBlocksChatOpenAI 拍平适配并记录;规避方案:system 拍平为纯字符串或改走 Anthropic 路径。

### Round 3 后残余 Threats(更新)

1. langflow 真实 UI 导入回放仍未做(需 docker 起服务);
2. openai/Codex 产物未在真实 Codex CLI 会话加载;
3. 真实调用覆盖 glm-4-flash / glm-5.3-flash 两档,旗舰档(glm-4.6/GLM-5.3)未测;
4. tools 端到端(stub 换真实工具后模型正确调用)未测——本轮仅验证 prompt/知识注入。

## 7. Next Iteration Roadmap(合并更新)

1. **端到端运行时验证**(优先):CI 中安装 crewai≥1.12 / deepagents / langflow,对产物做真实加载与一次执行,V_format 从静态升级为可执行门禁。
2. **外部真实 corpus**:批量拉取 anthropics/skills、openai plugins 市场的第三方 SKILL.md 做 A 类泛化评测,报告分布外的失败模式。
3. **语义级指标**:引入 embedding 相似度作为 F_prompt 的补充(报告双口径),避免对合法改写误判。
4. **多 agent 拓扑**:IR.tasks 已有承载,补 crewai 多 task/多 agent 的 emit+parse 闭环并纳入矩阵。
5. **工具契约往返**:当前 tools 仅保 name/description,input_schema 在多数链路未往返;扩展各载体(openai.yaml x-source-skill.tools、agent.py stub 参数)。
6. **Langflow 真实导入回放**:官方 docker 起服务,API 导入 flow.json + Knowledge 上传,验证 œ-handle 与组件链在真实前端的可渲染性。
