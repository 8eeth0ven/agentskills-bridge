"""CrewAI emitter:AgentIR -> CrewAI 项目配置(手写 YAML,不依赖 pyyaml)。

产出:
    <out>/config/agents.yaml   agent 定义(role/goal/backstory/verbose:false)
    <out>/config/tasks.yaml    单任务(description 附知识路由说明 / expected_output / agent)
    <out>/knowledge/*.md       知识文档按 filename 拷贝
    <out>/README.md            如何放入 CrewAI 项目并 crewai run

多行值一律用 `>` 折叠块标量生成:内容行缩进 4 空格、每行后跟换行,
文本含 YAML 特殊字符也安全(整段在块标量内);空文本退化为 ""。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR

EXPECTED_OUTPUT = "结构化的最终回答,必要时引用 knowledge 文档"


def emit_crewai(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 CrewAI 配置目录,返回 out_dir。"""
    out = Path(out_dir)
    (out / "config").mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    (out / "config" / "agents.yaml").write_text(_agents_yaml(ir), encoding="utf-8")
    (out / "config" / "tasks.yaml").write_text(_tasks_yaml(ir), encoding="utf-8")
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


# ---------- YAML 生成(手写,不经 pyyaml) ----------

def _folded_entry(key: str, value: str, indent: str = "  ") -> str:
    """生成 `key: |` 字面块标量条目;空文本退化为 `key: \"\"`。

    用 `|`(literal)而非 `>`(folded):markdown 正文(列表/代码块/标题)
    的换行有语义,folded 会把单换行折叠为空格,roundtrip 后结构被破坏
    (评测 F_prompt: crewai S3_min 曾因此跌至 0.356)。
    """
    if not value or not value.strip():
        return f'{indent}{key}: ""\n'
    out = [f"{indent}{key}: |"]
    for line in value.rstrip("\n").split("\n"):
        out.append(f"{indent}  {line}" if line.strip() else "")
    return "\n".join(out) + "\n"


def _agents_yaml(ir: AgentIR) -> str:
    parts = [f"{ir.name}:\n"]
    parts.append("  x-agentskills-bridge: true\n")
    parts.append(_folded_entry("role", ir.title()))
    parts.append(_folded_entry("goal", ir.description))
    # backstory 必须承载完整 system_prompt:它是 crewai 反向链唯一 prompt
    # 载体,截断会导致 roundtrip 正文丢失(评测 F_prompt=0.408 的根因)。
    parts.append(_folded_entry("backstory", ir.system_prompt.strip()))
    parts.append("  verbose: false\n")
    return "".join(parts)


def _tasks_yaml(ir: AgentIR) -> str:
    description = "\n\n".join(
        p for p in (ir.description.strip(), _knowledge_routing(ir)) if p
    )
    parts = [f"{ir.name}_task:\n"]
    parts.append(_folded_entry("description", description))
    parts.append(_folded_entry("expected_output", EXPECTED_OUTPUT))
    parts.append(f"  agent: {ir.name}\n")
    return "".join(parts)


def _knowledge_routing(ir: AgentIR) -> str:
    names = [d.title or _safe_filename(d.filename) for d in ir.knowledge if _safe_filename(d.filename)]
    if names:
        return (
            "知识路由:回答前优先检索随附 knowledge/ 目录中的参考文档"
            f"({', '.join(n for n in names if n)});相关内容以文档为准并引用,"
            "文档未覆盖的部分再基于通用知识作答并说明来源。"
        )
    return "知识路由:本任务未附带 knowledge/ 参考文档,直接基于通用知识作答。"


# ---------- 知识文档拷贝 ----------

def _safe_filename(filename: str) -> Optional[str]:
    """过滤非法路径名:为空、. / ..、含 / 或 \\ 或 .. 的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _write_knowledge(ir: AgentIR, out: Path) -> List[str]:
    written: List[str] = []
    for doc in ir.knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        kdir = out / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(doc.content or "", encoding="utf-8")
        written.append(name)
    return written


# ---------- README ----------

def _readme(ir: AgentIR) -> str:
    docs = [d for d in ir.knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 agent 未附带知识文档)"
    return f"""# {ir.title()} —— CrewAI 配置(由 agentskills-bridge 生成)

本目录由 agentskills-bridge 转换引擎自 AgentIR 生成,是一个单 agent 的 CrewAI 配置包。

## 目录结构

- config/agents.yaml —— agent 定义(role=展示名,goal=何时使用,backstory=完整系统提示词)
- config/tasks.yaml —— 任务定义(单任务 {ir.name}_task,description 附知识路由说明)
- knowledge/ —— 参考知识文档:
{listing}

## 使用方法

1. 安装 CrewAI:`pip install crewai`
2. 新建项目:`crewai create crew {ir.name}`
3. 拷贝文件到新项目:
   - `config/agents.yaml` -> `<项目>/src/config/agents.yaml`
   - `config/tasks.yaml` -> `<项目>/src/config/tasks.yaml`
   - `knowledge/` -> `<项目>/src/knowledge/`(CrewAI Knowledge 依赖版本不同,也可在 crew 定义中配置 knowledge source 指向这些文件)
4. 在 `<项目>/src/main.py` 中按默认模板装配 Crew(Kickoff 该任务),然后运行:`crewai run`

## 接入 GLM(智谱开放平台)—— 双端点任选

crewai>=1.15 不依赖 litellm:LLM() 自动路由到内置原生 provider(2026-10
实测 crewai 1.15.27)。在 main.py 装配时把 llm 传给 Agent(llm=llm),
role/goal/backstory 取自 config/agents.yaml:

OpenAI 兼容路径(GLM v4,模型如 glm-4-flash)—— `openai/` 前缀 + api_base
自动判 custom_openai,命中原生 OpenAICompletion:

```python
from crewai import LLM
llm = LLM(
    model="openai/glm-4-flash",
    api_key="<GLM_API_KEY>",
    api_base="https://open.bigmodel.cn/api/paas/v4",
    max_tokens=1024,
)
```

Anthropic 兼容路径(模型如 glm-5.3-flash)—— 非 claude-* 模型名不会自动
命中原生路由(会掉到未安装的 litellm 回退),必须显式 provider="anthropic";
需先 `pip install anthropic` 提供 crewai 原生 AnthropicCompletion:

```python
from crewai import LLM
llm = LLM(
    model="glm-5.3-flash",
    provider="anthropic",
    api_key="<GLM_API_KEY>",
    base_url="https://open.bigmodel.cn/api/anthropic",
    max_tokens=2048,
)
```

## 说明

- agents.yaml/tasks.yaml 为手写标准 YAML,可被 pyyaml 与 CrewAI 直接读取。
- tasks.yaml 的 description 末尾附带"知识路由"说明,要求 agent 优先引用 knowledge/ 文档。
"""
