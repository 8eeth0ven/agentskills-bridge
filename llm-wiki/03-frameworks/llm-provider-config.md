# 转换产物的 LLM 供应商配置(GLM / OpenAI / Claude)

本仓库转换产物(`agent.py` / flow.json / agents.yaml)默认按 **OpenAI 格式**生成模型调用。GLM(bigmodel)本身提供 OpenAI 兼容端点,接 GLM 只需换 `base_url` 一行;接 Claude 则有原生 Messages API 与官方 OpenAI 兼容层两条路。本章沉淀三家协议差异与各 target 产物的具体接线方法。

## 1. 三协议对照表

| 项 | GLM(bigmodel) | OpenAI | Claude(Anthropic) |
|------|----------------|--------|---------------------|
| 聊天端点 | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `https://api.openai.com/v1/chat/completions` | `https://api.anthropic.com/v1/messages` |
| 认证头 | `Authorization: Bearer <key>`(与 OpenAI 同) | `Authorization: Bearer sk-...` | `x-api-key: sk-ant-...` + **必带** `anthropic-version: 2023-06-01` |
| system 提示 | `messages` 内 `{"role":"system","content":...}` | `messages` 内 `{"role":"system","content":...}` | 独立顶层 `system` 参数(不在 messages 里) |
| `max_tokens` | 可省(服务端给默认值) | 可省(服务端给默认值) | **必填**,缺失直接报 400 |
| 响应取文本 | `resp.choices[0].message.content`(str) | `resp.choices[0].message.content`(str) | `resp.content[0].text`(content 是块数组,文本块 type=`text`) |
| API key 格式 | `id.secret`(`32位hex.密文` 两段式) | `sk-...` | `sk-ant-...` |
| 环境变量 | 无官方约定(社区常见 `ZHIPUAI_API_KEY`;OpenAI 兼容层下也有人直接用 `OPENAI_API_KEY`) | `OPENAI_API_KEY`(官方 SDK 默认读) | `ANTHROPIC_API_KEY`(官方 SDK 默认读) |

关键差异只有三条:Claude 的**认证头不同**(x-api-key 而非 Bearer)、**system 是顶层参数**、**max_tokens 必填**;响应结构从「单个字符串」变成「块数组」。GLM 与 OpenAI 在 chat/completions 层面请求/响应结构一致,差异只在域名与 key 格式。

## 2. curl 最小示例

### GLM(glm-4.6)

```bash
curl https://open.bigmodel.cn/api/paas/v4/chat/completions \
  -H "Authorization: Bearer $GLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.6",
    "messages": [
      {"role": "system", "content": "你是一个严谨的助手。"},
      {"role": "user", "content": "一句话解释什么是 agent"}
    ]
  }'
```

### OpenAI(gpt-4o)

```bash
curl https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "system", "content": "你是一个严谨的助手。"},
      {"role": "user", "content": "一句话解释什么是 agent"}
    ]
  }'
```

### Claude(claude-sonnet-4-5)

注意三点:`x-api-key` 头、`anthropic-version: 2023-06-01` 头、`max_tokens` 必填;system 走顶层参数。

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 1024,
    "system": "你是一个严谨的助手。",
    "messages": [
      {"role": "user", "content": "一句话解释什么是 agent"}
    ]
  }'
```

## 3. Python SDK 示例

### GLM:用 openai SDK 换 base_url

GLM v4 端点 OpenAI 兼容,`openai` 官方 SDK 直接可用,只换 `base_url`:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["GLM_API_KEY"],                # key 形如 id.secret
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)
resp = client.chat.completions.create(
    model="glm-4.6",
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.choices[0].message.content)
```

langchain 侧同理,`ChatOpenAI` 换两个参数:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="glm-4.6",
    api_key=os.environ["GLM_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)
```

### Claude:原生 anthropic SDK

`Anthropic()` 自动读 `ANTHROPIC_API_KEY`;system 是独立参数;`max_tokens` 必填:

```python
import anthropic

client = anthropic.Anthropic()  # 自动读 ANTHROPIC_API_KEY
resp = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    system="你是一个严谨的助手。",          # 独立顶层参数,不在 messages 里
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.content[0].text)                # content 是块数组,取第一个文本块
```

### Claude:官方 OpenAI 兼容层

Anthropic 官方提供 OpenAI 兼容端点,`openai` SDK 换 `base_url` 即可(认证走 Bearer,`anthropic-version` 由兼容层处理):

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    base_url="https://api.anthropic.com/v1/",
)
resp = client.chat.completions.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,                        # 兼容层下仍建议显式传,Claude 侧必填
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.choices[0].message.content)
```

## 4. 对本项目产物的接线指南

转换产物默认写 OpenAI 格式,接 GLM 的统一思路:**模型客户端不动,换 key + base_url**。逐 target 如下。

### 重要实测发现:GLM 有两条协议路径,免费档模型不同(2026-10-11 实测)

| 路径 | base_url | 认证 | 免费档模型 | 说明 |
|---|---|---|---|---|
| OpenAI 兼容 | `https://open.bigmodel.cn/api/paas/v4/` | `Authorization: Bearer` | **glm-4-flash** | glm-5.3-flash / flashx 在此路径报 1113(需资源包) |
| **Anthropic 兼容** | `https://open.bigmodel.cn/api/anthropic` | `x-api-key` + `anthropic-version: 2023-06-01` | **glm-5.3-flash** | 完整 Claude Messages 协议(顶层 system、必填 max_tokens、thinking+text 块);glm-5.3-flash 默认输出 thinking 块,max_tokens 建议 ≥2048 |

即:**同一把 GLM key,glm-5.3-flash 要走 Anthropic 协议路径**。这正好复用 Claude 生态的全部客户端(langchain `ChatAnthropic`、autogen `AnthropicChatCompletionClient`、litellm `anthropic/` 前缀),换 base_url 即可。另实测注意:经 v4 路径传「system 为 content-blocks 数组且 ~15k 长文」时,system 内容可能不完整送达模型(langchain 新版默认 blocks 格式,长 SKILL.md 正文会触发)——建议用 ChatOpenAI 时把 system 拍平为纯字符串,或改走 Anthropic 路径。

### langchain / deepagents / autogen 产物

三者的模型客户端都是 OpenAI 兼容层,同参接入:

```python
# langchain / deepagents 产物
llm = ChatOpenAI(
    model="glm-4.6",
    api_key=os.environ["GLM_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)

# autogen(AG2)产物:用 OpenAIChatCompletionClient,同样的两个参数
from autogen_ext.models.openai import OpenAIChatCompletionClient
client = OpenAIChatCompletionClient(
    model="glm-4.6",
    api_key=os.environ["GLM_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)
```

glm-5.3-flash 则改走 Anthropic 路径(langchain/deepagents 用 `ChatAnthropic(model="glm-5.3-flash", api_key=..., base_url="https://open.bigmodel.cn/api/anthropic", max_tokens=2048)`;autogen 用 `AnthropicChatCompletionClient` 同参)。

### crewai 产物

CrewAI 的 `LLM` 走 litellm,模型名要加 `openai/` 前缀表示「经 OpenAI 兼容层调用」,端点用 `api_base`:

```python
from crewai import LLM

llm = LLM(
    model="openai/glm-4.6",   # litellm 前缀 openai/ = 按 OpenAI 兼容协议调用
    api_key=os.environ["GLM_API_KEY"],
    api_base="https://open.bigmodel.cn/api/paas/v4",
)

# glm-5.3-flash 走 GLM 的 Anthropic 兼容路径:前缀 anthropic/,api_base 指到 /api/anthropic
llm53 = LLM(
    model="anthropic/glm-5.3-flash",
    api_key=os.environ["GLM_API_KEY"],
    api_base="https://open.bigmodel.cn/api/anthropic",
    max_tokens=2048,
)
```

### langflow 产物

langflow 的 LanguageModelComponent 目前 provider 下拉**没有 GLM 选项**。两条路:

1. **选 OpenAI provider + 覆盖 base_url**:provider 选 `OpenAI`,api_key 填 GLM key,base_url 字段填 `https://open.bigmodel.cn/api/paas/v4`,model 名填 `glm-4.6`。flow.json 里就是 LanguageModelComponent 节点的这三个字段值,parser/emitter 不需要改动。
2. **Custom Component**:自己写一个组件包装 GLM SDK,适合需要 GLM 专有参数(如 `thinking`、工具调用细节)的场景。

### 模型选型一行表

| 模型 | 定位 |
|------|------|
| `glm-4.6` | GLM 旗舰,转换产物默认选型 |
| `glm-4-flash` | GLM 免费档,适合跑通管线与批量测试 |
| `claude-sonnet-4-5` | Claude 主力,长上下文与 agent 任务 |
| `claude-haiku-4-5` | Claude 便宜快档,适合高频轻量调用 |

## 5. 密钥纪律

- key 只经**环境变量 / shell 配置(`~/.zshrc`)/ `.env`(须在 `.gitignore`)** 注入,任何情况不写进代码、不提交 git。
- 仓库内文档、示例代码一律用 `os.environ["GLM_API_KEY"]` 形式占位。
- 本仓库 runtime 测试统一读 **`GLM_API_KEY`** 环境变量;Claude 侧示例读 `ANTHROPIC_API_KEY`、OpenAI 侧读 `OPENAI_API_KEY`。
- GLM key 为 `id.secret` 两段式,泄露任一段都不构成防护,按整体敏感对待。

---

*协议信息核实于 2026-10:Anthropic Messages API 版本头 `anthropic-version: 2023-06-01`、bigmodel v4 端点(`https://open.bigmodel.cn/api/paas/v4`)、Claude 官方 OpenAI 兼容层(`https://api.anthropic.com/v1/`)。模型名与免费档政策以各官方文档最新版为准。*
