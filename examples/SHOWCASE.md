# 转换案例

以下案例全部真实执行,命令可直接复制到仓库根目录复现(零依赖,Python ≥3.9)。

## 案例 1:skill → CrewAI 原生 skills(正向)

把仓库自带的真实 skill([agent-fullcycle-engineering](agent-fullcycle-engineering/SKILL.md))转成 CrewAI v1.12+ 的原生 skills 目录:

```bash
python3 cli.py skill2agent examples/agent-fullcycle-engineering --target crewai-skills --out out/case1
```

产物 16 个文件,布局(摘录):

```text
out/case1/
├── config/agents.yaml          # 含 skills: 挂载字段
├── config/tasks.yaml
├── skills/agent-fullcycle-engineering/
│   ├── SKILL.md                # 合法 Agent Skills 格式,可直接被 crewai 加载
│   └── references/             # 12 篇知识文档原样迁移
└── README.md
```

`config/agents.yaml` 实际内容(摘录):

```yaml
agent-fullcycle-engineering:
  role: |
    Agent Fullcycle Engineering
  goal: |
    End-to-end AI agent engineering workflow for designing, building, debugging,
    testing, evaluating, observing, deploying, and improving LLM or AI agents...
  backstory: |
    # Agent Fullcycle Engineering

    ## Overview

    Use this skill to turn an agent idea into a working, testable, operable system...
  skills:
    - "./skills/agent-fullcycle-engineering"
```

## 案例 2:第三方 CrewAI 项目 → skill(反向)

输入是 **crewAI-examples 官方仓库的真实项目** [screenplay_writer](https://github.com/crewAIInc/crewAI-examples/tree/main/crews/screenplay_writer)(非本工具生成;该项目是多 agent 的):

```bash
# 假设把该项目 clone 到 ./screenplay_writer
python3 cli.py agent2skill ./screenplay_writer --from crewai --out out/case2
```

原 `config/agents.yaml`(第一个 agent,原文):

```yaml
spamfilter:
  role: >
    spamfilter
  goal: >
    Decide whether a text is spam or not.
  backstory: >
    You are an expert spam filter with years of experience. You DETEST advertisements,
    newsletters and vulgar language.
```

生成的 `SKILL.md`(实际输出):

```markdown
---
name: spamfilter
description: Decide whether a text is spam or not.
---

# spamfilter

## Role
spamfilter

## Goal
Decide whether a text is spam or not.

## Backstory
You are an expert spam filter with years of experience. You DETEST advertisements,
newsletters and vulgar language.
```

多 agent 项目取第一个 agent,其余 agent 名完整记录在 `metadata.agents_all`,不丢弃信息。

## 案例 3:Langflow 官方 flow → skill(反向)

输入是 **Langflow 官方测试夹具** [basic_prompting.json](https://github.com/langflow-ai/langflow/blob/main/src/lfx/tests/fixtures/starter_flows/v1.9.0/basic_prompting.json)(v1.9 真实导出格式,非本工具生成):

```bash
python3 cli.py agent2skill ./basic_prompting.json --from langflow --out out/case3
```

生成的 `SKILL.md`(实际输出,完整):

```markdown
---
name: basic-prompting
description: Perform basic prompting with an OpenAI model.
---

Answer the user as if you were a GenAI expert, enthusiastic about helping them
get started building something fresh.
```

## 案例 4:roundtrip 保真(评测演示)

skill 经 langflow(`flow.json` JSON 编码)再完整还原,知识文档逐篇比对哈希:

```python
from converter.skill_loader import load_skill
from converter.emitters import EMITTERS
from converter.parsers import PARSERS
from converter.skill_writer import write_skill

ir_in = load_skill("examples/agent-fullcycle-engineering")
EMITTERS["langflow"](ir_in, "out/case4")           # skill → flow.json
parsed = PARSERS["langflow"](out_dir := "out/case4/flow.json")
write_skill(parsed, "out/case4-back")              # flow.json → skill
```

实际输出:

```text
输入 references: 12 篇
经 langflow(flow.json JSON 编码)再还原后 sha256 一致: 12/12
system_prompt: 输入 12737 字符 → 还原 12737 字符(F_prompt = 1.0)
```

完整评测(27 条链路 × 6 项指标、外部真实语料、真实 LLM 端到端)见 [evaluation/REPORT.md](../evaluation/REPORT.md),复现入口 `python3 evaluation/run_eval.py`。
