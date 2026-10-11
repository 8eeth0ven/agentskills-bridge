"""CrewAI Skills emitter:AgentIR -> CrewAI 原生 Agent Skills 项目(crewai>=1.12.0)。

产出:
    <out>/skills/<name>/SKILL.md         合法 Anthropic 风格技能:frontmatter
                                         (name/description)+ system_prompt 正文,
                                         可直接被 CrewAI v1.12.0+ 加载
    <out>/skills/<name>/references/*.md  知识文档按 filename 拷贝(渐进披露资源层)
    <out>/config/agents.yaml             agent 定义(role/goal/backstory +
                                         skills: ["./skills"] 目录发现式挂载)
    <out>/config/tasks.yaml              单任务(description 附知识路由说明)
    <out>/README.md                      使用方法与运行机制说明

`skills` 字段为 CrewAI v1.12.0(2026-03)引入的公开 Agent 字段。实测
crewai 1.15.27 的 loader(skills/loader.py)把 skills 路径输入一律当
"搜索目录"、只扫其子目录下的 SKILL.md:引用发现目录 `["./skills"]` 才能
加载技能(METADATA 级,任务命中时渐进激活);单技能目录
`["./skills/<name>"]` 只会扫到 references/,解析出 0 个技能,禁止产出。
SKILL.md 同时满足 agentskills.io 开放规范(name 与目录名一致、
description ≤1024 字符),跨厂商可移植。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR
from converter.skill_writer import _frontmatter_metadata

EXPECTED_OUTPUT = "结构化的最终回答,必要时引用技能内 references/ 参考文档"


def emit_crewai_skills(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 CrewAI Agent Skills 项目目录,返回 out_dir。"""
    out = Path(out_dir)
    name = _skill_name(ir)
    skill_dir = out / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    written = _write_references(ir, skill_dir)
    _write_scripts(ir, skill_dir)
    (skill_dir / "SKILL.md").write_text(_skill_md(ir, name), encoding="utf-8")
    (out / "config").mkdir(parents=True, exist_ok=True)
    (out / "config" / "agents.yaml").write_text(_agents_yaml(ir, name), encoding="utf-8")
    (out / "config" / "tasks.yaml").write_text(_tasks_yaml(ir, name, written), encoding="utf-8")
    (out / "README.md").write_text(_readme(ir, name, written), encoding="utf-8")
    return out


# ---------- 技能目录生成(SKILL.md + references/) ----------

def _skill_name(ir: AgentIR) -> str:
    """规范技能目录/frontmatter 名:小写字母数字+单连字符,1-64 字符。

    agentskills.io 与 CrewAI skills 校验均要求 name 形如
    ^[a-z0-9]+(-[a-z0-9]+)*$ 且与目录名一致;非法字符归一成单连字符,
    超 64 字符截断(去掉尾部悬挂连字符),空值兜底 "agent"。
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (ir.name or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:64].rstrip("-") or "agent"


def _first_line(text: str) -> str:
    """取文本首个非空、非纯标题行并单行化(SKILL.md description 兜底)。"""
    for line in (text or "").splitlines():
        flat = " ".join(line.split())
        if flat.lstrip("#").strip():
            return flat
    return ""


def _description(ir: AgentIR, limit: int = 1024) -> str:
    """单行化 description 并保证非空、≤limit 字符(超长截断补 "...")。

    规范要求 1-1024 字符;空白展平成单行 YAML 安全标量;空值依次兜底
    system_prompt 首行、占位句。
    """
    text = " ".join((ir.description or "").split())
    if not text:
        text = _first_line(ir.system_prompt) or f"Instructions for {ir.title()}."
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def _yaml_str(value: str) -> str:
    """生成合法的 YAML 双引号标量(JSON 转义是 YAML 双引号子集)。"""
    return json.dumps(value or "", ensure_ascii=False)


def _skill_md(ir: AgentIR, name: str) -> str:
    """生成 SKILL.md:frontmatter(name/description + 可选 metadata 行)+ 正文。

    metadata 行(单行 JSON,agentskills.io 允许的扩展对象)复用
    skill_writer._frontmatter_metadata:携带 tools 契约(input_schema/
    side_effects)与 graph_edges 等语义键,经 parse_crewai_skills →
    load_skill 还原,agent→crewai-skills 反向不再静默丢工具 schema。
    """
    body = (ir.system_prompt or "").strip() or "(源 agent 未提供系统提示词。)"
    meta_line = ""
    metadata = _frontmatter_metadata(ir)
    if metadata:
        compact = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        meta_line = "\nmetadata: " + compact
    return (
        "---\n"
        f"name: {_yaml_str(name)}\n"
        f"description: {_yaml_str(_description(ir))}{meta_line}\n"
        "---\n\n"
        f"{body}\n"
    )


# ---------- 知识文档拷贝 ----------

def _safe_filename(filename: str) -> Optional[str]:
    """过滤非法路径名:为空、. / ..、含 / 或 \\ 或 .. 的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _write_references(ir: AgentIR, skill_dir: Path) -> List[str]:
    """把知识文档拷进 <skill_dir>/references/,返回写出的文件名列表。"""
    written: List[str] = []
    for doc in ir.knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        rdir = skill_dir / "references"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / name).write_text(doc.content or "", encoding="utf-8")
        written.append(name)
    return written


def _write_scripts(ir: AgentIR, skill_dir: Path) -> List[str]:
    """把源 skill 的 scripts/ 原样拷进 <skill_dir>/scripts/,返回相对路径列表。

    Agent Skills 规范里 scripts/ 是技能的执行资源层,skill 目录形态的
    产物必须原样保留(否则 docx 这类脚本型技能能力直接减半)。源目录
    取 ir.metadata["source_path"](load_skill 填写),逐条按 ir.scripts
    相对路径拷贝;源缺失或路径越界(含 ..)跳过。非 skill 源(无
    source_path)时安静跳过 —— 此时 IR 本就没带脚本内容。
    """
    source = (ir.metadata or {}).get("source_path") or ""
    copied: List[str] = []
    if not source or not ir.scripts:
        return copied
    src_root = Path(source)
    for rel in ir.scripts:
        rel = (rel or "").strip()
        if not rel or ".." in Path(rel).parts:
            continue
        src = src_root / rel
        if not src.is_file():
            continue
        dst = skill_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        copied.append(rel)
    return copied


# ---------- YAML 生成(手写,不经 pyyaml) ----------

def _folded_entry(key: str, value: str, indent: str = "  ") -> str:
    """生成 `key: |` 字面块标量条目;空文本退化为 `key: \"\"`。

    用 `|`(literal)而非 `>`(folded):backstory 承载 markdown 正文
    (列表/代码块/标题)时换行有语义,folded 会把单换行折叠为空格,
    roundtrip 后结构被破坏(crewai 靶 emitter 已实证并修复,此处同步)。
    """
    if not value or not value.strip():
        return f'{indent}{key}: ""\n'
    out = [f"{indent}{key}: |"]
    for line in value.rstrip("\n").split("\n"):
        out.append(f"{indent}  {line}" if line.strip() else "")
    return "\n".join(out) + "\n"


def _agents_yaml(ir: AgentIR, name: str) -> str:
    parts = [f"{name}:\n"]
    parts.append(_folded_entry("role", ir.title()))
    parts.append(_folded_entry("goal", ir.description))
    parts.append(_folded_entry("backstory", ir.backstory()))
    parts.append("  verbose: false\n")
    # 必须引用发现目录 ./skills:crewai(实测 1.15.27)loader 把路径输入当
    # 搜索目录扫子目录 SKILL.md,单技能目录 ./skills/<name> 会解析出 0 个技能。
    parts.append('  skills: ["./skills"]\n')
    return "".join(parts)


def _tasks_yaml(ir: AgentIR, name: str, written: List[str]) -> str:
    description = "\n\n".join(
        p for p in (ir.description.strip(), _knowledge_routing(name, written)) if p
    )
    parts = [f"{name}_task:\n"]
    parts.append(_folded_entry("description", description))
    parts.append(_folded_entry("expected_output", EXPECTED_OUTPUT))
    parts.append(f"  agent: {name}\n")
    return "".join(parts)


def _knowledge_routing(name: str, written: List[str]) -> str:
    if written:
        files = ", ".join(f"skills/{name}/references/{f}" for f in written)
        return (
            "知识路由:技能激活后可按需读取随附参考文档"
            f"({files});相关内容以文档为准并引用,"
            "文档未覆盖的部分再基于通用知识作答并说明来源。"
        )
    return "知识路由:本技能未附带 references/ 参考文档,直接基于通用知识作答。"


# ---------- README ----------

def _readme(ir: AgentIR, name: str, written: List[str]) -> str:
    listing = "\n".join(
        f"- skills/{name}/references/{f}" for f in written
    ) or "- (本技能未附带参考文档)"
    return f"""# {ir.title()} —— CrewAI Agent Skills 项目(由 agentskills-bridge 生成)

## 目录结构

- skills/{name}/SKILL.md —— 合法 Anthropic 风格技能(frontmatter name/description + 指令正文)
- skills/{name}/references/ —— 按需加载的参考文档:
{listing}
- config/agents.yaml —— agent 定义(role=展示名,goal=何时使用,backstory=系统提示词精简版,
  并通过 `skills: ["./skills"]` 目录发现式挂载技能)
- config/tasks.yaml —— 任务定义(单任务 {name}_task,description 附知识路由说明)

## 版本要求

- `crewai>=1.12.0` —— `skills` 字段与 Agent Skills 机制自 v1.12.0(2026-03)引入;
  如需运行时渐进披露请用 v1.15.9+。
- SKILL.md 同时符合 agentskills.io 开放规范,可直接被 Claude Code、Codex 等其它实现加载。

## 使用方法

1. 安装:`pip install "crewai>=1.12.0"`
2. 新建项目:`crewai create crew {name}`
3. 拷贝文件到新项目(skills 目录固定在项目根,不是 src/config/):
   - `skills/` -> `<项目>/skills/`
   - `config/agents.yaml` -> `<项目>/src/config/agents.yaml`
   - `config/tasks.yaml` -> `<项目>/src/config/tasks.yaml`
4. 按 @CrewBase 默认模板在 `<项目>/src/crew.py` 装配 Crew,然后运行:`crewai run`

## skills 挂载语义

agents.yaml 中的 `skills: ["./skills"]` 是目录发现式引用:Agent 构造时只读取
各 SKILL.md 的 name/description(METADATA 级),任务命中时由内置 load_skill 工具
按需激活完整正文(INSTRUCTIONS 级)。注意:不要写成单技能目录
`["./skills/{name}"]`——实测 crewai 1.15.27 的 loader 把 skills 路径输入一律当
"搜索目录"、只扫其子目录下的 SKILL.md,单技能目录下只有 references/,会解析出
0 个技能(等价于没挂载)。

## 运行时机制(三级渐进披露)

1. Discovery:Agent 初始化仅读取各 SKILL.md 的 name/description,注入提示词目录;
2. Activation:任务命中 description 时加载完整 SKILL.md 正文(内置 load_skill 工具按需激活);
3. Resources:references/ 参考文档仅在任务需要时由 agent 按需读取。

## CLI 管理

- `crewai create skill <new-name>` 在项目内脚手架新技能(SKILL.md 模板 + scripts/references/assets 空目录);
- `crewai skill list` 列出项目 ./skills/ 与全局缓存的已装技能;
- `crewai skill publish` 可把本技能发布到组织私有注册表(org 内可见)。

## 接入 GLM(智谱开放平台)—— 双端点任选

crewai>=1.15 不依赖 litellm:LLM() 自动路由到内置原生 provider(2026-10
实测 crewai 1.15.27)。在 crew.py 装配时把 llm 传给 Agent(llm=llm),
role/goal/backstory/skills 取自 config/agents.yaml:

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
"""
