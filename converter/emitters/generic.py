"""Generic emitter:AgentIR -> 框架无关的规范序列化。

产出:
    <out>/agent.json     AgentIR 便携 JSON 序列化(移除本机来源路径)
    <out>/knowledge/*.md 知识文档按 filename 拷贝
    <out>/README.md      agent.json 字段说明与读取方式
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR


def emit_generic(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 规范序列化写到 out_dir,返回 out_dir。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    from converter.preservation import portable_ir
    (out / "agent.json").write_text(portable_ir(ir).to_json() + "\n", encoding="utf-8")
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


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
    return f"""# {ir.title()} —— 通用 Agent 定义(由 agentskills-bridge 生成)

## 文件

- agent.json —— AgentIR 的规范 JSON 序列化,任何框架/语言都可以直接读取
- knowledge/ —— 参考知识文档(文件名与 agent.json 的 knowledge[].filename 一一对应):
{listing}

## agent.json 字段

| 字段 | 含义 |
|------|------|
| name | kebab-case id |
| display_name | 人类可读名 |
| description | 何时使用 |
| system_prompt | 主指令 |
| default_prompt | UI 默认提示词 |
| tools | 工具契约(name/description/input_schema/side_effects) |
| knowledge | 知识文档清单(filename/title/content;本机 source_path 留空) |
| tasks | 任务步骤 |
| scripts | 附带脚本相对路径 |
| metadata | 其他元数据 |

## 读取方式(Python)

```python
from converter.ir import AgentIR

ir = AgentIR.from_json(open("agent.json", encoding="utf-8").read())
```

其他框架可按相同结构把 agent.json 转换为自己的配置形态。
"""
