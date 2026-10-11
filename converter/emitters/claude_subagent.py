"""Claude Code subagent emitter:AgentIR -> .claude/agents/<name>.md。

产出:
    <out>/.claude/agents/<name>.md  subagent 定义:frontmatter(name/description/
                                    tools/model)+ 正文 system_prompt(knowledge
                                    以"知识文件"清单附在正文末尾)
    <out>/knowledge/*.md           知识文档按 filename 拷贝
    <out>/README.md                subagents 机制与调用方式说明

Claude Code subagent = Markdown 文件 + YAML frontmatter、正文即该子代理的
system prompt。加载硬约束(规避即静默跳过):`---` 必须是文件第一行;
name 非空、≤256 字符、不含 ':'、不以 '-' 开头;description 非空。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR

DEFAULT_TOOLS = ["Read", "Grep", "Glob", "Bash"]
DEFAULT_MODEL = "sonnet"
# model 值域(官方 subagents 文档):别名 + inherit + 完整 claude-* 模型 id
_ALLOWED_MODELS = {"sonnet", "opus", "haiku", "fable", "inherit"}


def _model_value(raw: Any) -> str:
    """model 值域过滤:非 sonnet/opus/haiku/fable/inherit/claude-* 的值回退默认。

    源 IR 的 metadata.model 可能来自其他框架(如 langflow 的 gpt-4.1),
    直接写出不在 Claude Code 值域内;回退 sonnet 保证 frontmatter 合法。
    """
    model = str(raw or "").strip()
    if model in _ALLOWED_MODELS or model.startswith("claude-"):
        return model
    return DEFAULT_MODEL


def emit_claude_subagent(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 Claude Code subagent 目录,返回 out_dir。"""
    out = Path(out_dir)
    name = _agent_name(ir)
    (out / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    written = _write_knowledge(ir, out)
    agent_md = out / ".claude" / "agents" / f"{name}.md"
    agent_md.write_text(_agent_md(ir, name, written), encoding="utf-8")
    (out / "README.md").write_text(_readme(ir, name, written), encoding="utf-8")
    return out


# ---------- subagent 定义生成 ----------

def _agent_name(ir: AgentIR) -> str:
    """规范 subagent name:非空、单行、≤256 字符、不含 ':'、无空白、不以 '-' 开头。

    name 不合法时 Claude Code 会静默跳过整个文件,故在生成侧即清洗;
    ':' 保留给 plugin 作用域(my-plugin:reviewer),不允许出现在裸 name 里;
    官方示例均为 slug 形(code-reviewer / reviewer-v2),identifier 语义不含
    空白,故空白(含空格/制表)归一为单连字符。
    """
    name = "".join(
        ch for ch in (ir.name or "").strip() if ch not in ':\\\n\r\t'
    ).strip()
    name = re.sub(r"\s+", "-", name).strip()
    name = name.lstrip("-").strip()
    return name[:256] or "agent"


def _first_line(text: str) -> str:
    """取文本首个非空、非纯标题行并单行化(description 兜底)。"""
    for line in (text or "").splitlines():
        flat = " ".join(line.split())
        if flat.lstrip("#").strip():
            return flat
    return ""


def _description(ir: AgentIR) -> str:
    """单行化 description 并保证非空(subagent 加载硬约束)。"""
    text = " ".join((ir.description or "").split())
    if not text:
        text = _first_line(ir.system_prompt) or f"Delegate {ir.title()} tasks to this subagent."
    return text


def _yaml_str(value: str) -> str:
    """生成合法的 YAML 双引号标量(JSON 转义是 YAML 双引号子集)。"""
    return json.dumps(value or "", ensure_ascii=False)


def _tools_names(ir: AgentIR) -> List[str]:
    """取 ir.tools 的 name 列表;无工具时用默认四件套(Read/Grep/Glob/Bash)。"""
    names = [t.name.strip() for t in ir.tools if t.name and t.name.strip()]
    return names or list(DEFAULT_TOOLS)


def _tools_block(ir: AgentIR) -> str:
    lines = ["tools:"]
    lines += [f"  - {_yaml_str(n)}" for n in _tools_names(ir)]
    return "\n".join(lines) + "\n"


def _x_tools_line(ir: AgentIR) -> str:
    """工具契约扩展键:tools 白名单之后追加单行 JSON 数组的 x-tools:。

    白名单只有名字,丢 input_schema/side_effects;x-tools(x- 扩展命名
    空间,Claude Code 对未知 frontmatter 键宽容忽略)携带同结构
    [{name,description,input_schema,side_effects}],parse 端优先还原。
    """
    if not ir.tools:
        return ""
    compact = json.dumps(
        [t.to_dict() for t in ir.tools], ensure_ascii=False, separators=(",", ":")
    )
    return f"x-tools: {compact}\n"


def _agent_md(ir: AgentIR, name: str, written: List[str]) -> str:
    """生成 subagent markdown:frontmatter(四键 + 可选 knowledge 清单)+ 纯 system_prompt 正文。

    知识清单放 frontmatter 的 knowledge: 键而非正文 —— 正文是 prompt 的
    唯一载体,附加清单会在 roundtrip 时污染 system_prompt(评测 F_prompt
    曾因此降至 0.87-0.96);knowledge 内容本身由 knowledge/ 目录承载,
    frontmatter 键只作人读路由,parser 无需还原它。
    """
    model = _model_value(ir.metadata.get("model"))
    body = (ir.system_prompt or "").strip() or "(源 agent 未提供系统提示词。)"
    text = (
        "---\n"
        f"name: {_yaml_str(name)}\n"
        f"description: {_yaml_str(_description(ir))}\n"
        f"{_tools_block(ir)}"
        f"{_x_tools_line(ir)}"
        f"model: {_yaml_str(model)}\n"
    )
    if written:
        text += "knowledge:\n" + "".join(
            f"  - {_yaml_str(f)}\n" for f in written
        )
    text += f"---\n\n{body}\n"
    return text


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

def _readme(ir: AgentIR, name: str, written: List[str]) -> str:
    listing = "\n".join(
        f"- knowledge/{f}" for f in written
    ) or "- (本 subagent 未附带知识文档)"
    return f"""# {ir.title()} —— Claude Code Subagent(由 agentskills-bridge 生成)

## 文件

- .claude/agents/{name}.md —— subagent 定义(frontmatter name/description/tools/model,
  正文即该子代理的 system prompt)
- knowledge/ —— 知识文档(正文"知识文件"清单引用):
{listing}

## Subagents 机制

Claude Code 的 subagent(子代理)定义为 Markdown 文件 + YAML frontmatter,
正文即该子代理的 system prompt(不含 Claude Code 主系统提示)。目录递归扫描,
agent 标识只来自 frontmatter 的 name 字段。放置位置:

- 项目级:`<仓库根>/.claude/agents/{name}.md` —— 仅本仓库会话可用,可提交共享;
- 用户级:`~/.claude/agents/{name}.md` —— 本机所有项目可用;
- 组织级:管理设置目录下的 `.claude/agents/`(优先级最高)。

子代理在独立上下文中运行(默认不继承主会话历史),完成后向主会话返回结果;
frontmatter 的 tools 限定其可用工具,model 覆盖模型(sonnet/opus/haiku/inherit)。

## 调用方式

- 自动:主会话中任务描述命中 description 时,由 Claude 自动委派给该 subagent;
- 显式:在 Claude Code 会话中直接说"使用 {name} 子代理完成 ...";
- 校验:`claude plugin validate .claude/agents` 可检查定义文件能否被解析。

## 安装

把 `.claude/agents/{name}.md` 拷到目标仓库根的 `.claude/agents/`(或用户级
`~/.claude/agents/`);`knowledge/` 固定放仓库根,与正文中"知识文件"清单的
路径一一对应。若改放用户级目录,请同步把 knowledge/ 移到对应仓库并调整清单路径。
"""
