"""Deep Agents emitter:AgentIR -> LangChain 官方 deepagents 运行时项目。

产出:
    <out>/agent.py                 入口:from deepagents import create_deep_agent,
                                   skills 参数指向本地 skills/ 源目录,主循环读输入跑 agent
    <out>/skills/<name>/SKILL.md   合法 Anthropic 风格技能(agentskills.io 规范):
                                   frontmatter(name/description)+ system_prompt 正文
    <out>/skills/<name>/references/*.md  知识文档按 filename 拷贝(渐进披露资源层)
    <out>/requirements.txt         deepagents>=0.7 + langchain
    <out>/README.md                安装、SkillsMiddleware 渐进披露与 langchain 关系说明

create_deep_agent 的 `skills` 参数接受本地目录列表(官方签名
`skills: list[str] | None`),指向"包含技能子目录"的源目录 —— 即 `["./skills"]`;
由 deepagents 的 SkillsMiddleware 按 Anthropic Agent Skills 模式做渐进披露加载。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from converter.ir import AgentIR
from converter.emitters.crewai_skills import _write_scripts

MODEL = "anthropic:claude-sonnet-4-6"


def emit_deepagents(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 deepagents 运行时项目目录,返回 out_dir。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = _skill_name(ir)
    skill_dir = out / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    written = _write_references(ir, skill_dir, name)
    _write_scripts(ir, skill_dir)
    (skill_dir / "SKILL.md").write_text(_skill_md(ir, name), encoding="utf-8")
    (out / "agent.py").write_text(_agent_py(ir, name, written), encoding="utf-8")
    (out / "requirements.txt").write_text(_requirements(), encoding="utf-8")
    (out / "README.md").write_text(_readme(ir, name, written), encoding="utf-8")
    return out


# ---------- agent.py 生成 ----------

def _agent_py(ir: AgentIR, name: str, written: List[str]) -> str:
    sections = [
        _header(ir, name),
        _prompt_section(ir),
        _knowledge_section(name, written),
        _main_section(name),
    ]
    return "\n\n".join(sections)


def _header(ir: AgentIR, name: str) -> str:
    return (
        "#!/usr/bin/env python3\n"
        f'"""{ir.title()} —— Deep Agent(LangChain deepagents 运行时)。\n\n'
        "本文件由 agentskills-bridge 转换引擎自 AgentIR 生成,可独立阅读与修改:\n"
        "- SYSTEM_PROMPT:源 agent 的完整系统提示词;\n"
        f"- skills 参数指向脚本同目录的 skills/ 源目录,内含 {name} 技能\n"
        "  (SKILL.md + references/),由 deepagents 的 SkillsMiddleware 按\n"
        "  Anthropic Agent Skills 规范做三级渐进披露加载;\n"
        "- 主循环:读一行用户输入,agent 执行一轮并打印回答。\n"
        '"""\n\n'
        "from pathlib import Path\n"
        "\n"
        "from deepagents import create_deep_agent\n"
        "from deepagents.backends import FilesystemBackend\n"
    )


def _prompt_section(ir: AgentIR) -> str:
    return (
        "# ---------- 系统提示词(源自 AgentIR.system_prompt) ----------\n\n"
        f"SYSTEM_PROMPT = {_py_triple(ir.system_prompt)}\n"
    )


def _knowledge_section(name: str, written: List[str]) -> str:
    entries = [f"# - skills/{name}/references/{f}" for f in written]
    body = "\n".join(entries) if entries else "# - (源 agent 未附带知识文档。)"
    return (
        "# ---------- 知识清单(渐进披露第 3 层,agent 按需读取) ----------\n"
        f"{body}\n"
    )


def _main_section(name: str) -> str:
    # deepagents 0.7.x 实测约束:默认 backend 是 StateBackend(内存虚拟文件
    # 系统,文件需经 invoke(files={...}) 提供),skills=[...] 指向本地源目录时
    # 必须显式传 FilesystemBackend 才会真正从磁盘扫描 SKILL.md。因此模块顶层
    # 只定义常量与工厂函数(导入零副作用,模型初始化需要 provider 包+key),
    # 真实组装推迟到 build_agent()/main。
    return (
        "# ---------- Agent 组装与入口 ----------\n\n"
        f'DEFAULT_MODEL = "{MODEL}"  # 换模型改这里,如 "openai:gpt-4o"\n'
        "AGENT_DIR = Path(__file__).resolve().parent\n"
        "\n"
        "\n"
        "def build_agent(model=None, backend=None):\n"
        '    """组装 Deep Agent:skills/ 源目录经 FilesystemBackend 从磁盘加载。\n'
        "\n"
        "    model 缺省时按 DEFAULT_MODEL 解析(需要对应 provider 包与 API key);\n"
        "    也可直接传 BaseChatModel 实例(如测试注入 fake model),天然支持\n"
        "    任意 OpenAI 兼容 / Anthropic 兼容端点。示例(GLM 双协议 + Claude\n"
        "    官方;密钥一律经环境变量注入,勿硬编码):\n"
        "\n"
        "        # 1) OpenAI 兼容端点(GLM v4 / DeepSeek / vLLM 等):\n"
        "        #    pip install langchain-openai\n"
        "        import os\n"
        "        from langchain_openai import ChatOpenAI\n"
        '        llm = ChatOpenAI(model="glm-4-flash", api_key=os.environ["GLM_API_KEY"],\n'
        '                         base_url="https://open.bigmodel.cn/api/paas/v4/")\n'
        "\n"
        "        # 2) Anthropic 兼容端点(GLM anthropic 路径等):\n"
        "        #    pip install langchain-anthropic\n"
        "        from langchain_anthropic import ChatAnthropic\n"
        '        llm = ChatAnthropic(model="glm-5.3-flash", api_key=os.environ["GLM_API_KEY"],\n'
        '                            base_url="https://open.bigmodel.cn/api/anthropic")\n'
        "\n"
        "        # 3) Claude 官方(不传 base_url 即默认官方端点):\n"
        '        llm = ChatAnthropic(model="claude-sonnet-4-5",\n'
        '                            api_key=os.environ["ANTHROPIC_API_KEY"])\n'
        "\n"
        "    然后 build_agent(model=llm) 即可换到对应端点;backend 缺省用\n"
        '    FilesystemBackend(root_dir=AGENT_DIR) 从磁盘扫描 skills/。\n'
        '    """\n'
        "    return create_deep_agent(\n"
        "        model=model if model is not None else DEFAULT_MODEL,\n"
        "        system_prompt=SYSTEM_PROMPT,\n"
        '        skills=["skills"],  # backend 虚拟路径,含技能子目录 skills/'
        + name
        + "/\n"
        "        backend=backend if backend is not None else FilesystemBackend(root_dir=AGENT_DIR),\n"
        "    )\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    agent = build_agent()\n"
        "    # 读一次用户输入,跑一轮 agent。\n"
        '    user_input = input("你: ")\n'
        '    result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})\n'
        '    print("Agent:", result["messages"][-1].content)\n'
    )


def _py_triple(text: str) -> str:
    """把文本嵌成 Python 三引号字面量;含 \"\"\" 时改用 ''' 并处理冲突。"""
    if not text:
        return '""'
    delim = '"""'
    if delim in text:
        delim = "'''"
    body = text.replace("\\", "\\\\")
    if delim in body:
        body = body.replace(delim, "\\" + delim)
    if body.endswith(delim[0]):
        body = body[:-1] + "\\" + delim[0]
    return delim + body + delim


# ---------- 技能目录生成(SKILL.md + references/) ----------

def _skill_name(ir: AgentIR) -> str:
    """规范技能目录/frontmatter 名:小写字母数字+单连字符,1-64 字符。

    agentskills.io 规范要求 name 形如 ^[a-z0-9]+(-[a-z0-9]+)*$ 且与目录名
    一致;非法字符归一成单连字符,超 64 字符截断,空值兜底 "agent"。
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
    """单行化 description 并保证非空、≤limit 字符(超长截断补 "...")。"""
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
    """生成 SKILL.md:frontmatter(name/description)+ system_prompt 正文。"""
    body = (ir.system_prompt or "").strip() or "(源 agent 未提供系统提示词。)"
    return (
        "---\n"
        f"name: {_yaml_str(name)}\n"
        f"description: {_yaml_str(_description(ir))}\n"
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


def _write_references(ir: AgentIR, skill_dir: Path, name: str) -> List[str]:
    """把知识文档拷进 <skill_dir>/references/,返回写出的文件名列表。"""
    written: List[str] = []
    for doc in ir.knowledge:
        fname = _safe_filename(doc.filename)
        if fname is None:
            continue
        rdir = skill_dir / "references"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / fname).write_text(doc.content or "", encoding="utf-8")
        written.append(fname)
    return written


# ---------- 附带产物 ----------

def _requirements() -> str:
    return (
        "deepagents>=0.7\n"
        "langchain>=1.0\n"
        "# 模型 provider,与 agent.py 中 model 字符串对应(任选其一;也可传自定义\n"
        "# BaseChatModel 实例接任意 OpenAI/Anthropic 兼容端点,见 build_agent docstring):\n"
        "langchain-anthropic>=1.0  # Claude 官方 / GLM anthropic 路径(glm-5.3-flash)\n"
        "langchain-openai>=1.0     # OpenAI 官方 / GLM v4 路径(glm-4-flash)等\n"
    )


def _readme(ir: AgentIR, name: str, written: List[str]) -> str:
    listing = "\n".join(
        f"- skills/{name}/references/{f}" for f in written
    ) or "- (本技能未附带参考文档)"
    return f"""# {ir.title()} —— Deep Agent(deepagents 运行时,由 agentskills-bridge 生成)

## 文件

- agent.py —— 入口脚本(create_deep_agent + skills 挂载 + 主循环)
- skills/{name}/ —— 技能目录:
  - SKILL.md —— frontmatter(name/description)+ 指令正文
  {listing}
- requirements.txt —— Python 依赖

## 运行

1. 安装依赖:`pip install -r requirements.txt`
2. 配置密钥:`export ANTHROPIC_API_KEY=sk-ant-...`(模型在 agent.py 中可换)
3. 运行:`python agent.py` —— 输入一句话,agent 执行一轮并打印回答

## 换任意 OpenAI / Anthropic 兼容端点

`build_agent(model=None, backend=None)` 接受任意 `BaseChatModel` 实例,
agent.py 的 `build_agent` docstring 内附三份可直接照抄的示例(GLM OpenAI
兼容路径 / GLM Anthropic 兼容路径 / Claude 官方)。要点:

- OpenAI 兼容端点(GLM v4、DeepSeek、vLLM 等):
  `ChatOpenAI(model=..., api_key=..., base_url="https://open.bigmodel.cn/api/paas/v4/")`
- Anthropic 兼容端点(GLM anthropic 路径):
  `ChatAnthropic(model=..., api_key=..., base_url="https://open.bigmodel.cn/api/anthropic")`
- Claude 官方:`ChatAnthropic(model="claude-sonnet-4-5", api_key=...)`(不传 base_url)

密钥经环境变量注入,不要写进代码或仓库。

## SkillsMiddleware 与渐进披露

deepagents 的 SkillsMiddleware 实现了 Anthropic 的 Agent Skills 模式
(遵循 agentskills.io 规范),三级渐进披露与 Claude Agent SDK 一致:

1. 启动时扫描 skills/ 各子目录,仅把每个 SKILL.md frontmatter 的 name/description
   注入系统提示(约 100 tokens/skill);
2. agent 判断任务匹配后,用内置 read_file 工具读取完整 SKILL.md 正文;
3. references/ 等资源仅在正文引用到时再按需读取。

`create_deep_agent(skills=["skills"], backend=FilesystemBackend(root_dir=...))`
即挂载该中间件;skills 参数是相对 backend 根的源目录路径(含技能子目录),
配 FilesystemBackend 时从磁盘扫描,也可指向别的目录甚至 `~/.claude/skills`
(与 Claude Code 共用同一套技能)。注意 deepagents 默认 backend 是内存
StateBackend,不传 FilesystemBackend 时 skills 不会从磁盘加载。

## 与 langchain create_agent 的关系

deepagents 是 LangChain 官方产品线:`create_deep_agent` 在
`langchain.agents.create_agent`(langchain>=1.0,返回 LangGraph 编译图)之上,
追加文件系统 backend、规划/子代理等 Deep Agents 能力与 SkillsMiddleware。
`create_agent` 本身没有 skills 参数 —— 官方给的手工模式是自写 load_skill 工具 +
在 system_prompt 里列技能清单;要标准 SKILL.md 加载就走 deepagents。
"""
