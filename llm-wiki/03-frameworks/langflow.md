# Langflow

Langflow 是可视化 agent 构建器,一个 agent 即一张流程图,以 `flow.json` 导入导出。核心结构:顶层 `id`/`name`/`data`(nodes/edges/viewport);每个节点带 `id`/`type`/`position`/`data.node.template`;边用 `source`/`target`/handle 连接组件端口,handle 为 JSON 字符串且**字符串内引号替换为 `œ`(U+0153)**。

## 最小可用示例

经典四组件链(官方 Basic Prompting starter 同款结构;1.5/1.6/1.9 fixture 与 1.12 API 读回样例实测一致,2026-10-11 对 langflow 1.12.5 源码核实):ChatInput(用户消息)与 Prompt(系统提示)分别接入 LLM 的 `input_value` 与 `system_message`,LLM 输出接 ChatOutput。4 节点 3 边;edge 的 `sourceHandle`/`targetHandle` 是引号替换为 `œ` 的 JSON 字符串,边内另双写结构化 `data` 对象(官方导出双写,建议跟随):

```json
{
  "id": "3f9c2e8a-1b4d-4f6e-9a2b-7c8d5e0f1a2b",
  "name": "Minimal Agent Flow",
  "description": "ChatInput + Prompt(系统提示) + LLM + ChatOutput",
  "data": {
    "nodes": [
      {
        "id": "ChatInput-b6UCc",
        "type": "genericNode",
        "position": {"x": 0, "y": 220},
        "width": 384,
        "height": 172,
        "selected": false,
        "dragging": false,
        "data": {
          "id": "ChatInput-b6UCc",
          "type": "ChatInput",
          "node": {
            "template": {
              "_type": "Component",
              "input_value": {
                "name": "input_value",
                "display_name": "Message",
                "type": "str",
                "show": true,
                "multiline": true,
                "value": "",
                "required": false
              }
            },
            "description": "Get chat inputs from the Playground.",
            "display_name": "Chat Input",
            "base_classes": ["Message"]
          }
        }
      },
      {
        "id": "Prompt-t2oaK",
        "type": "genericNode",
        "position": {"x": 480, "y": 60},
        "width": 384,
        "height": 172,
        "selected": false,
        "dragging": false,
        "data": {
          "id": "Prompt-t2oaK",
          "type": "Prompt",
          "node": {
            "template": {
              "_type": "Component",
              "template": {
                "name": "template",
                "display_name": "Template",
                "type": "prompt",
                "show": true,
                "trace_as_input": true,
                "value": "你是一名技术笔记助手。只回答与笔记主题相关的问题,输出 Markdown。",
                "required": false
              }
            },
            "description": "Create a prompt template with dynamic variables.",
            "display_name": "Prompt",
            "base_classes": ["Message"]
          }
        }
      },
      {
        "id": "LanguageModelComponent-FLeYF",
        "type": "genericNode",
        "position": {"x": 960, "y": 220},
        "width": 384,
        "height": 300,
        "selected": false,
        "dragging": false,
        "data": {
          "id": "LanguageModelComponent-FLeYF",
          "type": "LanguageModelComponent",
          "node": {
            "template": {
              "_type": "Component",
              "provider": {"name": "provider", "display_name": "Provider", "type": "str", "value": "OpenAI"},
              "model_name": {"name": "model_name", "display_name": "Model Name Override", "type": "str", "value": "gpt-4o-mini"},
              "api_key": {"name": "api_key", "display_name": "API Key", "type": "str", "value": "OPENAI_API_KEY", "load_from_db": true},
              "input_value": {"name": "input_value", "display_name": "Input", "type": "str", "input_types": ["Message"], "show": true, "value": ""},
              "system_message": {"name": "system_message", "display_name": "System Message", "type": "str", "input_types": ["Message"], "multiline": true, "show": true, "value": ""},
              "temperature": {"name": "temperature", "display_name": "Temperature", "type": "float", "value": 0.1},
              "max_tokens": {"name": "max_tokens", "display_name": "Max Tokens", "type": "int", "value": 512}
            },
            "description": "Runs a language model given a specified provider.",
            "display_name": "Language Model",
            "base_classes": ["Message", "Text"]
          }
        }
      },
      {
        "id": "ChatOutput-yK0AU",
        "type": "genericNode",
        "position": {"x": 1440, "y": 220},
        "width": 384,
        "height": 172,
        "selected": false,
        "dragging": false,
        "data": {
          "id": "ChatOutput-yK0AU",
          "type": "ChatOutput",
          "node": {
            "template": {
              "_type": "Component",
              "input_value": {
                "name": "input_value",
                "display_name": "Text",
                "type": "str",
                "input_types": ["Message", "Data", "JSON"],
                "show": true,
                "value": ""
              }
            },
            "description": "Display a chat message in the Playground.",
            "display_name": "Chat Output",
            "base_classes": ["Message"]
          }
        }
      }
    ],
    "edges": [
      {
        "id": "reactflow__edge-ChatInput-b6UCc-msg-LM-input",
        "source": "ChatInput-b6UCc",
        "sourceHandle": "{œdataTypeœ: œChatInputœ, œidœ: œChatInput-b6UCcœ, œnameœ: œmessageœ, œoutput_typesœ: [œMessageœ]}",
        "target": "LanguageModelComponent-FLeYF",
        "targetHandle": "{œfieldNameœ: œinput_valueœ, œidœ: œLanguageModelComponent-FLeYFœ, œinputTypesœ: [œMessageœ], œtypeœ: œstrœ}",
        "data": {
          "sourceHandle": {"dataType": "ChatInput", "id": "ChatInput-b6UCc", "name": "message", "output_types": ["Message"]},
          "targetHandle": {"fieldName": "input_value", "id": "LanguageModelComponent-FLeYF", "inputTypes": ["Message"], "type": "str"}
        },
        "animated": false
      },
      {
        "id": "reactflow__edge-Prompt-t2oaK-prompt-LM-sys",
        "source": "Prompt-t2oaK",
        "sourceHandle": "{œdataTypeœ: œPromptœ, œidœ: œPrompt-t2oaKœ, œnameœ: œpromptœ, œoutput_typesœ: [œMessageœ]}",
        "target": "LanguageModelComponent-FLeYF",
        "targetHandle": "{œfieldNameœ: œsystem_messageœ, œidœ: œLanguageModelComponent-FLeYFœ, œinputTypesœ: [œMessageœ], œtypeœ: œstrœ}",
        "data": {
          "sourceHandle": {"dataType": "Prompt", "id": "Prompt-t2oaK", "name": "prompt", "output_types": ["Message"]},
          "targetHandle": {"fieldName": "system_message", "id": "LanguageModelComponent-FLeYF", "inputTypes": ["Message"], "type": "str"}
        },
        "animated": false
      },
      {
        "id": "reactflow__edge-LM-text_output-ChatOutput-input",
        "source": "LanguageModelComponent-FLeYF",
        "sourceHandle": "{œdataTypeœ: œLanguageModelComponentœ, œidœ: œLanguageModelComponent-FLeYFœ, œnameœ: œtext_outputœ, œoutput_typesœ: [œMessageœ]}",
        "target": "ChatOutput-yK0AU",
        "targetHandle": "{œfieldNameœ: œinput_valueœ, œidœ: œChatOutput-yK0AUœ, œinputTypesœ: [œMessageœ], œtypeœ: œstrœ}",
        "data": {
          "sourceHandle": {"dataType": "LanguageModelComponent", "id": "LanguageModelComponent-FLeYF", "name": "text_output", "output_types": ["Message"]},
          "targetHandle": {"fieldName": "input_value", "id": "ChatOutput-yK0AU", "inputTypes": ["Message"], "type": "str"}
        },
        "animated": false
      }
    ],
    "viewport": {"x": 0, "y": 0, "zoom": 0.9}
  }
}
```

导入方式:

| 途径 | 操作 |
|---|---|
| UI Import | Langflow 界面 → Flows → New Flow → Import JSON,粘贴或上传 flow.json |
| API | `POST /api/v1/flows`,Header `x-api-key: <LANGFLOW_API_KEY>`,body `{"name": ..., "data": <flow.json 的 data 字段>}` |
| 本地启动 | `langflow run --env-file .env`(默认 7860 端口),再走上面两种导入;导出用 UI 的 Export JSON 或 `GET /api/v1/flows/{id}` |

## 字段说明

顶层:

| 字段 | 说明 |
|---|---|
| `id` | flow 的 UUID,导入时缺省会自动生成 |
| `name` | flow 名称(UI 列表显示) |
| `description` | 描述(可选) |
| `endpoint_name` / `is_component` / `last_tested_version` / `tags` | 导出附带的元数据(可选) |
| `data.nodes` / `data.edges` / `data.viewport` | 节点、边、画布视口(仅显示用) |

节点结构:

| 字段 | 说明 |
|---|---|
| `id` | `组件名-5位随机后缀`,如 `ChatInput-b6UCc`,边按此引用 |
| `type` | 1.9 统一为 `"genericNode"`(另 `"noteNode"` 备注节点);真实组件类型在 `data.type`。旧版(约 ≤1.4)直接把组件类型写在顶层 `type` |
| `position` | `{x, y}` 画布坐标 |
| `data.type` | 组件类型,**PascalCase 短类名、无命名空间**:`ChatInput` / `Prompt` / `LanguageModelComponent`(LLM,1.4.2 起统一各厂商,旧名 `OpenAIModel`/`OpenAI`;字段 `model_name`/`provider`/`api_key`)/ `ChatOutput` / `Agent` 等。不存在 `author/slug`(如 `eiyooooo/chat_input`)或 snake_case 形态的 type,那是 Langflow Store 的组件标识,写进 data.type 无法解析 |
| `data.node.template` | 组件参数表:字段名 → `{name, display_name, type, value, show, required, multiline, input_types}`;`value` 是实际生效值 |
| `data.node.display_name` / `description` / `base_classes` | 显示名、说明、输出类型 |

关键组件的端口:

| 组件 | 输出 handle | 输入 handle |
|---|---|---|
| ChatInput | `message`(用户消息) | — |
| Prompt | `prompt`(系统提示消息) | `template`(可接收变量注入) |
| LanguageModelComponent(LLM) | `text_output`、`model_output` | `input_value`(用户输入)、`system_message`(系统提示) |
| Agent | `response`、`structured_response` | `system_prompt`(display "Agent Instructions")、`tools`、`model`、`input_value` |
| ChatOutput | — | `input_value` |

系统提示接向区分(源码 `src/lfx/src/lfx/components/models_and_agents/`,2026-10-11 核实):Prompt → **LanguageModelComponent** 时 targetHandle `fieldName=system_message`;Prompt → **Agent** 时才是 `fieldName=system_prompt`(更老的 LLMChain 用 `prompt` handle)。

边结构:

| 字段 | 说明 |
|---|---|
| `source` / `target` | 节点 id |
| `sourceHandle` | JSON 字符串,**字符串内引号替换为 `œ`(U+0153)**:`{œdataTypeœ: ..., œidœ: ..., œnameœ: <输出 handle 名>, œoutput_typesœ: [...]}`;前端 `customStringify(json).replace(/"/g, "œ")` 生成、后端解析时 `replace("œ", '"')` 还原;旧版为简单字符串如 `"message"` |
| `targetHandle` | 同上 œ 形态:`{œfieldNameœ: <输入字段名>, œidœ: ..., œinputTypesœ: [...], œtypeœ: ...}` |
| `data` | 边内双写的结构化对象:`{"sourceHandle": {...}, "targetHandle": {...}}`(正常引号的 JSON 对象;官方导出双写,稳妥跟随) |
| `id` / `animated` | reactflow 边 id(可任意)、动画开关 |

## Knowledge 上传(1.12)

Langflow 1.12 起 Knowledge Bases 与 flow 解耦、按用户管理(2026-10-11 调研,langflow 1.12.5 源码 `src/backend/base/langflow/api/v1/knowledge_bases.py` 核实;REST `include_in_schema=False`,主要供 UI 使用)。正确姿势两步走 + 组件挂载:

1. `POST /api/v1/knowledge_bases`:JSON body 建 KB——`name`(空格转下划线、最短 3 字符)、embedding 配置、`backend_type`/`backend_config`;
2. `POST /api/v1/knowledge_bases/{kb_name}/ingest`:**multipart 文件直传**(`files[]`、`source_name`、`chunk_size` 默认 1000、`chunk_overlap` 默认 200、`separator`、`metadata`/`per_file_metadata` JSON 串、`column_config`);
3. flow 里放 `Knowledge` 组件(mode=Retrieve,`knowledge_base` 下拉选中该 KB)接 Agent。

另有 `GET .../knowledge_bases`(列表)、`GET .../{kb_name}`、`GET .../{kb_name}/chunks`、`DELETE .../{kb_name}`。老式 `KnowledgeIngestion`(≤1.6 fixture 可见)与 flow 内 VectorStore 组件已过时(1.12 起多数 vector store 组件移入可选 bundles)。轻量替代:ChatInput 的 `files` 字段(FileInput,is_list,支持 txt/md/pdf/docx 等)。

**1.12.5 无 SKILL.md 运行时支持**:全仓库 grep 无 Agent Skills 产品功能(仓库内 `.agents/skills/` 仅为贡献者开发用);等价能力为 **Agent 组件**(多 agent 互连、Human-in-the-Loop gated tools、Edit Tool Actions)、**FlowTool**(display "Flow as Tool",把整个 flow 变成 agent 工具)与 **MCP**(Langflow 自身可作 MCP server 暴露 flows,`MCP Tools` 组件接外部 server;另有 A2A)。

## 与 AgentIR 的映射

| AgentIR 字段 | Langflow 落点 |
|---|---|
| `system_prompt` | Prompt 节点 `data.node.template.template.value`(1.9;旧版 1.0–1.4 在 `data.node.template.system_prompt.value`)或 LLM 节点 `system_message` 字段的 `value` |
| `name` / `display_name` | 顶层 `name` |
| `description` | 顶层 `description` |
| `knowledge` | 不进 flow.json;同目录 `knowledge/` 拷贝 + README 说明导入方式(1.12 亦可走 KB ingest API,见上文 Knowledge 上传一节) |
| `tools` | LLM 形态无工具概念 → 丢失;若目标是 `Agent` 组件(输入口 system_prompt/tools/model),需在 UI 里手工挂 Tool 组件,emit 不生成 |
| `default_prompt` / `tasks` / `scripts` / `metadata` | 无对应,README 记录 |

反向 `parse_langflow(flow_file)`:找 `data.type == "Prompt"` 的节点,读 `data.node.template.template.value`(或旧版 `system_prompt.value`)作 system_prompt;`metadata={"source_format": "langflow"}`。

## 转换注意事项

1. **版本差异最大的一章**:约 1.0–1.4 与 1.9 的节点包装(`type: 组件名` vs `genericNode` + `data.type`)、handle 形态(简单字符串 vs JSON 字符串)、系统提示字段(`system_prompt` vs `template.value`)都不一样。emit 按目标版本写;parse 必须两套都兼容,按存在性探测。
2. **静默断边**:导入时 Langflow 会用安装版本的组件 schema 补全缺失字段,但组件名或 handle 对不上时不报错、只是边失效。handle 字符串的 `œ` 转义必须逐字符精确(后端按 `replace("œ", '"')` 解析),误写成普通引号形态即断边。精简版 JSON(如上例)能导入,但建议在 UI 里打开确认连线完整。
3. **两个系统提示位置**:Prompt 组件和 LLM 的 `system_message` 都能放系统提示,人工编辑常两者混用;parse 时优先 Prompt 节点,查不到再读 LLM 节点字段。
4. **知识文件必须在 flow.json 之外**:`flow.json` 无法内嵌文档内容,转换产物必须连同 `knowledge/` 目录一起交付,否则 agent 行为退化成裸 prompt;1.12 的正式路径是先建 Knowledge Base 再 multipart ingest(见上文),或用 ChatInput 的 `files` 字段接收文件。
5. **布局字段尽量保留**:`position`/`width`/`height` 缺省时节点会堆叠在原点,不影响运行但不可用;`viewport` 纯显示,可丢。
6. **带工具的形态不生成**:Agent 组件 + Tool 组件的连线结构复杂且依赖具体组件,AgentIR 的 ToolSpec 没有组件实现,emit 到 LLM 形态时工具信息丢失,需人工在 UI 里补。
