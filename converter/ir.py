"""Agent/Skill 中间表示 (Intermediate Representation)。

所有转换都经过 AgentIR:
    skill -> AgentIR -> crewai / langchain / langflow / openai / generic
    crewai / langchain / langflow -> AgentIR -> skill

IR 字段与 llm-wiki/01-concepts/intermediate-representation.md 一一对应,
修改任一侧必须同步另一侧。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SOURCE_FORMATS = ("skill", "crewai", "langchain", "langflow", "generic")
TARGET_FORMATS = (
    "autogen",
    "crewai",
    "crewai-skills",
    "deepagents",
    "langchain",
    "langflow",
    "openai",
    "claude-subagent",
    "generic",
)


@dataclass
class ToolSpec:
    """Agent 可调用的工具契约。"""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    side_effects: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolSpec":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_schema=data.get("input_schema") or {},
            side_effects=bool(data.get("side_effects", False)),
        )


@dataclass
class KnowledgeDoc:
    """一份章节知识,对应 skill 里的 references/<file>.md。"""

    filename: str  # 例如 "crewai-patterns.md"
    title: str = ""  # 章节标题,例如 "CrewAI Patterns"
    content: str = ""  # markdown 正文
    source_path: str = ""  # 来源文件绝对/相对路径(拷贝时用)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeDoc":
        return cls(
            filename=data.get("filename", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            source_path=data.get("source_path", ""),
        )


@dataclass
class TaskStep:
    """一个任务步骤;单 agent 通常只有一步,multi-agent 编排会有多步。"""

    name: str
    description: str = ""
    expected_output: str = ""
    agent: str = ""  # 承担该步骤的 agent 名;单 agent 留空

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskStep":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            expected_output=data.get("expected_output", ""),
            agent=data.get("agent", ""),
        )


@dataclass
class AgentIR:
    """规范化 agent 表示 —— 一切转换的枢纽。"""

    name: str  # kebab-case id,例如 "agent-fullcycle-engineering"
    display_name: str = ""  # 人类可读名,例如 "Agent Fullcycle Engineering"
    description: str = ""  # 何时使用(对应 skill frontmatter description)
    system_prompt: str = ""  # 主指令(对应 SKILL.md 正文)
    default_prompt: str = ""  # UI 默认提示词(openai.yaml interface.default_prompt)
    tools: List[ToolSpec] = field(default_factory=list)
    knowledge: List[KnowledgeDoc] = field(default_factory=list)
    tasks: List[TaskStep] = field(default_factory=list)
    scripts: List[str] = field(default_factory=list)  # skill 侧 scripts/ 相对路径
    metadata: Dict[str, Any] = field(default_factory=dict)  # source_format / source_path / model 等

    # ---------- 序列化 ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "default_prompt": self.default_prompt,
            "tools": [t.to_dict() for t in self.tools],
            "knowledge": [k.to_dict() for k in self.knowledge],
            "tasks": [t.to_dict() for t in self.tasks],
            "scripts": list(self.scripts),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentIR":
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            default_prompt=data.get("default_prompt", ""),
            tools=[ToolSpec.from_dict(t) for t in data.get("tools", [])],
            knowledge=[KnowledgeDoc.from_dict(k) for k in data.get("knowledge", [])],
            tasks=[TaskStep.from_dict(t) for t in data.get("tasks", [])],
            scripts=list(data.get("scripts", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "AgentIR":
        return cls.from_dict(json.loads(text))

    # ---------- 派生 ----------

    def title(self) -> str:
        """从 kebab-case name 生成 display_name(未显式提供时)。"""
        if self.display_name:
            return self.display_name
        return " ".join(p.capitalize() for p in self.name.split("-") if p)

    def backstory(self, max_chars: int = 1200) -> str:
        """system_prompt 的精简版,供 CrewAI backstory / UI 摘要使用。"""
        text = self.system_prompt.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        # 尽量在段落/句子边界截断
        for sep in ("\n\n", "\n", ". "):
            idx = cut.rfind(sep)
            if idx > max_chars // 2:
                return cut[: idx + len(sep)].rstrip() + "\n..."
        return cut.rstrip() + "..."


def slugify(text: str, fallback: str = "agent") -> str:
    """把任意名字规范成 kebab-case id。"""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or fallback


def parse_frontmatter(text: str) -> "tuple[Dict[str, str], str]":
    """解析 YAML frontmatter(只取平面的字符串字段),返回 (meta, body)。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    meta: Dict[str, str] = {}
    key: Optional[str] = None
    buf: List[str] = []
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            if key:
                meta[key] = " ".join(buf).strip()
            key, value = m.group(1), m.group(2).strip().strip('"').strip("'")
            buf = [value] if value else []
        elif key:
            buf.append(line.strip())
    if key:
        meta[key] = " ".join(buf).strip()
    return meta, body
