![agentskills-bridge：跨框架转换，把源资产原样带回](docs/assets/bridge-hero.svg)

# agentskills-bridge

**把跨框架转换的回程保真，做到逐字节可验证。**

一份 skill，转成 **11 种 agent / workflow 格式**，经过多跳转换后仍能找回完整源资产。脚本、二进制附件、嵌套参考文件、扩展 frontmatter、工具契约一起随包携带；原始目录可以删除。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/) [![363 strict roundtrips](https://img.shields.io/badge/strict_roundtrips-363%2F363-16856B)](evaluation/preservation/results.json) [![MIT License](https://img.shields.io/badge/license-MIT-64748B)](LICENSE)

## 三步走完，再验一次

转换本身只需 Python 3.10+，无强制第三方依赖，无 API key。运行生成的 agent 时，再安装对应框架、配置模型与真实工具。

```bash
git clone https://github.com/8eeth0ven/agentskills-bridge.git
cd agentskills-bridge

# Skill → CrewAI
python3 cli.py skill2agent examples/agent-fullcycle-engineering \
  --target crewai --out out/crewai

# CrewAI → LangChain
python3 cli.py convert out/crewai --from crewai \
  --target langchain --out out/langchain

# LangChain → 原始 skill
python3 cli.py convert out/langchain --from langchain \
  --target skill --out out/restored

# 检查原生产物、完整源文件与 IR 的一致性
python3 cli.py verify out/langchain
```

`--out` 使用新目录或空目录，避免混入旧产物。`agent2skill <path> --from <format> --out <dir>` 同样可用于回程。

## 一个特长：完整资产可恢复

很多格式可以表达提示词，却没有位置容纳原 skill 的全部资源和契约。agentskills-bridge 同时生成两份相互绑定的产物：

![Preservation Capsule：原生格式与完整资产并行，校验后恢复](docs/assets/roundtrip-contract.svg)

- **原生投影**：目标框架的配置、Python 入口或工作流，按该框架的能力使用。
- **Preservation Capsule**：`.agentskills-bridge/` 中的完整 AgentIR、原始普通文件，以及绑定原生产物的 SHA-256 manifest。

回读时先核对文件集合、字节与权限。产物被修改、删除、增加文件，或 capsule 损坏时，转换明确失败，防止静默恢复过期内容。完整包可以搬到别的目录或机器，回程不依赖源目录。工具 schema、任务、角色与分支元数据通过 IR 保留，即使目标原生格式无法表达它们。

**未编辑输入**恢复原始文件路径、字节与 POSIX 权限位，包括 CRLF、尾随空格、空文件和二进制资源。通过 Python API 合法编辑 IR 后，skill 投影会应用更新后的指令、界面字段、工具契约和知识文件；独立测试直接检查原生文件，避免旧快照覆盖新内容。

原生产物已经手动编辑时，显式重新导入：

```bash
python3 cli.py agent2skill out/langchain --from langchain \
  --native-only --out out/edited-skill
```

`--native-only` 读取当前原生文件，放弃旧 capsule 中无法从原生格式提取的信息。分享和迁移时，请保留整个输出目录，包括隐藏的 `.agentskills-bridge/`。

## 证据可以自己重跑

当前核心结果来自离线、确定性的检查，不需要模型，也不把文本相似度当作字节保真。

| 验证 | 本轮结果 | 检查什么 |
| --- | --- | --- |
| 3 种输入 × 11 × 11 有序格式对 | **363 / 363** | 每跳 IR 字段相等；恢复文件集合、SHA-256、字节数与权限全部相等 |
| 11 种格式循环 10 次 | **3 / 3，每条 110 跳** | 转换前删除源目录，长链后仍能完整恢复 |
| 11 格式 × 6 类损坏 | **66 / 66 显式拒绝** | 修改、缺失、新增、权限变化、IR 损坏、格式不匹配 |
| 官方 docx / pdf / pptx：129 个文件、2.33 MB | **33 / 33 单跳 + 3 条 110 跳长链** | 固定上游 commit，删除源目录后恢复全部普通文件与 IR |
| 独立原生投影审计 | **1,000 份字符串 fuzz + 边界回归** | 绕过 capsule 检查 Python literal、长工具 schema、CrewAI 来源识别 |

```bash
python3 -m unittest discover tests -q
python3 evaluation/benchmark_preservation.py
python3 evaluation/benchmark_real_skills.py  # 首次需网络，获取固定官方 commit
python3 evaluation/run_native_audit.py --baseline 21ad414
python3 cli.py wiki verify
```

[完整基准与开源对照](evaluation/ECOSYSTEM-COMPARISON.md) · [机器可读结果](evaluation/preservation/results.json) · [独立原生审计](evaluation/FIDELITY-AUDIT.md) · [编辑回归审查](evaluation/PRESERVATION-REVIEW.md)

官方真实语料的 [129 文件清单与完整结果](evaluation/preservation/real-skills.json) 只保存相对路径、哈希和指标，上游内容未打包进本仓库。三个文档技能按上游各自的 source-available 许可提供。

本轮实际运行了固定 commit 的 [SkillKit](https://github.com/rohitg00/skillkit) 文本转换接口：8 条受支持路径均转换成功，但未恢复完整 11 文件资源包。本项目在**完整资产可验证回程**这一项，提供了该接口之外的恢复能力。双方目标格式不同，详细证据、版本、脚本和降级提示见[对照报告](evaluation/ECOSYSTEM-COMPARISON.md#skillkit实际源码执行结果)；这些结果不构成穷尽开源的质量排名。

## 支持的格式

下列 11 种目标均可通过注册表和 CLI 双向转换；`skill` 还可作为 `convert --target skill` 的回程目标。

| 格式 | 主要原生产物 |
| --- | --- |
| `crewai` | `config/agents.yaml`、`tasks.yaml`、`knowledge/` |
| `crewai-skills` | `skills/<name>/` 与 CrewAI skills 配置 |
| `deepagents` | `agent.py` 与 `skills/<name>/` |
| `langchain` | `agent.py`、知识文件与工具 stub |
| `langflow` | `flow.json` |
| `openai` | Codex skill 界面配置形态：`agents/openai.yaml`、`instructions.md` |
| `claude-subagent` | `.claude/agents/<name>.md` |
| `autogen` | AutoGen AgentChat `agent.py` |
| `generic` | `agent.json` |
| `n8n` | `workflow.json` |
| `mermaid-workflow` | `workflow.md` |

`AgentIR` 负责统一字段，`WorkflowIR` 负责节点与边。每新增一种格式，实现一对 parser / emitter；无需为所有格式两两编写适配器。Python 接入与 capsule 契约见 [INTERFACE.md](INTERFACE.md)。

## 适用边界

完整资产恢复与框架原生执行是两个验证层次。capsule 不会让目标框架自动支持它原本没有的工具、权限或编排。生成的工具 stub 需要真实后端；n8n 凭据和工具子节点需要补齐，Mermaid 用于表达流程。

第三方原生工程没有本项目的 capsule 时，parser 尽力提取可识别的定义，不承诺恢复不存在的源文件或任意动态 Python 工程。模块级 parser / emitter 是低层原生接口；完整保真契约使用 `PARSERS` / `EMITTERS` 注册表或 CLI。

恢复契约覆盖普通文件及 POSIX 权限位。符号链接、特殊文件明确拒绝；空目录、时间戳、所有权与 ACL 不在契约内。SHA-256 检测损坏和陈旧状态，不认证来源；同时改写文件及全部 manifest 的人可以重算哈希。capsule 会携带所选 skill 目录内的原始文件，包的分享范围与原资料一致。

## 继续了解

- [转换实例](examples/SHOWCASE.md)：真实框架输入、脚本型 skill、分支 DAG。
- [原生能力矩阵](examples/CAPABILITY-MATRIX.md)：框架自身的保留与降级；与 capsule 的完整恢复分开理解。
- [历史评测](evaluation/SCORECARD.md)：此前的静态、模型行为与运行时实验；本轮未把历史结果计入新的运行时验证。
- [贡献指南](CONTRIBUTING.md)：添加格式、回归测试与知识库维护。
- `python3 cli.py wiki list`：16 章格式知识库；`wiki verify` 校验完整性。

[MIT License](LICENSE)
