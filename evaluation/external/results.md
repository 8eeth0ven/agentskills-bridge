# 外部真实 corpus 泛化测试(2026-10-11)

输入全部来自第三方仓库(crewAIInc/crewAI-examples、anthropics/skills、
langflow-ai/langflow 官方 fixtures、wshobson/agents 真实 subagents),
无一份由本项目 emitter 生成 —— 针对「corpus 同源」威胁的正面测试。

## Stage A:agent→skill(真实 agent 输入 → parse → write_skill → load_skill)

- parse 成功率:**11/11**;write+load 回读成功:**11/11**

| 输入 | 格式 | parse | name | display_name | desc_len | prompt_len | tasks | knowledge | tools | agents_all | write+load |
|---|---|---|---|---|---|---|---|---|---|---|---|
| game-builder-crew | crewai | ok | senior-engineer-agent | Senior Engineer Agent | 25 | 256 | 3 | 0 | 0 | senior_engineer_agent,qa_engineer_agent,chief_qa_engineer_agent | ok |
| landing_page_generator | crewai | ok | senior-idea-analyst | Senior Idea Analyst | 132 | 319 | 7 | 0 | 0 | senior_idea_analyst,senior_strategist,senior_react_engineer,senior_content_editor | ok |
| marketing_strategy | crewai | ok | lead-market-analyst | Lead Market Analyst | 116 | 311 | 5 | 0 | 0 | lead_market_analyst,chief_marketing_strategist,creative_content_creator,chief_creative_director | ok |
| recruitment | crewai | ok | researcher | Researcher | 37 | 294 | 4 | 0 | 0 | researcher,matcher,communicator,reporter | ok |
| basic_prompting@1.9.0 | langflow | ok | basic-prompting | Basic Prompting | 45 | 116 | 0 | 0 | 0 | - | ok |
| research_agent@1.9.0 | langflow | ok | research-agent | Research Agent | 111 | 461 | 0 | 0 | 0 | - | ok |
| meeting_summary@1.9.0 | langflow | ok | meeting-summary | Meeting Summary | 129 | 131 | 0 | 0 | 0 | - | ok |
| pokedex_agent@1.6.0 | langflow | ok | pok-dex-agent | Pokédex Agent | 62 | 260 | 0 | 0 | 0 | - | ok |
| backend-architect | claude-subagent | ok | backend-development-backend-architect | Backend Development Backend Architect | 394 | 17879 | 0 | 0 | 0 | - | ok |
| eval-judge | claude-subagent | ok | eval-judge | Eval Judge | 163 | 2808 | 0 | 0 | 3 | - | ok |
| image-generator | claude-subagent | ok | image-generator | Image Generator | 204 | 1884 | 0 | 0 | 1 | - | ok |

## Stage B:skill→agent(anthropics/skills 真实 skill × 全部 emitter)

- V_format 通过:**24/24**(emitter 键 8 个 × skill 3 个)

| skill | target | V_format | 失败原因 |
|---|---|---|---|
| docx | crewai | 1 |  |
| docx | crewai-skills | 1 |  |
| docx | deepagents | 1 |  |
| docx | langchain | 1 |  |
| docx | langflow | 1 |  |
| docx | openai | 1 |  |
| docx | claude-subagent | 1 |  |
| docx | generic | 1 |  |
| pdf | crewai | 1 |  |
| pdf | crewai-skills | 1 |  |
| pdf | deepagents | 1 |  |
| pdf | langchain | 1 |  |
| pdf | langflow | 1 |  |
| pdf | openai | 1 |  |
| pdf | claude-subagent | 1 |  |
| pdf | generic | 1 |  |
| pptx | crewai | 1 |  |
| pptx | crewai-skills | 1 |  |
| pptx | deepagents | 1 |  |
| pptx | langchain | 1 |  |
| pptx | langflow | 1 |  |
| pptx | openai | 1 |  |
| pptx | claude-subagent | 1 |  |
| pptx | generic | 1 |  |

### 四链 parse 回(F vs load_skill 的 ir_in)

- F_name:均值 1.0,满分 12/12
- F_prompt:均值 1.0,满分 12/12
- F_desc:均值 1.0,满分 12/12

| skill | target→chain | 状态 | F_name | F_prompt | F_desc | 原因 |
|---|---|---|---|---|---|---|
| docx | crewai→crewai | ok | 1.0000 | 1.0000 | 1.0000 |  |
| docx | langflow→langflow | ok | 1.0000 | 1.0000 | 1.0000 |  |
| docx | claude-subagent→claude-subagent | ok | 1.0000 | 1.0000 | 1.0000 |  |
| docx | generic→generic | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pdf | crewai→crewai | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pdf | langflow→langflow | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pdf | claude-subagent→claude-subagent | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pdf | generic→generic | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pptx | crewai→crewai | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pptx | langflow→langflow | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pptx | claude-subagent→claude-subagent | ok | 1.0000 | 1.0000 | 1.0000 |  |
| pptx | generic→generic | ok | 1.0000 | 1.0000 | 1.0000 |  |

## 发现的真实格式 → 修的兼容点

| 真实格式(第三方仓库) | 兼容点(parser 改动)|
|---|---|
| crewai: 真实项目模板路径是 src/<pkg>/config/agents.yaml 且包名 ≠ 项目目录名(game-builder-crew → src/game_builder_crew/config/),原探测只到 src/config/ | crewai.py _candidates 增加 sorted((root/src).glob('*/config/agents.yaml')) 兜底;首跑 4/4 项目 FileNotFoundError,修后 4/4 通过 |
| crewai: 多 agent 文件(真实项目每文件 3-4 个 agent) | parse_crewai 仍取第一个,metadata 新增 agents_all(全部 agent 名)+ agents_count,不静默丢弃(首跑后已验证 marketing_strategy 4 agent 全记录) |
| crewai: agents.yaml 未知字段(llm:/tools:/knowledge_sources: 等;真实仓库当前仅 role/goal/backstory,防御性兼容)、> 折叠块内带引号与 {var} 占位(landing_page_generator) | 白名单 agent.get 取值,未知字段静默忽略(原有行为,保持);pyyaml 天然支持折叠块,_minimal_yaml_load 容错路径不变 |
| langflow: 无 Prompt 节点的 Agent flow(官方 starter "Pokédex Agent"@1.6.0,system_prompt 在 Agent 组件 template.system_prompt.value) | _extract_system_prompt 新增优先级③ Agent 组件 system_prompt(≥20 字符);原模糊回退(>50 字符)降为④;新增⑤ Note 组件文本兜底(noteNode) |
| langflow: 1.9+ LLM 组件 model_name 是覆盖名常为空,模型在 model 字段(ModelInput) | _extract_model 每键依次尝试 model_name → model,取第一个非空 value |
| claude-subagent: tools 为行内逗号串或单值(eval-judge.md `tools: Read, Grep, Glob`;image-generator.md `tools: mcp__meigen__generate_image`),原解析只得 [] | _parse_tools_list 增加行内无方括号分支(逗号切分 + 单值),修后 tools=3 / tools=1 |
| claude-subagent: description 用 >- 折叠块(image-generator.md),ir.parse_frontmatter 把块标记拼进值形成 ">- " 脏前缀 | claude_subagent.py 新增 _clean_scalar 剥离块标量前缀(\|/>/-/\|-/+/数字指示符);ir.py 按契约不可改,在 parser 层修 |
| claude-subagent: 双引号标量值内含 \" 转义(anthropics/skills pptx 的 description 含 \"deck,\" \"slides,\"),parser 不做 YAML 反转义,每过一轮 emitter→parser 漂移一层(\" → \\\"),F_desc=0.9840 | _clean_scalar 叠加 _yaml_unescape(\\ → \、\" → "、\n → 换行,单趟扫描);修后该链 F_desc 0.9840 → 1.0000,四链 12/12 满分 |
| claude-subagent: frontmatter 额外键(color: magenta 等)与缺失可选键(backend-architect.md 无 tools) | 平面提取天然容忍:额外键忽略、缺失键空值,不崩(原有行为,保持) |

