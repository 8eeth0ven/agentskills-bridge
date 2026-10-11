---
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
    """把连续空白折叠成单个空格。"""
    return re.sub(r"\s+", " ", text).strip()

print(normalize("  你好,\t世界  "))  # 输出: 你好, 世界
```

emoji 压力位:🚀 开始、🧪 评测、📌 记录、⚠️ 回滚。

完成三步后,在《交付清单》上打勾并 @mentor 复核。
