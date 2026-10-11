"""语义级 roundtrip 保真指标(纯函数,零第三方依赖)。

回答"转换前后语义是否相同",补足字符级 F 指标(levenshtein 族)的盲区:
F 分数高只说明字面接近,S 分数低才暴露结构/关键约束语义的真丢失。

指标公式(本模块的 docstring 契约,实现不得偏离):

    S_struct = 0.4*steps + 0.3*know_jaccard + 0.2*name_eq + 0.1*desc_nonempty

        steps         = LCS(task 名序列) / max(len_in, len_out)
                        task 名先经 slugify 归一(大小写/空白/标点差不计);
                        两侧都无 tasks 时记 1.0
        know_jaccard  = |in∩out| / |in∪out|(knowledge 的 filename 集合;
                        两侧都空时记 1.0)
        name_eq       = slugify(ir_in.name) == slugify(ir_out.name) → 1.0/0.0
        desc_nonempty = ir_out.description 去空白后非空 → 1.0/0.0

    S_terms = 5 类"语义关键 token"保留率的等权平均;
              每类保留率 = |原集合 ∩ 回读集合| / |原集合|(原侧为空记 1.0)。

        token 从 ir_in.system_prompt 提取,在 ir_out.system_prompt 中查保留,
        每类内去重成集合。类别与正则:
          numbers       \\b\\d+(\\.\\d+)?%?\\b 及中文数字连串
                        [一二三四五六七八九十百千万亿]+(如 三 / 九 / 三十)
          qualifiers    at most / at least / no more than / 最多 / 至少 / 不超过
                        (忽略大小写,集合元素归一为小写)
          negation      do not / must not / not / never / no / 不要 / 禁止 / 不能
                        (忽略大小写,归一为小写;多词形态优先于单词)
          strong_cmd    must / should / always / 必须
                        (忽略大小写 —— 规格中单独列出的 MUST 由 ignorecase 覆盖)
          proper_nouns  连续大写缩写 \\b[A-Z]{2,}\\b 及已知框架名
                        CrewAI / LangChain / RAG / Flow / Langflow(区分大小写)

    semantic_metrics(ir_in, ir_out) 返回
        {"S_struct": float, "S_terms": float, "terms_detail": {...}};
    terms_detail 每类 {"score", "orig_count", "kept_count", "lost"}
    (lost 截前 10 个)供 loss 分析。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# 项目内导入(converter 属本项目,不算第三方依赖)
try:
    from converter.ir import AgentIR, slugify
except ImportError:  # pragma: no cover - 直接以脚本运行本文件时的兜底
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from converter.ir import AgentIR, slugify

__all__ = ["semantic_metrics", "s_struct", "s_terms"]

# --------------------------------------------------------------------------
# S_struct:结构等价
# --------------------------------------------------------------------------

def _lcs_len(a: List[str], b: List[str]) -> int:
    """最长公共子序列长度(经典双行 DP,纯 Python)。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            if x == y:
                cur.append(prev[j - 1] + 1)
            else:
                cur.append(max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """集合 Jaccard |a∩b|/|a∪b|;两侧都空记 1.0。"""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def s_struct(ir_in: AgentIR, ir_out: AgentIR) -> float:
    """S_struct = 0.4*steps + 0.3*know_jaccard + 0.2*name_eq + 0.1*desc_nonempty。

    steps 用 slugify 归一后的 task 名序列做 LCS / max(len),衡量步骤保序;
    其余三个分量衡量 name / 知识文件集 / description 的结构保真。
    """
    names_in = [slugify(t.name, fallback="") for t in ir_in.tasks]
    names_out = [slugify(t.name, fallback="") for t in ir_out.tasks]
    if not names_in and not names_out:
        steps = 1.0
    else:
        steps = _lcs_len(names_in, names_out) / max(len(names_in), len(names_out))
    know = _jaccard({d.filename for d in ir_in.knowledge},
                    {d.filename for d in ir_out.knowledge})
    name_eq = 1.0 if slugify(ir_in.name) == slugify(ir_out.name) else 0.0
    desc_nonempty = 1.0 if (ir_out.description or "").strip() else 0.0
    # round(...,10) 只消除 0.4+0.3+0.2+0.1 的二进制浮点噪声,不改变公式
    return round(0.4 * steps + 0.3 * know + 0.2 * name_eq + 0.1 * desc_nonempty, 10)


# --------------------------------------------------------------------------
# S_terms:术语保留
# --------------------------------------------------------------------------

_ZH_NUMERALS = "一二三四五六七八九十百千万亿"

#: 数字与量词:阿拉伯数字(可带小数/百分号)及中文数字连串
_NUM_RE = re.compile(r"\b\d+(\.\d+)?%?\b")
_ZH_NUM_RE = re.compile(f"[{_ZH_NUMERALS}]+")

#: 限定词 / 否定 / 强命令(英文忽略大小写,集合元素归一为小写)
_QUALIFIER_RE = re.compile(
    r"at most|at least|no more than|最多|至少|不超过", re.IGNORECASE
)
_NEGATION_RE = re.compile(
    r"\b(?:do not|must not|not|never|no)\b|不要|禁止|不能", re.IGNORECASE
)
_STRONG_RE = re.compile(r"\b(?:must|should|always)\b|必须", re.IGNORECASE)

#: 专有名词:连续大写缩写 + 已知框架名(区分大小写)
_PROPER_RE = re.compile(r"\b[A-Z]{2,}\b|\b(?:CrewAI|LangChain|RAG|Flow|Langflow)\b")

#: 类别顺序固定(terms_detail 键序与等权平均都按它)
TERM_CATEGORIES: Tuple[str, ...] = (
    "numbers", "qualifiers", "negation", "strong_cmd", "proper_nouns",
)


def _extract_terms(text: str) -> Dict[str, Set[str]]:
    """从一段文本提取 5 类语义关键 token 集合(类内去重)。"""
    return {
        "numbers": set(_NUM_RE.findall(text)) | set(_ZH_NUM_RE.findall(text)),
        "qualifiers": {m.lower() for m in _QUALIFIER_RE.findall(text)},
        "negation": {m.lower() for m in _NEGATION_RE.findall(text)},
        "strong_cmd": {m.lower() for m in _STRONG_RE.findall(text)},
        "proper_nouns": set(_PROPER_RE.findall(text)),
    }


def s_terms(text_in: str, text_out: str) -> Tuple[float, Dict[str, dict]]:
    """S_terms:原文本的语义关键 token 在回读文本中的保留率(公式见模块 docstring)。

    返回 (score, per_category);per_category 每类
    {"score", "orig_count", "kept_count", "lost"},便于 loss 分析。
    """
    cats_in = _extract_terms(text_in or "")
    cats_out = _extract_terms(text_out or "")
    detail: Dict[str, dict] = {}
    scores: List[float] = []
    for name in TERM_CATEGORIES:
        orig = cats_in[name]
        after = cats_out[name]
        kept = orig & after
        lost = sorted(orig - after)
        score = len(kept) / len(orig) if orig else 1.0
        scores.append(score)
        detail[name] = {
            "score": score,
            "orig_count": len(orig),
            "kept_count": len(kept),
            "lost": lost[:10],
        }
    return sum(scores) / len(scores), detail


# --------------------------------------------------------------------------
# 汇总入口
# --------------------------------------------------------------------------

def semantic_metrics(ir_in: AgentIR, ir_out: AgentIR) -> dict:
    """一次 roundtrip 的语义级指标(公式见模块 docstring)。

    返回 {"S_struct": float, "S_terms": float, "terms_detail": {...}}。
    纯函数:不修改入参、无 I/O、零第三方依赖。
    """
    struct = s_struct(ir_in, ir_out)
    terms, detail = s_terms(ir_in.system_prompt, ir_out.system_prompt)
    return {"S_struct": struct, "S_terms": terms, "terms_detail": detail}
