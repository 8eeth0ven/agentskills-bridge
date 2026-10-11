# 语义等价验证标准

字符级指标(`F_prompt` 等,见 [roundtrip-fidelity](roundtrip-fidelity.md))度量的是**字面保真**;本章定义与之互补的**语义等价**三层验证体系——结构、术语、行为各占一层。层名、指标名与方法以本章为唯一真相,实现侧不得偏离。

- L1/L2 实现:`evaluation/semantics.py`(纯规则,零外部依赖,已并入 `evaluation/run_eval.py` 汇总,结果矩阵新增 `S_struct` / `S_terms` 两列)
- L3 实现:`evaluation/behavior/`(真实 LLM 调用,需 GLM key)

## 为什么字符级不够

`F_prompt` 本质是 levenshtein 编辑距离比例,它对语义漂移与合法重组两个方向都失真:

- **测不出语义漂移**:「步骤顺序调换」「否定词丢失(not / 禁止 / never)」「条件分支丢失(if-else 只剩 if」)这类改写,字符编辑距离很小、`F_prompt` 接近 1,但执行语义已经反转——这类缺陷恰是最危险的静默丢失。
- **对合法结构重组误伤**:转换产物把正文重组为分节、把列表改写为编号段,是格式契约内的合法变换;字符距离拉大导致 `F_prompt` 低估,把语义等价的产物判为有损。

结论:语义验证需要一个**独立于字符距离的层次**,规则可判的交给规则(L1/L2),规则判不了的交给真实 LLM 对照(L3)。

## 三层验证体系

| 层 | 名称 | 方法 | 依赖 | 指标 |
|----|------|------|------|------|
| L1 | 结构等价 | 规则:tasks LCS 保序率 + 知识文件集 Jaccard + name/desc 全等 | 零 | `S_struct ∈ [0,1]` |
| L2 | 术语保留 | 规则:数字 / 限定词 / 否定 / 强命令 / 专有名词 五类 token 保留率 | 零 | `S_terms ∈ [0,1]` |
| L3 | 行为等价 | 真实 LLM:原形态与转换形态同题同模型对照,LLM judge 判一致 | GLM key | A-B / A-C 一致率 |

- **L1 结构等价**:roundtrip 后 tasks 序列做最长公共子序列(LCS),保序率 = LCS 长度 / 原序列长度;知识文件集按文件名求 Jaccard;name / description 归一化全等。三要素合成 `S_struct`——顺序调换在 LCS 层直接暴露。
- **L2 术语保留**:从原文提取五类承载语义的 token——数字(阈值 / 步数 / 版本号)、限定词(only / must / at most)、否定(not / never / 禁止)、强命令(must / shall / 一定要)、专有名词(模型名 / 工具名 / 文件名)——逐类统计 roundtrip 后的保留率,加权合成 `S_terms`。否定词与数字丢失在该层暴露。
- **L3 行为等价**:同一探针问题分别喂给原形态产物与转换形态产物(同模型、同参数),由 LLM judge 比对两个回答是否语义一致。前两层测「文本像不像」,L3 测「用起来是否等价」。

## L3 协议

- **探针问题选取**:每题必须在正文中有明确依据——数字(「共几步」「阈值是多少」)、清单(「列出全部 X」)、条件(「当 Y 时该做什么」)——保证期望答案可从原文唯一推出,不引入主观发挥。
- **对照设置**:原形态与转换形态用**同模型、同温度(0.2)、同 max_tokens** 发问,消除参数差异;两问独立发出,互不污染。
- **judge 输出**:LLM judge 对(原答,转答)输出 JSON `{"equivalent": true|false, "reason": "..."}`,reason 必须指出不一致点(若判 false)。
- **通过阈值**:一致率 ≥ 90% 视为通过;单题偶发不一致不立即判死,需人工复读该题 reason 后定论。

## 语义审计已修复的缺陷

三层体系不是纸面设计——它钉出过两类真实缺陷并已修复(修复均在 `converter/` 侧,证据可复现):

| 编号 | 缺陷 | 根因 | 修复 |
|------|------|------|------|
| P1 | 多 agent 角色丢失:crewai 多 agent 项目转 workflow 后,节点只知「做什么」,不知「谁以什么角色做」 | tasks.yaml 常不写 agent 字段(运行时分配),IR.tasks 的 agent 为空 | `converter/wir.py`:节点 prompt 前缀 `As <role>. Goal: <goal>`;task 未标 agent 且 agent 数与 task 数相等时按序对齐(crewai 常见模式) |
| P2 | 分支 DAG 压扁:n8n 分支(A→B 且 A→C)被压成线性链 | tasks/chain 是图的线性投影,分支边无处安放 | `converter/parsers/n8n.py`:完整边表存 `metadata.graph_edges`;`converter/emitters/n8n.py`:重建 connections 时优先按 graph_edges 还原分支 |

修复证据:

- **P1**:crewAI-examples 真实项目 screenplay_writer(5 agents / 5 tasks)转 n8n,5/5 节点 prompt 均带角色前缀(如 `As spamfilter. Goal: Decide whether a text is spam or not.`)。
- **P2**:构造 A→B / A→C 分支的 n8n workflow,经 generic(agent.json 内嵌 `metadata.graph_edges`)roundtrip 回 n8n,connections 仍为分支:`{Chat Trigger→A, A→B, A→C}`。

## 局限

- L3 依赖真实 LLM,温度 > 0 带来随机性——同题重跑一致率会波动,90% 阈值已留余量但不消除方差。
- 探针覆盖有限:当前探针为单轮短题,未测长上下文与多轮对话场景下的行为漂移。
- L2 术语表是启发式:五类 token 之外的语义载体(如隐喻、语气的强弱)不在统计内,专有名词识别可能漏类别。
- 行为等价 ≠ 输出逐字等价:L3 判的是回答语义一致,允许措辞与组织差异——这与字符级指标的口径不同,两者互补而非替代。
