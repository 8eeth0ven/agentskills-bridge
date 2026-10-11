"""OpenAI/Codex agent emitter:AgentIR -> openai.yaml + instructions.md + knowledge/。

产出(对齐 Codex skill 安装形态,整个目录即 skill):
    <out>/agents/openai.yaml  interface: display_name / short_description / default_prompt
    <out>/instructions.md     完整 system_prompt
    <out>/knowledge/*.md      知识文档按 filename 拷贝
    <out>/README.md           Codex skill / ChatGPT/Codex UI 用法

openai.yaml 手写生成(不依赖 pyyaml),标量一律安全双引号包裹。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR

_SENTENCE_END = ".!?。！？"
# Codex 官方长度约束(codex-rs/skills/src/interface.rs:
#   MAX_NAME_LEN=64, MAX_DESCRIPTION_LEN=1024;超长字段被 resolve_str 忽略)
_MAX_DISPLAY_NAME = 64
_MAX_PROMPT = 1024


def emit_openai_agents(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 OpenAI/Codex agent 定义目录,返回 out_dir。"""
    out = Path(out_dir)
    (out / "agents").mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    (out / "agents" / "openai.yaml").write_text(_openai_yaml(ir), encoding="utf-8")
    (out / "instructions.md").write_text(ir.system_prompt or "", encoding="utf-8")
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


# ---------- openai.yaml 生成(手写 YAML) ----------

def _clamp(value: str, limit: int) -> str:
    """按字符数截断(Codex resolve_str 按 chars().count() 计长)。"""
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _openai_yaml(ir: AgentIR) -> str:
    short = _first_sentence(ir.description, limit=120)
    default = (ir.default_prompt or "").strip() or _default_prompt(ir, short)
    # x-source-skill: 转换器私有扩展(x- 前缀命名空间,Codex 宽容忽略),
    # 携带全文 description 保证 roundtrip;parse_openai 优先读取。
    full_desc = " ".join((ir.description or "").split())
    lines = [
        "interface:",
        f"  display_name: {_yaml_str(_clamp(ir.title(), _MAX_DISPLAY_NAME))}",
        f"  short_description: {_yaml_str(_clamp(short, _MAX_PROMPT))}",
        f"  default_prompt: {_yaml_str(_clamp(default, _MAX_PROMPT))}",
        "x-source-skill:",
        f"  name: {_yaml_str(ir.name)}",
        f"  description: {_yaml_str(full_desc or short)}",
    ]
    return "\n".join(lines) + "\n"


def _default_prompt(ir: AgentIR, short: str) -> str:
    """无 default_prompt 时按 `Use ${name} to ...` 生成。"""
    doing = short or "完成用户的任务"
    return f"Use {ir.name} to {doing}"


def _first_sentence(text: str, limit: int = 120) -> str:
    """取首行内的第一句,并截断到 limit 字。"""
    text = (text or "").strip()
    if not text:
        return ""
    text = text.split("\n", 1)[0].strip()
    cut = -1
    for i, ch in enumerate(text):
        if ch in _SENTENCE_END:
            cut = i + 1
            break
    sent = text[:cut] if cut > 0 else text
    if len(sent) > limit:
        sent = sent[:limit].rstrip() + "…"
    return sent


def _yaml_str(value: str) -> str:
    """任意文本 -> 安全的 YAML 双引号标量。"""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


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
    return f"""# {ir.title()} —— OpenAI/Codex Agent 定义(由 agentskills-bridge 生成)

本目录整体即一个 skill 形态,目录结构对齐 Codex skill 的安装方式,可直接当 `$skill` 调用,也是 ChatGPT/Codex UI 的 agent 定义。

## 文件

- agents/openai.yaml —— interface 定义(display_name / short_description / default_prompt)
- instructions.md —— 完整系统提示词(源 agent 的 system_prompt 原文)
- knowledge/ —— 参考知识文档:
{listing}

## 用作 Codex skill

把整个目录放进 Codex 的 skills 目录(如 `~/.codex/skills/{ir.name}/`),对话中以 `${ir.name}` 调用:
instructions.md 作为主指令,knowledge/ 下的文档作为参考资料按需检索。

## 用作 ChatGPT/Codex UI 的自定义 agent

创建自定义 agent 时:
1. 名称/简介/默认提示词 -> 填 agents/openai.yaml 中 interface 的对应字段;
2. 系统指令 -> 粘贴 instructions.md 全文;
3. 知识文件 -> 按需上传 knowledge/ 下的文档。
"""
