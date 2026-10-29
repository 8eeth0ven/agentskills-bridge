# Roundtrip 保真度评测体系

本章保留 skill ↔ agent 双向转换的质量评估方法,用于理解原生格式映射与资产恢复的区别。它回答两个问题:正向产物是否合规(forward),以及 skill → agent → skill 往返后信息保留了多少(roundtrip)。这些指标是方法说明,仓库不再分发测试脚本、测试语料或评测报告。

## 指标定义

粒度均为**逐样本**(per-sample):每个 (corpus, target, sample) 组合产出一组指标值,汇总时按 corpus × target 聚合。

| 指标 | 公式 | 粒度 | 含义 |
|------|------|------|------|
| `F_name` | `slugify(name_out) == slugify(name_in)` → 1,否则 0 | 逐样本 | name 保真度:经 `slugify` 归一(大小写/分隔符)后全等才记 1——容忍规范化差异,不允许实质改名 |
| `F_desc` | description 归一化(`strip` + 换行→空格)后全等 → 1;否则 `1 − levenshtein(a, b) / max_len(a, b)` | 逐样本 | description 保真度:全等满分,否则按字符编辑距离比例扣分,连续值 [0, 1] |
| `F_prompt` | system_prompt 归一化(`\r\n`→`\n`、`strip`)后全等 → 1;否则 `1 − levenshtein(a, b) / max_len(a, b)` | 逐样本 | system_prompt 保真度:只容忍行尾符与首尾空白差异,其余按编辑距离比例扣分 |
| `F_know_q` | `count(knowledge_out) / count(knowledge_in)`;in = 0 时定义为 1 | 逐样本 | knowledge 数量保全率:往返后 references 文件数不减少才得 1 |
| `F_know_c` | `sha256 一致文件数 / count(knowledge_in)`;in = 0 时定义为 1 | 逐样本 | knowledge 内容保全率:按 `filename` 配对、内容 sha256 一致的文件数占比 |
| `V_format` | forward 产物静态校验通过 → 1,否则 0(附失败原因) | 逐样本 | 正向产物合规率:目标目录结构/关键文件存在且语法合法(YAML/JSON 可解析、必填键齐全),属静态校验非运行验证 |
| `L` | Loss points 清单 | 逐样本 | 丢失/降级点:逐条记录哪个字段丢了或降级了、为什么(如 `default_prompt: crewai 无槽位`) |

约定:

- `max_len(a, b) = max(len(a), len(b))`;双方皆空串时编辑距离项定义为 1(即全等)。
- `F_know_c` 只数"配对成功且 sha256 一致"的文件;out 侧多出的文件不计分,逐条记入 `L`。
- `V_format` 的校验规则按各 target 的产物契约执行(见 [skill-to-agent](../04-conversion/skill-to-agent.md))。

## 输入覆盖建议

| 语料 | 内容 | 覆盖意图 |
|------|------|----------|
| 真实技能包 | 真实 skill `agent-fullcycle-engineering`(仓库 `examples/` 内) | 真实形态:长正文 + references + scripts + `agents/openai.yaml` 三件套 |
| 中文与结构边界 | 合成 skill:中文正文 + 引号 + emoji + 多级列表 | 压力面:非 ASCII、YAML 引号陷阱、嵌套 markdown 结构 |
| 极简技能包 | 极简 skill:仅 `SKILL.md`(name + description + 正文) | 下界:无 references/scripts/interface,验证空列表路径不崩 |

选择输入时还应覆盖二进制附件、递归参考目录、可执行权限、扩展 frontmatter、空文件和 CRLF。上表描述输入类别,不对应随仓库分发的测试集。

## 实验矩阵

每个 corpus × target 组合跑两条链:

- **forward**:skill → `load_skill` → `emit_<fmt>`,测 `V_format` + `L`;
- **roundtrip**:skill → emit → 对应 parser → `write_skill`,测全部 F 指标(`F_name` / `F_desc` / `F_prompt` / `F_know_q` / `F_know_c`)。

对每种输入分别运行所需目标,逐样本记录后再按输入与目标格式聚合。当前 11 个 target 及其反向解析入口:

| target | 反向解析入口(roundtrip 起点) |
|--------|------------------------------|
| `crewai` | 产物根目录(`config/agents.yaml` + `config/tasks.yaml`) |
| `crewai-skills` | 产物根目录(`skills/*/SKILL.md`,原生形态原样保真) |
| `deepagents` | 产物根目录(`skills/` 优先,`agent.py` 回退) |
| `langchain` | `agent.py` |
| `langflow` | `flow.json` |
| `openai` | 产物根目录(`instructions.md` + `agents/openai.yaml`) |
| `claude-subagent` | 产物根目录(`.claude/agents/*.md`,frontmatter + 正文) |
| `generic` | `agent.json` |
| `autogen` | `agent.py` |
| `n8n` | `workflow.json` |
| `mermaid-workflow` | `workflow.md` |

## 原生映射与资产完整性

通过公开 `EMITTERS` / `PARSERS` 注册表转换时，Preservation Capsule 保存目标原生格式无法表达的 IR 字段与原始普通文件。验证完整性时应检查整个输出目录，而不是只复制一个配置文件：

```bash
python3 cli.py skill2agent examples/agent-fullcycle-engineering --target langchain --out out/langchain
python3 cli.py verify out/langchain
python3 cli.py agent2skill out/langchain --from langchain --out out/restored
```

`verify` 核对当前包的原生产物、IR 与源文件清单。要判断往返是否保持原始资产，还需逐项比较输入与恢复目录的文件集合、字节和 POSIX 权限。原生格式字段的检查应独立进行，不能以 capsule 成功读回替代真实运行时验证。协议细节见 [INTERFACE.md](../../INTERFACE.md)。

## 指标局限

- `F_desc` / `F_prompt` 用字符级 levenshtein,度量字面保真而非语义等价——往返重组后语义等价但措辞有变的产物会被低估。
- `V_format` 是产物静态校验(结构 + 语法),不是端到端运行验证——通过 `V_format` 不代表目标框架真跑得通。
- 合成输入不覆盖真实 skill 的全部形态；超长正文、frontmatter 扩展、递归资源与依赖运行时的脚本需要分别检查。
