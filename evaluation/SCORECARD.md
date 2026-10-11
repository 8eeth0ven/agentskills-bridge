# 转换实例与评分总表(2026-10-11)

agentskills-bridge 覆盖 **skill(声明式知识包)/ agent(可执行运行时定义)/ workflow(多步骤编排 DAG)三形态互转**,正向目标共 11 个:9 种 agent 格式(crewai、crewai-skills、deepagents、langchain、langflow、openai、claude-subagent、autogen、generic)+ 2 种 workflow 格式(n8n、mermaid-workflow)。截至 2026-10-11,3 语料 × 11 目标 = **33 条 roundtrip 链路的全部 8 项指标(F_name / F_desc / F_prompt / F_know_q / F_know_c / S_struct / S_terms / V_format)均为 1.0000,Loss 点 0 条**(数据源:`evaluation/results/results.md`);在此之上叠了三层活性验证:L3 行为等价一致率 100%、真实框架运行时 3 家 PASS(crewai 1.15.27 / langchain 1.4.4 / deepagents 0.7.23)、GLM 双协议真实模型端到端 9 链全绿,外部 14 份第三方真实语料 agent→skill 11/11、skill→agent 24/24——静态 → 语义 → 行为 → 运行时四层闭环。历史缺陷修复 R1–R16、语义审计 P1–P2 全记录见 `evaluation/REPORT.md`。

## 1. 实例总表(11 格式 × 每格式 3 语料链,共 33 链)

每行 F 五指标为该 target roundtrip 有效行均值(n=3);V_format 为 forward 3 行均值;S_struct / S_terms 为全语料语义指标。实例来源为 [SHOWCASE](../examples/SHOWCASE.md) 案例号或评测语料。

| 格式 | 实例来源 | 输入→输出(一句话) | F_name | F_desc | F_prompt | F_know_q | F_know_c | S_struct | S_terms | V_format | 反向入口 | 关联验证 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| crewai | 案例 2(反向真实项目)、8、10;语料 S1/S2/S3 | SKILL.md 正文逐字进 `config/agents.yaml` 的 backstory(`\|` literal 标量),knowledge/ 原样迁移;反向读真实项目(取首 agent,`metadata.agents_all` 记全部) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from crewai` | 运行时 **6/6 PASS**(crewai 1.15.27,真实 `load_skill`);GLM e2e 4/4 模式词 ×2 协议(4.7s / 9.3s);L3 A-B 一致率 100% |
| crewai-skills | 案例 1、5;语料 S1/S2/S3 | skill 目录整体迁入 `skills/<name>/`(SKILL.md + references + scripts 原样),agents.yaml 挂 `skills:` 字段 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from crewai-skills` | GLM e2e 4/4(5.2s,skills 构造期加载);案例 5 docx scripts 迁移 **59/59** |
| deepagents | 案例 5;语料 S1/S2/S3 | skill 目录原样迁入 `skills/` + AGENT.md 主文件;`FilesystemBackend` 从磁盘真实加载 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from deepagents` | 运行时 PASS(deepagents 0.7.23);GLM e2e 4/4 ×2 协议(4.9s / 9.2s);案例 5 59/59 |
| langchain | 案例 8、10;语料 S1/S2/S3 | 生成 `agent.py`:SYSTEM_PROMPT / AGENT_NAME / SKILL_DESCRIPTION 内嵌常量 + `@tool` stub,parser 以 `ast.literal_eval` 字面量级还原 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from langchain` | 运行时 PASS(langchain 1.4.4 + core 1.6.9,`GenericFakeChatModel` 跑通 invoke);GLM e2e 4/4 ×2 协议(3.9s / 8.9s);案例 10 n8n 产物直转后 9 步编号清单完整保留 |
| langflow | 案例 3、4、7、8;语料 S1/S2/S3 | 生成 `flow.json` 节点图(system_prompt 进 Prompt 组件);反向兼容无 Prompt 组件的 1.6.0 老 flow(Agent 组件兜底) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from langflow` | 外部 4 个官方真实 flow 全解析(含 11 节点 / 10 边的 research_agent);schema diff 必需级差异归零;案例 8 中文 SKILL.md 往返 `diff` 无输出(逐字节一致) |
| openai | 案例 8;语料 S1/S2/S3 | 生成 `openai.yaml` + instructions.md,`x-source-skill:` 扩展段(x- 命名空间)携带 description 全文回源 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from openai` | x-source-skill 经 Codex 源码证实宽容忽略;schema diff interface 三字段长度 clamp(64/1024)后必需级归零;外部语料 V_format 24/24 之列 |
| claude-subagent | 案例 5、6;语料 S1/S2/S3 | 生成 `.claude/agents/<name>.md`,description 即触发键,知识清单进 frontmatter `knowledge:` 键(不污染正文) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from claude-subagent` | 外部 3 个 wshobson 真实 subagent 解析 ok(prompt 最长 17879 字);schema diff 必需级差异归零;R12 行内 `tools: Read, Grep` 逗号式 + R13 `>-` 折叠块脏前缀均已修 |
| autogen | 案例 8;语料 S1/S2/S3 | 生成 AG2 `agent.py`(`AssistantAgent(name=, system_message=, model_client=)` 形态),`_runtime_name()` 运行期名称归一 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from autogen` | GLM e2e 4/4 ×2 协议(4.8s / 7.3s,AG2 真跑暴露 R14 并已修);与 AG2 0.7.x 真实签名对照 |
| generic | 案例 10;语料 S1/S2/S3 | 生成 `agent.json`(IR 枢纽:全字段内嵌,references 全文,input_schema 完整保留) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from generic` | 外部语料四链之一 generic→generic F 三项满分(12/12 之列);分支 DAG 经其 `metadata.graph_edges` 中转往返仍保分支(案例 10) |
| n8n | 案例 9、10;语料 S1/S2/S3 | 正文 9 步语义提取为 9 个 AI Agent 节点(`options.systemMessage` = 步骤指令)按序成链,`x-source-skill` 携带原文全文 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from n8n` | L3 A-C 一致率 100%(C 形态即 n8n 产物 systemPrompt);分支 DAG 往返保分支(P2 修复实测);案例 9 九节点成链 |
| mermaid-workflow | 案例 9;语料 S1/S2/S3 | 生成 `workflow.md`:GitHub 原生渲染 flowchart(实际 9 节点 8 边)+ 每步一节 `## Step N: <name>` 放该步指令 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `agent2skill --from mermaid-workflow` | 案例 9 反向读回 roundtrip 六项指标满分(12 篇 knowledge 回流、F_prompt=1.0) |

> 全局均值行(11 target 合计 n=33)与逐链明细见 `evaluation/results/results.md`;Top Loss 频次表为空(0 条丢失)。

## 2. 语料与分层验证

### 2.1 三个评测语料

| 语料 | 构成 | 代表性 |
|---|---|---|
| **S1_real** | 上游仓库真实 skill(agent-fullcycle-engineering),12 篇 references,system_prompt 13,286 字符 | 真实长文 + 知识目录;案例 4 实测经 langflow 往返 12737 → 12737 字符、12/12 篇 sha256 一致 |
| **S2_cn** | 中文合成:多级列表、代码块、引号、emoji | 中文与 YAML/JSON 转义边界;案例 8 实测经 flow.json 编码往返 `diff` 无输出(逐字节一致) |
| **S3_min** | 仅 SKILL.md 极简(无 references) | 最小输入边界 |

### 2.2 四层验证链

**第 1 层 · 静态 F(33 链全 1.0000)** — 3 语料 × 11 target 的 roundtrip(emit → parse → write_skill → load_skill)后,F_name / F_desc / F_prompt / F_know_q / F_know_c 全部 1.0000,forward 侧 V_format 亦全部 1.0000,Loss 点 0 条(`evaluation/results/results.md` 汇总表,全局均值行 n=33)。迭代轨迹:基线全局 F_prompt=0.9189、F_name=0.875 → 修复 R1–R6 后 24 链全 1.0 → 新增 autogen、n8n、mermaid-workflow 扩至 33 链仍全 1.0(REPORT §2.1、§6.4)。

**第 2 层 · 语义 S(两列全 1.0000)** — S_struct(tasks LCS 保序率 + 知识集 Jaccard + name/desc 全等,权重 0.4/0.3/0.2/0.1)与 S_terms(数字 / 限定词 / 否定 / 强命令 / 专有名词五类 token 保留率)并入汇总矩阵,全语料两列 1.0000(`evaluation/semantics.py`,纯规则零依赖)。该层历史上钉出并修复 P1(多 agent 角色丢失)、P2(分支 DAG 压扁)两类真实缺陷。

**第 3 层 · 行为 L3(一致率 100%)** — glm-4-flash、temperature 0.2、max_tokens 600,5 个探针问题(答案均有正文依据),三形态同模型同参各答一次、LLM judge 判一致:A(原 SKILL.md 正文,12736 字)vs B(crewai 产物 backstory,12979 字)**5/5 = 100%**;A vs C(n8n 产物 x-source-skill.systemPrompt,12736 字)**5/5 = 100%**,无判定错误(`evaluation/behavior/results.md`)。

**第 4 层 · 运行时与外部语料** — ① 真实框架加载/执行:crewai 1.15.27 **6/6 PASS**(含真实 `crewai.skills.load_skill` 加载我们的 skills/ 目录)、langchain 1.4.4 + core 1.6.9 PASS(fake model 跑完整 `agent.invoke`)、deepagents 0.7.23 PASS(FilesystemBackend + fake model 一轮);② GLM 真实模型双协议端到端:**9 链全绿**(OpenAI 兼容 glm-4-flash 与 Anthropic 兼容 glm-5.3-flash 两条路径,统一问题命中 4/4 模式词,证明 system prompt / 技能目录真实生效);③ 外部第三方语料 14 份:agent→skill parse **11/11**、write+load 回读 11/11;skill→agent V_format **24/24**、四链 F_name/F_desc/F_prompt **12/12 满分**(`evaluation/external/results.md`)。

## 3. 真实第三方实例清单(14 份输入,全部非本工具生成)

针对「corpus 同源」威胁的正面泛化测试,输入取自 crewAIInc/crewAI-examples、langflow 官方 fixtures、wshobson/agents、anthropics/skills 四个第三方仓库。

**Stage A:agent→skill(11 份,parse 11/11,write+load 回读 11/11)**

| 输入 | 来源 | 格式 | 解析 name | prompt 长度 | tools | 回读 |
|---|---|---|---|---|---|---|
| game-builder-crew | crewAI-examples | crewai | senior-engineer-agent | 256 | 0 | ok |
| landing_page_generator | crewAI-examples | crewai | senior-idea-analyst | 319 | 0 | ok |
| marketing_strategy | crewAI-examples | crewai | lead-market-analyst | 311 | 0 | ok |
| recruitment | crewAI-examples | crewai | researcher | 294 | 0 | ok |
| basic_prompting@1.9.0 | langflow fixtures | langflow | basic-prompting | 116 | 0 | ok |
| research_agent@1.9.0 | langflow fixtures | langflow | research-agent | 461 | 0 | ok |
| meeting_summary@1.9.0 | langflow fixtures | langflow | meeting-summary | 131 | 0 | ok |
| pokedex_agent@1.6.0 | langflow fixtures | langflow | pok-dex-agent | 260 | 0 | ok |
| backend-architect | wshobson/agents | claude-subagent | backend-development-backend-architect | 17879 | 0 | ok |
| eval-judge | wshobson/agents | claude-subagent | eval-judge | 2808 | 3 | ok |
| image-generator | wshobson/agents | claude-subagent | image-generator | 1884 | 1 | ok |

**Stage B:skill→agent(3 份,anthropics/skills 官方 docx / pdf / pptx × 8 个 emitter)**

| 输入 | 结果 |
|---|---|
| docx | V_format 8/8;四链(crewai / langflow / claude-subagent / generic 往返)F_name / F_desc / F_prompt 全 1.0000 |
| pdf | V_format 8/8;四链全 1.0000 |
| pptx | V_format 8/8;四链全 1.0000(pptx 的 description 含 `\"` 转义,曾致 F_desc=0.9840,R13 修复后 1.0000) |

合计:V_format **24/24**,四链 F 三项 **12/12 满分**。过程中修掉 5 处真实兼容缺陷(R9 真实项目模板路径 `src/<pkg>/config/`、R10 多 agent 全记录、R11 langflow 无 Prompt 组件兜底、R12 行内逗号 tools、R13 折叠块脏前缀与 YAML 转义漂移)。

## 4. 能力保留速查

- **无损通道 = crewai-skills / deepagents**:scripts(实测 docx 59/59)、渐进披露、agentskills.io 合规全部原生保留——脚本型技能(docx / pdf / pptx)优先选这两个 target。
- **scripts/ 只在 skill 目录形态随迁**:其余 target 不迁是有意的(无执行脚本挂载点),IR 保留路径名单,`write_skill(copy_scripts_from=...)` 回程可恢复。
- **input_schema 当前实际**:仅 generic 完整保留并往返;langchain/autogen 见 `tests/test_tool_schema_roundtrip.py`(本轮新增) `langchain/autogen/deepagents 三链已支持 input_schema 字典级往返 + side_effects 回读(tests/test_tool_schema_roundtrip.py);其余格式仍 name-only,.generic 仍为唯一全 schema 格式。`;其余 target 保留工具名 + 描述。
- **n8n / mermaid 的 tools 与凭据节点不自动生成**:AI Agent 节点的 tool 子节点与凭据需人工在 n8n 界面补挂;mermaid 为纯文本格式,无工具挂载点。
- **渐进披露三级**:crewai / crewai-skills(CrewAI 三级原生)、deepagents(SkillsMiddleware 三级);langchain / openai 等为常量全量进上下文,无自动按需读。

完整逐格矩阵(含降级标记 ⚠️/❌ 与证据链接)见 `examples/CAPABILITY-MATRIX.md`。

## 5. 已知限制

**语义验证层**(`llm-wiki/05-evaluation/semantic-equivalence.md` §局限):

- L3 依赖真实 LLM,temperature 0.2 仍有随机性,同题重跑一致率会波动(90% 阈值留余量但不消除方差);
- 探针覆盖有限:当前已记录结果为单轮短题(5 题),长上下文与多轮对话场景下的行为漂移未系统覆盖;
- L2 术语表是启发式:五类 token 之外的语义载体(隐喻、语气强弱)不在统计内,专有名词识别可能漏类;
- 行为等价 ≠ 输出逐字等价:L3 判回答语义一致,与字符级 F 指标口径互补而非替代。

**转换能力层(上轮缺点清单剩项)**:

- **角色对齐启发式**:tasks.yaml 未标 agent 且 agent 数 = task 数时按序对齐(`converter/wir.py`),真实项目若非一一对应会错配;
- **非 markdown 步骤**:workflow 步骤提取依赖 markdown 结构(workflow 节编号列表 / 全文编号列表 / `Step N` 标题三种形态),无形态正文退化为单节点兜底(`converter/workflow_extract.py` 形态 d);
- **input_schema 非全格式落点**:多数链路 tools 仅保 name / description,全链路 schema 往返在 Roadmap(langchain/autogen 本轮在补,见 §4 标记);
- **运行时残余**(REPORT Round 3 后):langflow 真实 UI / 服务端导入回放未做(需 docker);openai 产物未在真实 Codex CLI 会话加载;真实调用仅覆盖 glm-4-flash / glm-5.3-flash 两档;tools 端到端(stub 换真实工具后模型正确调用)未测。

## 6. 复现命令

```bash
# 1. 静态矩阵:33 链 F/S/V 指标 → evaluation/results/results.{md,json}
python3 evaluation/run_eval.py

# 2. 全量单元/矩阵测试(2026-10-11 实测:117 通过,1 skip)
python3 -m unittest discover tests

# 3. 外部真实语料泛化(14 份第三方输入)
python3 evaluation/external/run_external.py

# 4. L3 行为等价(需 GLM key)
python3 evaluation/behavior/probe_behavior.py

# 5. 真实框架运行时(框架缺失自动 skip,venv 依赖见各脚本 docstring)
python3 -m unittest evaluation.runtime.test_crewai_runtime \
                   evaluation.runtime.test_langchain_runtime

# 6. GLM 双协议端到端(需 GLM_API_KEY / GLM_BASE_URL / GLM_MODEL /
#    GLM_ANTHROPIC_BASE_URL / GLM_ANTHROPIC_MODEL,缺省自动 skip)
python3 -m unittest evaluation.runtime.test_glm_e2e_langchain \
                   evaluation.runtime.test_glm_e2e_crewai \
                   evaluation.runtime.test_glm_e2e_autogen

# 7. schema 深度一致性(对官方真实结构逐字段 diff)
python3 evaluation/schema_diff.py
```

单次转换:`python3 cli.py skill2agent <skill目录> --target <格式>` / `python3 cli.py agent2skill <产物> --from <格式>` / 万能子命令 `python3 cli.py convert <输入> --from <形态> --target <形态>`(12 种 `--from` × 11 种 `--target`),可复现案例见 `examples/SHOWCASE.md`。
