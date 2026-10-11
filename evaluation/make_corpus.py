"""合成测试集生成器:S2_cn(中文全量)与 S3_min(最小)→ evaluation/corpus/。

幂等:文件内容与目标字节完全一致时跳过写入(不刷 mtime),重复运行无副作用。

    S2_cn  SKILL.md(中文 description 约 80~110 字,含「」“”《》引号与顿号、
          正文含多级列表/代码块/引用块/emoji)+ references/ 两篇中文 md
          + agents/openai.yaml
    S3_min 仅 SKILL.md(frontmatter + 短正文,无 references 无 yaml)

用法:python3 evaluation/make_corpus.py [目录](默认 evaluation/corpus)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

CORPUS_ROOT = Path(__file__).resolve().parent / "corpus"

S2_NAME = "cn-agent-onboarding"
S3_NAME = "min-skill"

S2_SKILL_MD = """---
name: cn-agent-onboarding
description: 面向中文团队的 Agent 上手指南:覆盖「环境准备」、「提示词改写」与「评测基线」三类场景,当用户提到“新人入职”“国产生态”或需要 🔍 排查上线问题时使用;支持引用 references/ 中的术语表与演练手册,输出需遵循《交付清单》。
---

# 中文 Agent 上手指南

本技能用于带新人完成 Agent 项目的“第一周”:环境、提示词、评测三步走。多级清单如下:

- 第一步:环境准备
  - 安装 Python 3.13 与 `uv`(推荐)或 `pip`
    - 校验:`uv --version` 输出 ≥ 0.5
    - 国内镜像:`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`
  - 配置密钥环:写入 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`
- 第二步:提示词改写
  - 把“口语需求”改写成“结构化指令”
    - 模板:角色 + 边界 + 输出格式 + 验收标准
- 第三步:评测基线
  - 建立最小“黄金集”(≥ 20 条)
  - 跑通自动评分前,先做 ✅ 人工抽检

> 引用:师傅带徒弟的关键不是“讲全”,而是“盯着他把第一件事做完”。

示例脚本(注意引号与反斜杠的往返保真):

```python
import re

def normalize(text: str) -> str:
    \"\"\"把连续空白折叠成单个空格。\"\"\"
    return re.sub(r"\\s+", " ", text).strip()

print(normalize("  你好,\\t世界  "))  # 输出: 你好, 世界
```

emoji 压力位:🚀 开始、🧪 评测、📌 记录、⚠️ 回滚。

完成三步后,在《交付清单》上打勾并 @mentor 复核。
"""

S2_REF_GLOSSARY = """# 中文术语表

| 术语 | 含义 |
|---|---|
| 提示词 | 给模型的自然语言指令 |
| 黄金集 | 人工标注的评测样本集 |
| 渐进披露 | 只在需要时加载参考资料的模式 |

## 使用说明

查询术语时优先读本表;表内没有的,再用“英文原词”检索 references/cn-playbook.md。
"""

S2_REF_PLAYBOOK = """# 上线演练手册

## 演练步骤

1. 预发环境跑一轮「冒烟用例」
2. 核对日志中的 `trace_id` 是否连续
3. 出现 ⚠️ 告警时按《回滚预案》执行

## 回滚预案

> 宁可慢一分钟,不可带伤上线。

- 冻结发布窗口
- 执行 `git revert <merge-commit>`
- 在群里同步“影响面”与“恢复时间”
"""

S2_OPENAI_YAML = """interface:
  display_name: "CN Agent Onboarding"
  short_description: "中文团队的 Agent 上手指南(环境、提示词、评测)"
  default_prompt: "请按「三步走」带我完成第一周,并引用术语表解释“黄金集”"
"""

S3_SKILL_MD = """---
name: min-skill
description: 最小技能:仅 frontmatter 与短正文,验证基础往返保真。
---

# 最小技能

短正文:一行标题加一段话,无 references、无 agents yaml。
"""


def _write_if_changed(path: Path, content: str) -> str:
    """内容有差异才写盘(幂等);返回 'written' 或 'unchanged'。"""
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def make_s2(root: Path) -> Dict[str, str]:
    """生成 S2_cn(中文全量:SKILL.md + references×2 + agents/openai.yaml)。"""
    base = root / "S2_cn"
    return {
        "S2_cn/SKILL.md": _write_if_changed(base / "SKILL.md", S2_SKILL_MD),
        "S2_cn/references/cn-glossary.md": _write_if_changed(
            base / "references" / "cn-glossary.md", S2_REF_GLOSSARY),
        "S2_cn/references/cn-playbook.md": _write_if_changed(
            base / "references" / "cn-playbook.md", S2_REF_PLAYBOOK),
        "S2_cn/agents/openai.yaml": _write_if_changed(
            base / "agents" / "openai.yaml", S2_OPENAI_YAML),
    }


def make_s3(root: Path) -> Dict[str, str]:
    """生成 S3_min(仅 SKILL.md)。"""
    base = root / "S3_min"
    return {
        "S3_min/SKILL.md": _write_if_changed(base / "SKILL.md", S3_SKILL_MD),
    }


def ensure_all(root: Path = CORPUS_ROOT) -> Dict[str, str]:
    """幂等生成全部合成 corpus,返回 {相对路径: written|unchanged}。"""
    report: Dict[str, str] = {}
    report.update(make_s2(root))
    report.update(make_s3(root))
    return report


def main(argv: list) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else CORPUS_ROOT
    report = ensure_all(root)
    written = sum(1 for v in report.values() if v == "written")
    print(f"corpus root: {root}")
    for rel, status in sorted(report.items()):
        print(f"  [{status:>10}] {rel}")
    print(f"done: {written} written, {len(report) - written} unchanged (幂等)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
