# 迁移接口与保真契约

Python ≥3.10，转换器本身无强制第三方依赖。AI 迁移需要模型凭据；执行目标工程需要对应框架。规则转换路径为：

```text
skill / native definition → AgentIR → native projection + preservation capsule
```

## 公开 Python API

```python
from converter.emitters import EMITTERS
from converter.parsers import PARSERS
from converter.skill_loader import load_skill
from converter.skill_writer import write_skill
from converter.preservation import read_capsule, PreservationError

ir = load_skill("examples/agent-fullcycle-engineering")
EMITTERS["langchain"](ir, "out/langchain")
restored = PARSERS["langchain"]("out/langchain/agent.py")
write_skill(restored, "out/skill")
verified_ir, manifest = read_capsule("out/skill")
```

`read_capsule` 接受 `Path` 或路径字符串。输出必须是新目录或空目录。转换先在相邻临时目录生成，成功后发布；失败不会覆盖已有非空目录。相同 IR 与相同文件权限在同一平台上生成确定性产物，capsule 不记录生成时间或本机源目录。

`EMITTERS` / `PARSERS` 的键与 CLI 所列 11 个目标一致。模块级 `emit_<format>` / `parse_<format>` 函数保留为**低层原生接口**，用于独立格式验证；直接调用它们不提供完整 capsule 契约。

```python
# 原生产物已修改，明确从当前原生字段重新提取。
ir = PARSERS["langchain"]("out/langchain/agent.py", native_only=True)
# skill 同样支持显式原生读取。
ir = load_skill("out/skill", native_only=True)
```

默认读取发现 capsule 时必须校验，不会在校验失败后偷偷降级为原生读取。显式原生导入放弃旧 capsule 独有的信息，新的转换包只承诺保存这次导入所得的 IR 和资产。

## AI 语义迁移 API

`converter.ai_migration.migrate` 在规则解析得到的 IR 上执行模型分析、生成、独立验收和修复。模型客户端为标准库 HTTP 实现：

```python
import os
from pathlib import Path
from converter.ai_provider import ModelClient
from converter.ai_migration import migrate, MigrationFailed

client = ModelClient(
    provider="anthropic",
    model=os.environ["ANTHROPIC_MODEL"],
    api_key_env="ANTHROPIC_API_KEY",
)
ir = load_skill("examples/agent-fullcycle-engineering")
try:
    report = migrate(
        ir, "langchain", "out/ai-langchain", client,
        execute=True,
        python_executable=str(Path(".venv-runtime/bin/python").resolve()),
        max_repairs=3,
    )
except MigrationFailed as error:
    report = error.report
```

`execute=False` 只生成和静态检查，不会得到成功状态；默认不会发布未通过工程。`keep_failed=True` 可保留已生成但未通过的工程供检查。源资料不足而没有可实现计划时，只有 `MigrationFailed.report`，不会虚构代码。

核心参数：

| 参数 | 作用 |
| --- | --- |
| `execute` | 明确执行生成代码；默认 False |
| `python_executable` | 已安装真实目标依赖的运行解释器 |
| `max_repairs` | 首次生成之后允许的实现修复次数 |
| `timeout` | 单次执行的时间上限 |
| `runtime_command` | 用户提供的真实宿主验收 argv；不经 shell |
| `acceptance` | 额外冻结用例的 JSON 对象列表 |
| `source_root` | 第三方原生工程的源目录，用于静态收集实际实现及资源 |
| `context_chars` | 源及当前项目上下文上限，超限明确失败 |
| `progress` | 接收脱敏阶段事件的可选回调 |

分析计划与验收值在生成前冻结。实现阶段只返回允许的 `files` 变更，不能改写来源文件、验收期望、验证器或 `migration.json`。独立执行器接收输入并观察实际返回值，父进程将其与冻结期望比较；生成代码不会收到验收期望作为调用参数。

`validate_project` 的成功需要实际执行与原生验收。LangChain、Deep Agents、AutoGen AgentChat、CrewAI 和 CrewAI Skills 由独立适配器验证；其他格式需要用户提供真实宿主命令。该命令的退出状态是用户选择的验收边界，不能将空操作命令解释为引擎运行证明。

生成的工程包含真实工具模块、工作流模块、目标原生产物与 `migration.json`；保真 capsule 单独保存来源及完整性信息。模型推理调用、确定性注入模型的框架执行和资产完整性是三类不同证据。详细 CLI、冻结用例与状态定义见 [AI 迁移使用说明](docs/AI-MIGRATION.md)。

## AgentIR

`converter/ir.py` 是数据模型的权威实现。主要字段为 name、display_name、description、system_prompt、default_prompt、tools、knowledge、tasks、scripts、metadata，以及可选 `source_files`。

| 子结构 | 关键字段 |
| --- | --- |
| `ToolSpec` | name、description、input_schema、side_effects |
| `KnowledgeDoc` | filename（相对路径）、title、content、source_path |
| `TaskStep` | name、description、expected_output、agent |
| `source_files` | 相对路径 → `{data: base64, sha256: hex, mode: int}` |

`source_files` 为空时，旧 JSON 形状保持不变；非空时可通过 `AgentIR.to_json()` 独立运输源文件。`load_skill()` 捕获所选目录内的全部普通文件，排除根 `.agentskills-bridge/` 协议目录；原生知识提取覆盖递归 UTF-8 Markdown，其他文件仍按字节归档。路径不得为绝对路径、包含 `..`、反斜杠、盘符或保留协议目录。符号链接与特殊文件明确拒绝。

持久化的 IR 移除 `metadata.source_path` 和知识条目的本机 `source_path`；它们仅是本机定位信息。其余语义字段完整保留。工具契约与拓扑元数据被运输，不等于框架原生会执行它们。

## Preservation Capsule v1

```text
<output>/
  <native artifacts>
  .agentskills-bridge/
    ir.json
    manifest.json
```

manifest 包含 `schema_version: 1`、目标 `format`、`ir_sha256`，以及原生产物的完整文件集合（每项含 SHA-256 和 POSIX mode）。`ir.json` 中源文件的 base64 与其 SHA-256 也必须一致。

读取时检查协议版本、目标格式、IR 哈希、原生产物的文件集合/字节/权限，以及源文件路径与哈希。新增文件也视为状态变化。manifest 提供完整性检查，不是签名或来源认证。capsule 与原生产物必须一起复制；仅复制一个 Python 或 JSON 文件会失去完整恢复契约。

`read_capsule(root, expected_format=None)` 返回 `(AgentIR, manifest)`，格式/完整性错误抛 `PreservationError`。它不会执行被读取的 Python 或 shell 文件。

## 原始文件与合法编辑

未编辑 IR 的源 skill 逐字节恢复，包括 CRLF、未知 frontmatter、附件、空文件及 POSIX 文件权限。空目录、时间戳、owner、ACL 不在恢复范围。

原始 `source_files` 是来源快照。合法编辑活跃 IR 后，`skill`、`crewai-skills`、`deepagents` 的原生 skill 投影应用当前的 name/description/system_prompt、display/default、工具契约与知识文件。保留未编辑的扩展字段；删除的 Markdown 知识不在原生投影中复活。原始快照仍随 capsule 保存，表示来源，不替代活跃指令。工具契约通常写入 JSON `metadata.tools`；原始 metadata 为无法解释的 YAML 时用 `x-bridge-tools` 显式覆盖，避免删除未知 metadata。

## 新增格式

1. 实现原生 `emit_<fmt>(ir, out_dir) -> Path` 与 `parse_<fmt>(path) -> AgentIR`。
2. 在两侧注册表和 `TARGET_FORMATS` 中注册，CLI 使用同一格式集合。
3. 验证原生产物字段，再检查格式间的 capsule 与资源恢复。
4. 若加入 AI 迁移，在 `converter/ai_profiles.py` 提供真实框架约束；需要自动验收时增加独立原生适配器。
5. 在格式文档说明原生可表达字段、降级点与运行前需要的配置。

新增格式的验证必须分别覆盖原生映射和 capsule，不能只确认保存的 IR 被原样读回。
