# L3 行为等价实测结果

- 日期:2026-10-11
- 模型:glm-4-flash | temperature:0.2 | max_tokens:600
- 探针协议:5 个探针问题(答案均有 SKILL.md 正文依据);三形态 system prompt 同模型同参各答一次;judge 用同模型对 (A 答, X 答) 只输出 `{"equivalent":bool,"reason":"≤30字"}`
- 形态:A=原 SKILL.md 正文(strip frontmatter,12736 字);B=crewai 产物 backstory(12979 字);C=n8n 产物 x-source-skill.systemPrompt(12736 字)

## 一致率

| 对比 | 等价 | 不等价 | 判定错误 | 一致率 |
|---|---|---|---|---|
| A-B | 5 | 0 | 0 | 100% |
| A-C | 5 | 0 | 0 | 100% |

## 逐题判定与摘录

### A-B(A vs B)

**Q1** 这个 skill 列出的 Response Modes 有哪几种?只列名字
- 判定:`True` | 理由:数字、列表项集合、核心结论一致
- A 答:这个 skill 列出的 Response Modes 有以下几种： 1. Beginner learning 2. I…
- B 答:这个 skill 列出的 Response Modes 有以下几种： - Beginner learning - Int…

**Q2** 最多同时运行几个 subagents?(数字)
- 判定:`True` | 理由:数字和核心结论一致
- A 答:根据文档中的描述，默认情况下最多同时运行三个 subagents： > Run at most three subage…
- B 答:根据文档中的描述，默认情况下最多同时运行 **三个 subagents**。 以下是相关段落： > - 运行最多三个 s…

**Q3** 选择架构时,什么时候才考虑 planner/executor 或 multi-agent?
- 判定:`True` | 理由:核心结论一致，细节描述不同
- A 答:选择架构时，只有在以下情况下才考虑使用 planner/executor 或 multi-agent： 1. **任务复…
- B 答:选择架构时，只有在以下情况下才考虑使用 planner/executor 或 multi-agent： 1. **任务复…

**Q4** skill 说调试时应该 patch 哪一层?
- 判定:`True` | 理由:核心结论和步骤一致
- A 答:根据提供的文档，调试时应该遵循以下步骤来 patch 最窄的失败层： 1. **收集证据**：首先收集与问题相关的所有信…
- B 答:根据提供的 Agent Fullcycle Engineering 技能文档，调试时应该遵循以下原则来 patch 最合…

**Q5** 首次发布前必须完成哪些最低要求中的两项即可,任举两项
- 判定:`True` | 理由:核心结论一致，数字和列表项集合相同
- A 答:首次发布前，以下两项最低要求是必须完成的： 1. **用户目标和验收标准**：确保用户的目标和项目需要达到的验收标准被明…
- B 答:根据文档中提到的“Minimum Done Definition”，以下是两项首次发布前必须完成的最低要求： 1. **…

### A-C(A vs C)

**Q1** 这个 skill 列出的 Response Modes 有哪几种?只列名字
- 判定:`True` | 理由:数字、列表项集合、核心结论一致
- A 答:这个 skill 列出的 Response Modes 有以下几种： 1. Beginner learning 2. I…
- C 答:这个 skill 列出的 Response Modes 有以下几种： 1. Beginner learning 2. I…

**Q2** 最多同时运行几个 subagents?(数字)
- 判定:`True` | 理由:数字一致，核心结论相同
- A 答:根据文档中的描述，默认情况下最多同时运行三个 subagents： > Run at most three subage…
- C 答:默认情况下，最多同时运行三个 subagents。 这是为了确保任务执行的可控性和稳定性。具体来说： - **三个 su…

**Q3** 选择架构时,什么时候才考虑 planner/executor 或 multi-agent?
- 判定:`True` | 理由:核心结论一致，细节略有不同
- A 答:选择架构时，只有在以下情况下才考虑使用 planner/executor 或 multi-agent： 1. **任务复…
- C 答:选择架构时，只有在以下情况下才考虑使用 planner/executor 或 multi-agent： 1. **任务复…

**Q4** skill 说调试时应该 patch 哪一层?
- 判定:`True` | 理由:核心结论一致，步骤相同
- A 答:根据提供的文档，调试时应该遵循以下步骤来 patch 最窄的失败层： 1. **收集证据**：首先收集与问题相关的所有信…
- C 答:根据提供的文档，调试时应该遵循以下步骤来 patch 最窄的失败层： 1. **收集证据**：首先收集与问题相关的所有信…

**Q5** 首次发布前必须完成哪些最低要求中的两项即可,任举两项
- 判定:`True` | 理由:核心结论一致，数字和列表项集合相同
- A 答:首次发布前，以下两项最低要求是必须完成的： 1. **用户目标和验收标准**：确保用户的目标和项目需要达到的验收标准被明…
- C 答:首次发布前，以下两项最低要求是必须完成的： 1. **用户目标和验收标准**：确保用户的目标和项目需要达到的验收标准被明…
