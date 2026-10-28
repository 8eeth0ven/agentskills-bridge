# 资源保真：开源对照与可复现证据

核查日期：2026-10-29。这里比较**明确范围内的可验证能力**，不声称穷尽开源项目，也不以支持的 agent 数量作为转换质量排名。

## 选择一个特长：完整资产可恢复

agentskills-bridge 的重点是：原始 skill 目录删除后，经过多个框架格式，仍能从转换包恢复原始普通文件的路径、字节和 POSIX 权限位，同时保留完整 AgentIR。转换包中的 `.agentskills-bridge/` 保存 IR 和源文件；manifest 将它与原生输出的文件集合、SHA-256 和权限绑定。修改或丢失文件会显式报错，避免静默采用过期快照。

这是**归档保真契约**。它不意味着目标框架会执行封装里的所有工具、权限、工作流或原始资源，也不证明不同框架的模型回答等价。`.agentskills-bridge/` 必须随转换包一起传递；删除它后只能按原生格式支持的字段进行解析。显式 `native_only=True` 用于从已编辑的原生文件重新导入。

## 对照如何选择

| 项目/来源 | 核查对象 | 为什么相关 | 比较边界 |
| --- | --- | --- | --- |
| [SkillKit](https://github.com/rohitg00/skillkit) | commit `d2e5c346f73325c326820efd3188dcf2b6eb704f`，根 package 版本 `1.24.0` | 官方 [Translation](https://www.agenstskills.com/docs/translation) 文档明确提供双向 skill 格式转换；实际 `translate` CLI 调用 content translator | 实测其支持的 Cursor、Windsurf、Copilot、Codex 文本转换路径；没有把其包管理器、安装或 sync 功能算作被测转换接口 |
| [Agent Skills 规范](https://agentskills.io/specification) | 格式结构、可选字段与资源目录 | 规范允许 `scripts/`、`references/`、`assets/` 以及额外文件；完整资产不止 SKILL.md 正文 | 用于定义输入范围；规范本身不是竞争实现 |
| [GitAgent](https://github.com/open-gitagent/gitagent/tree/ed595846b684276e364aa65da38e414109ef8cfb) | commit `ed595846b684276e364aa65da38e414109ef8cfb` | 搜索到历史上的跨框架导出描述，因此核查当前源码 | 当前核查的 `src/exports.ts` 是运行时 SDK 导出，未找到适合本轮执行的框架格式 exporter；不列为量化对照 |

SkillKit 的“46 个 coding agents”和本项目的“11 种目标格式”不是同一个分母：前者很多 agent 共用 SKILL.md，后者还包括通用 JSON 与 Mermaid。两者不能按数字直接排名。

源码证据：[SkillKit CLI 读取单个源文件并调用 translator](https://github.com/rohitg00/skillkit/blob/d2e5c346f73325c326820efd3188dcf2b6eb704f/packages/cli/src/commands/translate.ts#L356-L360)，[将 result.content 写成单个输出文件](https://github.com/rohitg00/skillkit/blob/d2e5c346f73325c326820efd3188dcf2b6eb704f/packages/cli/src/commands/translate.ts#L428-L433)，[CanonicalSkill 与 TranslationResult 接口](https://github.com/rohitg00/skillkit/blob/d2e5c346f73325c326820efd3188dcf2b6eb704f/packages/core/src/translator/types.ts)。这些接口支持正文、常见 frontmatter 和降级提示；本轮接口没有完整源文件清单、文件权限或与目标文件绑定的恢复封装。

## 本项目：严格测试，而非宽松相似度

复现：

```bash
python3 evaluation/benchmark_preservation.py --cycles 10 --out evaluation/preservation/results.json
```

[基准脚本](benchmark_preservation.py) 在临时目录生成 3 种固定输入：极简 skill、11 文件资源包、以及同一资源包加上复杂 JSON Schema 工具、任务角色、分支边和自定义嵌套元数据。工具、分支边和自定义元数据先写进源 SKILL.md 的 bridge 结构化 JSON metadata 扩展，再调用 `load_skill()`；因此这些工具从源文件开始就已存在，精确字节恢复测试没有加载后编辑源映射字段。任务对象单独加入 IR，用于验证额外 IR 状态运输，因为它们没有直接的原生 skill 字段映射。该 fixture 不证明任意第三方 YAML frontmatter 都能语义提取出相同工具契约。

合法编辑是另一种条件：加载后修改 name、prompt、tools 等有原生映射的 IR 字段，输出应反映当前 IR，不能让旧源快照覆盖编辑。此时映射文件内容改变是正确行为，不能要求恢复编辑前字节；编辑正确性由独立的 `tests/test_preservation_edits.py` 验证。它没有被混入原始资产字节不变的 363 条保真成绩。

每份输入在 `load_skill()` 后立即删除源目录，然后执行全部 11×11 个有序格式对（包含同格式），即 `IR → 格式 A → IR → 格式 B → IR → skill`。每跳比较全部公开 IR 字段，只排除本机 `source_path`。最后比较源文件集合、每个文件 SHA-256、字节数和权限；CRLF、尾随空格、空文件、二进制、嵌套路径与可执行位均纳入严格相等判断。

| 指标 | 旧实现基线 | 当前实现 |
| --- | ---: | ---: |
| 3 输入 × 121 有序格式对：IR 与资源全部严格相等 | 0/363 | **363/363** |
| 每种输入连续循环 11 种格式 10 次 | 0/3 | **3/3，每条 110 跳** |
| 11 格式 × 6 类损坏后显式报 `PreservationError` | 无封装能力 | **66/66** |

损坏覆盖原生文件修改、删除、新增、权限变化、封装 IR 修改、格式标签不匹配。SHA-256 检查检测损坏和陈旧包，不提供来源认证；能够同时改写文件与全部 manifest 的人可以重新计算哈希。

原始结果：[当前完整结果](preservation/results.json)、[旧实现完整基线](preservation/baseline.json)。旧实现基线由 commit `21ad41450556aca49a25870292e4f33ca89e764c` 的 `git archive` 导出，在独立目录运行同一脚本；它没有 `source_files` 字段和 preservation capsule。0/363 仅表示未满足本轮新增的严格、完整资产恢复条件，不代表旧实现所有转换均不可用。结果中记录脚本和各实现文件的 SHA-256，可核查评测对应的源码。

## 官方真实语料：129 个原始文件

[anthropics/skills](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44) 的固定 commit `dbd4588f9e1033efb41dad4bef2f7947c8993d44` 提供另一组真实输入。仅选取 `skills/docx`、`skills/pdf`、`skills/pptx` 的全部已跟踪普通文件，包含各自 LICENSE、脚本、参考文件、XML 模板和 schema；没有筛掉复杂文件。上游将这些 document skills 标为 source-available，不能称其为开源语料。

| 上游目录 | 文件数 | 原始字节数 | 11 格式单跳 | 110 跳长链 |
| --- | ---: | ---: | ---: | ---: |
| `skills/docx` | 61 | 1,128,695 | 11/11 | 通过 |
| `skills/pdf` | 12 | 58,692 | 11/11 | 通过 |
| `skills/pptx` | 56 | 1,139,175 | 11/11 | 通过 |
| 合计 | **129** | **2,326,562** | **33/33** | **3/3** |

[真实语料脚本](benchmark_real_skills.py) 默认在临时目录获取固定 commit，再通过 `git archive` 导出这三个目录；也可用 `--source-root` 指定已有上游 Git 仓库，但仍从固定 Git 对象导出，不采用工作区修改或未跟踪文件。每个 skill 在加载后立即删除源目录，再验证每跳完整 IR 和最终全部文件的路径、字节与权限。未执行上游脚本，未调用模型，也未安装目标框架。

```bash
python3 evaluation/benchmark_real_skills.py --cycles 10 --out evaluation/preservation/real-skills.json
```

[完整结果与逐文件 manifest](preservation/real-skills.json) 仅保存官方 URL、固定 commit、仓库相对路径、SHA-256、字节数、权限与指标；第三方源文档和资源没有收入本仓库。这组结果仍然检验归档恢复，不证明文档生成脚本或目标框架实际执行成功。

## SkillKit：实际源码执行结果

直接运行固定 commit 的 `packages/core/src/translator/index.ts:translateSkill`，即 CLI 使用的接口，没有复制或改写其实现。使用相同 11 文件 fixture 的 SKILL.md，分别测 LF 和 CRLF 两种行尾，转换到 4 个受支持的 agent 后再转回 Claude Code SKILL.md。完整记录包含所有 warnings、incompatible 信息及实际恢复文件。

| 被测能力 | SkillKit 支持路径上的结果 |
| --- | ---: |
| API 正反转换均返回 success | 8/8 |
| SKILL.md 原始字节完全恢复 | 0/8 |
| 原始 11 文件资源包完全恢复 | 0/8；每条输出仅 1 个 SKILL.md |
| LF 输入经 Codex 中转的常见 license、metadata、allowed-tools 与正文 | 保留 |
| CRLF 输入的原始 name 正确提取 | 0/4；观察到源 frontmatter 被当作正文保留 |

文本规范化和字段降级符合文本转换器的设计取舍。这里的 0/8 仅针对“完整资产、字节一致”这个更严格的需求，不能解释为 SkillKit 普遍无法完成 skill 转换。双方目标格式不同，因此这是一项**可恢复能力对照**，不是相同目标格式、相同语义执行路径上的质量排名。

原始数据：[skillkit.json](preservation/skillkit.json)。可检查 [LF Codex 恢复文件](preservation/skillkit-output/lf/codex/SKILL.md) 和 [CRLF Cursor 恢复文件](preservation/skillkit-output/crlf/cursor/SKILL.md)。复现入口：[compare_skillkit.mjs](compare_skillkit.mjs)。

```bash
mkdir -p out/comparison
git clone https://github.com/rohitg00/skillkit.git out/comparison/skillkit
git -C out/comparison/skillkit checkout d2e5c346f73325c326820efd3188dcf2b6eb704f
npm install --ignore-scripts --no-audit --no-fund --prefix out/comparison/harness yaml@2.8.1 zod@3.25.76 tsx@4.20.6
ln -s ../harness/node_modules out/comparison/skillkit/node_modules
python3 -c "from pathlib import Path; from evaluation.benchmark_preservation import make_fixture; make_fixture(Path('out/comparison/fixture'), 'bundle')"
out/comparison/harness/node_modules/.bin/tsx evaluation/compare_skillkit.mjs out/comparison/skillkit out/comparison/fixture evaluation/preservation/skillkit.json
```

这里运行了固定源码的 translator 模块，没有安装或运行 SkillKit 的完整 CLI、可选服务或生命周期脚本。Node、yaml、zod 和 tsx 版本记录在结果内；不需要模型或 API key。

## 可以据此说什么

有证据支持的定位是：**以源目录可删除、文件字节可校验、跨格式多跳可恢复为核心的转换器。** 在已核查并实际运行的 SkillKit 文本转换路径之外，本项目增加了完整源文件封装、完整 IR 运输和与原生输出绑定的损坏检测。它在这一明确的保真契约上具备实测差异。

尚不能声称“开源第一”或“所有框架执行无损”。3 个合成 fixture 和 3 个官方真实 skill 不能覆盖全部输入；本轮没有比较模型推理质量、性能、框架引擎执行或 SkillKit 的安装能力。空目录、时间戳、所有权和 ACL 不属于恢复契约；符号链接与特殊文件明确拒绝。后续新增语料或 native runtime 测试应单独报告，不能与 capsule 的字节相等率混为一个分数。
