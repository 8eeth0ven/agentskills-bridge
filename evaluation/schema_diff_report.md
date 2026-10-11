# schema 深度一致性校验报告(三产物 vs 官方真实 schema)

运行日期:2026-10-11
校验工具:`python3 evaluation/schema_diff.py [--json <path>]`(标准库,退出码 0 = 必需级差异清零)

## 0. 官方样本与依据来源

| 格式 | 官方真实样本 | 关键源码依据 |
|---|---|---|
| langflow | `src/lfx/tests/fixtures/starter_flows/v1.9.0/basic_prompting.json`(本地 clone `/tmp/langflow-repo`,main@1.12.5,与 1.6 starter 同构) | `src/lfx/src/lfx/graph/graph/base.py:2941-2951`(运行时逐键下标访问);`src/lfx/src/lfx/graph/vertex/base.py:250-270` |
| openai | Codex `agents/openai.yaml` 三段结构(developers.openai.com/codex/skills) | `/tmp/codex-src/codex-rs/ext/skills/src/loader/metadata.rs`(SkillMetadataFile);`codex-rs/skills/src/interface.rs`(长度上限) |
| claude-subagent | code.claude.com/docs/en/sub-agents(frontmatter 表 + skip 条件) | `/tmp/research/subagents-doc.txt:433/471/437`(name 约束)、`:437`(model 值域) |

键分级标准(langflow):
- **REQUIRED(导入/运行时必需)**:`node{id,position,type,data}` + `data{type,id,node}` + `data.node{base_classes,field_order,outputs,template._type}` + 字段 dict `{name,type,value}` + 边 `{source,target,sourceHandle,targetHandle}`——后端 `_create_vertex` 逐键下标读取,缺即 KeyError/ValueError。
- **UI-META(官方导出双写)**:`data.display_name` / `data.description`——画布节点标题显示,运行时非必需但对齐官方导出。
- **FUNCTIONAL(功能性一致键)**:`data.node.custom_fields`(动态输入口注册表,官方四节点一致携带,无动态字段时为 `{}`)。
- **DECOR(装饰性,不补)**:`measured/width/height/dragging/selected/beta/edited/pinned/lf_version/documentation/metadata/output_types/legacy/conditional_paths/tool_mode` 等——测量值/编辑器状态,导入后自动重建。

## 1. langflow:flow.json

### 差异(前 → 后)

| 范围 | 键 | 级别 | 前 | 后 | 处理 |
|---|---|---|---|---|---|
| ChatInput/Prompt `data` | `display_name`,`description` | UI-META | 缺 | 补 | ✅ 修 |
| 四节点 `data.node` | `custom_fields`(ChatInput/LLM/ChatOutput 缺) | FUNCTIONAL | 3 节点缺 | 补 `{}`(Prompt 保持 `{"template":["message"]}`) | ✅ 修 |
| node 顶层 | `measured`/`height` | DECOR | 缺 | 缺 | 按约定不补 |
| data.node | `beta/edited/pinned/lf_version/...` ×9 | DECOR | 缺 | 缺 | 不补(保持产物精简) |
| 顶层 | `last_tested_version` | DECOR | 缺 | 缺 | 不补 |
| node 顶层 | `width`/`positionAbsolute` | 我们多出 | 有 | 有 | 无害保留(reactflow 容忍) |

**修前必需级(REQUIRED)即已为 0**——原 emitter 的 node 顶层 `id/position/type/data`、`data.type/data.id/data.node`、`data.node` 四必需键、`template._type="Component"`、字段 dict `name/display_name/type/value/show/advanced/...` 核心 14 键、outputs `{name,method,types,selected}`、边 9 键(含 œ 双写 handle)全部齐备,与官方 fixture 逐键一致。

### 修改(`converter/emitters/langflow.py::_make_node`)

- `data` 层新增 `description`、`display_name`(值取自节点元数据,对齐官方导出双写);
- `data.node.custom_fields` 改为无条件携带(缺省 `{}`,Prompt 传 `{"template": ["message"]}`)。

## 2. openai:agents/openai.yaml

### 差异(前 → 后)

| 项 | 级别 | 前 | 后 |
|---|---|---|---|
| `interface.display_name/short_description/default_prompt` 三字段存在性 + str 类型 | REQUIRED | ✓ 一致(与调研确认的三字段完全一致) | ✓ |
| 三字段长度上限(display_name ≤64,short_description/default_prompt ≤1024) | REQUIRED(值约束) | 无保险(corpus 恰未超限,schema_diff 未报) | ✅ emitter 加 `_clamp` 截断(Codex `resolve_str` 按 `chars().count()` 计长,超长整字段被忽略) |
| `policy` 段 | 可选 | 缺失——合法 | 不产出(源 IR 无对应信息) |
| `dependencies` 段 | 可选 | 缺失——合法 | 不产出 |
| `x-source-skill` 顶层键 | 未知键判定 | **不会**被严格 schema 拒:Codex `SkillMetadataFile` 为 serde Deserialize 且无 `deny_unknown_fields`,未知顶层键宽容忽略;metadata 解析本身 fail-open(失败仅 warn,不阻塞 SKILL.md)。**置信度:高(源码直读)** | 维持 |
| 其余客户端 | — | 不读取 `agents/openai.yaml`,零影响 | — |

修改(`converter/emitters/openai_agents.py::_openai_yaml`):三个 interface 字段写出前过 `_clamp`(64/1024/1024),避免源 IR 值超长时被 Codex 静默丢弃。

## 3. claude-subagent:.claude/agents/*.md

frontmatter 硬约束逐条核(前 → 后):

| 约束 | 前 | 后 |
|---|---|---|
| `---` 是文件第一行 | ✓ | ✓ |
| `name` 必需、非空 | ✓(兜底 "agent") | ✓ |
| name ≤256 / 无 `:` / 不以 `-` 开头 | ✓ | ✓ |
| name 无空白(identifier slug 语义,官方示例 code-reviewer/reviewer-v2) | **未清洗**(空格/制表会原样写出) | ✅ `_agent_name` 增加 `re.sub(r"\s+","-")`,空白归一为连字符 |
| `description` 必需非空 | ✓(兜底首行) | ✓ |
| `tools` YAML 列表格式 | ✓(列表项双引号标量) | ✓(schema_diff 首轮曾因自身解析 bug 误报"列表含空项",已修校验器) |
| `model` 值域(sonnet/opus/haiku/fable/inherit/claude-* 完整 id) | **未过滤**(源 IR metadata.model 可能为 gpt-4.1 等跨框架值) | ✅ `_model_value` 值域过滤,非法回退 `sonnet`(实测 gpt-4.1 → sonnet) |
| `knowledge:` 扩展键 | 标注:**Claude Code 未知键容忍性未验证**(官方文档未定义该键;按"未知字段被忽略"的通用解析行为推断无害,YAML 结构合法不会触发解析失败,但未实测。置信度:低) | 维持 |

修改(`converter/emitters/claude_subagent.py`):`_agent_name` 空白清洗;`_model_value` 值域过滤。

## 4. 回归

- `python3 evaluation/schema_diff.py` → **必需级差异合计 0,退出码 0**(前:1 项必需级 + 4 项 UI-META/FUNCTIONAL)。
- `python3 -m unittest discover tests` → **64 tests OK**(TestLangflowV112 在内;首轮一次 29-skip 为并行线程写 `__pycache__` 的瞬时导入竞争,复跑两次均稳定全绿,与本改动无关)。
- `python3 evaluation/run_eval.py` → **全局均值 1.0000**(F_name/F_desc/F_prompt/F_know_q/F_know_c/V_format 全 1.0,24/24 roundtrip ok);langflow 链 V_format=1.0000、F 五项=1.0000;新增键未影响 langflow parser(其全 `.get` 兜底)。

## 5. 文件清单

- 新增:`evaluation/schema_diff.py`
- 修改:`converter/emitters/langflow.py`、`converter/emitters/openai_agents.py`、`converter/emitters/claude_subagent.py`
- 快照:`/tmp/schema/diff_before.json`、`/tmp/schema/diff_after.json`
