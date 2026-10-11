"""评测入口:3 corpus × 8 target 的 forward + roundtrip 全矩阵。

    python3 evaluation/run_eval.py [--out evaluation/results]

forward   :emit → V_format 静态校验(失分记入该行 L)
roundtrip :emit → parse(PARSERS 对应键;缺键标 parser-missing,不崩)
            → write_skill → load_skill → F_name/F_desc/F_prompt/F_know_q/F_know_c
            + S_struct/S_terms(语义级,公式见 semantics.py;terms_detail 记入结果行)+ L

产物:
    <out>/results.json  逐条目含指标与 L
    <out>/results.md    汇总表(行=target,列=各指标均值+总样本数)+ Loss 频次表
    stdout              摘要表

roundtrip parse 入口(契约):crewai=产物根, crewai-skills=产物根,
deepagents=产物根, langchain=agent.py, langflow=flow.json, openai=产物根,
claude-subagent=产物根, generic=agent.json。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT))      # converter 包
sys.path.insert(0, str(EVAL_DIR))  # metrics / make_corpus

import metrics as M  # noqa: E402
import semantics as S  # noqa: E402
import make_corpus  # noqa: E402

from converter.ir import AgentIR  # noqa: E402
from converter.skill_loader import load_skill  # noqa: E402
from converter.skill_writer import write_skill  # noqa: E402

try:
    from converter.emitters import EMITTERS
except Exception:  # pragma: no cover - 并行线程未落盘
    EMITTERS = {}
try:
    from converter.parsers import PARSERS
except Exception:  # pragma: no cover - 并行线程未落盘
    PARSERS = {}

TARGETS = ["crewai", "crewai-skills", "deepagents", "langchain",
           "langflow", "openai", "claude-subagent", "generic", "autogen",
           "n8n", "mermaid-workflow"]

CORPORA: List[Tuple[str, Path]] = [
    ("S1_real", ROOT / "examples" / "agent-fullcycle-engineering"),
    ("S2_cn", EVAL_DIR / "corpus" / "S2_cn"),
    ("S3_min", EVAL_DIR / "corpus" / "S3_min"),
]

# roundtrip parse 入口(契约见模块 docstring)
_PARSER_ENTRY_FILE = {
    "langchain": "agent.py",
    "langflow": "flow.json",
    "generic": "agent.json",
    "autogen": "agent.py",
    "n8n": "workflow.json",
    "mermaid-workflow": "workflow.md",
}

# PARSERS 对应键(含可能的命名变体;全部缺失 → parser-missing)
_PARSER_KEYS: Dict[str, Tuple[str, ...]] = {
    "crewai": ("crewai",),
    "crewai-skills": ("crewai-skills", "crewai_skills"),
    "deepagents": ("deepagents",),
    "langchain": ("langchain",),
    "langflow": ("langflow",),
    "openai": ("openai", "openai_agents"),
    "claude-subagent": ("claude-subagent", "claude_subagent"),
    "generic": ("generic",),
    "autogen": ("autogen",),
    "n8n": ("n8n",),
    "mermaid-workflow": ("mermaid-workflow", "mermaid_workflow"),
}

# 汇总列:5 个字符级 F 指标 + 2 个语义级 S 指标(evaluation/semantics.py)
F_KEYS = ["F_name", "F_desc", "F_prompt", "F_know_q", "F_know_c",
          "S_struct", "S_terms"]


# --------------------------------------------------------------------------
# 矩阵执行
# --------------------------------------------------------------------------

def _parser_entry(target: str, agent_dir: Path) -> Path:
    """按契约返回 parse 入口路径。"""
    filename = _PARSER_ENTRY_FILE.get(target)
    return agent_dir / filename if filename else agent_dir


def _find_parser(target: str) -> Tuple[Optional[Any], Optional[str]]:
    """查 PARSERS 对应键;返回 (parser, 使用的键)。缺键返回 (None, None)。"""
    for key in _PARSER_KEYS[target]:
        fn = PARSERS.get(key)
        if callable(fn):
            return fn, key
    return None, None


def run_matrix(work: Path) -> Tuple[List[dict], List[dict], Dict[str, str]]:
    """跑全矩阵,返回 (forward_rows, roundtrip_rows, corpus_notes)。"""
    forward_rows: List[dict] = []
    roundtrip_rows: List[dict] = []
    notes: Dict[str, str] = {}

    corpora: List[Tuple[str, Path]] = []
    for corpus_id, path in CORPORA:
        if (path / "SKILL.md").is_file():
            corpora.append((corpus_id, path))
        else:
            notes[corpus_id] = f"skipped: corpus 不存在或缺 SKILL.md({path})"

    for corpus_id, corpus_dir in corpora:
        try:
            ir_in = load_skill(corpus_dir)
        except Exception as exc:  # noqa: BLE001 - corpus 坏则整行标注
            notes[corpus_id] = f"skipped: load_skill 失败({exc})"
            continue

        for target in TARGETS:
            agent_dir = work / corpus_id / target
            skill_dir = work / corpus_id / f"{target}.skill"

            # ---- forward:emit + V_format ----
            frow: Dict[str, Any] = {"corpus": corpus_id, "target": target,
                                    "v_format": 0, "v_reasons": [], "error": None, "L": []}
            emit_fn = EMITTERS.get(target)
            if emit_fn is None:
                frow["error"] = "emitter-missing"
                frow["v_reasons"] = [f"EMITTERS 缺键 {target!r}"]
            else:
                try:
                    emit_fn(ir_in, agent_dir)
                except Exception as exc:  # noqa: BLE001
                    frow["error"] = f"emit-error: {exc}"
                    frow["v_reasons"] = [f"emit 失败: {exc}"]
                else:
                    frow["v_format"], frow["v_reasons"] = M.validate_forward(target, agent_dir)
            if frow["v_format"] == 0:
                frow["L"].append({"field": "v_format", "kind": "vformat-fail",
                                  "reason": "; ".join(frow["v_reasons"])[:300]})
            forward_rows.append(frow)

            # ---- roundtrip:parse → write → load ----
            rrow: Dict[str, Any] = {"corpus": corpus_id, "target": target,
                                    "status": "ok", "metrics": None, "L": [], "error": None}
            roundtrip_rows.append(rrow)

            def _fail(status: str, field: str, kind: str, reason: str) -> None:
                rrow["status"] = status
                rrow["error"] = reason
                rrow["L"].append({"field": field, "kind": kind, "reason": reason})

            if frow["error"] == "emitter-missing":
                _fail("emitter-missing", "emit", "emitter-missing",
                      f"EMITTERS 缺键 {target!r},无 forward 产物")
                continue
            if frow["error"]:
                _fail("error", "emit", "emit-error", frow["error"])
                continue

            parser, used_key = _find_parser(target)
            if parser is None:
                _fail("parser-missing", "parser", "parser-missing",
                      f"PARSERS 缺键 {list(_PARSER_KEYS[target])}(并行线程未落盘)")
                continue

            try:
                ir_mid = parser(_parser_entry(target, agent_dir))
            except Exception as exc:  # noqa: BLE001
                _fail("error", "parse", "parse-error", f"{used_key}: {exc}")
                continue

            try:
                write_skill(ir_mid, skill_dir, copy_scripts_from=corpus_dir)
            except Exception as exc:  # noqa: BLE001
                _fail("error", "write", "write-error", f"write_skill: {exc}")
                continue

            ok, why = M.validate_skill_dir(skill_dir)
            if not ok:
                rrow["L"].append({"field": "skill_out", "kind": "skill-md-invalid",
                                  "reason": "; ".join(why)[:300]})

            try:
                ir_out = load_skill(skill_dir)
            except Exception as exc:  # noqa: BLE001
                _fail("error", "load", "load-error", f"load_skill: {exc}")
                continue

            m, losses = M.roundtrip_metrics(ir_in, ir_out)
            sem = S.semantic_metrics(ir_in=ir_in, ir_out=ir_out)
            m["S_struct"] = sem["S_struct"]
            m["S_terms"] = sem["S_terms"]
            rrow["metrics"] = m
            rrow["terms_detail"] = sem["terms_detail"]
            rrow["L"].extend(losses)

    return forward_rows, roundtrip_rows, notes


# --------------------------------------------------------------------------
# 汇总与落盘
# --------------------------------------------------------------------------

def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def summarize(forward_rows: List[dict], roundtrip_rows: List[dict]) -> Dict[str, Any]:
    """每 target 的指标均值(3 corpus 平均;parser-missing/error 行不计入 F)、
    全局均值、L 去重频次。"""
    per_target: Dict[str, Dict[str, Any]] = {}
    for target in TARGETS:
        frows = [r for r in forward_rows if r["target"] == target]
        rrows = [r for r in roundtrip_rows if r["target"] == target and r["status"] == "ok"]
        entry: Dict[str, Any] = {k: _mean([r["metrics"][k] for r in rrows]) for k in F_KEYS}
        entry["V_format"] = _mean([float(r["v_format"]) for r in frows])
        entry["roundtrip_samples"] = len(rrows)
        entry["forward_samples"] = len(frows)
        per_target[target] = entry

    all_ok = [r for r in roundtrip_rows if r["status"] == "ok"]
    glob = {k: _mean([r["metrics"][k] for r in all_ok]) for k in F_KEYS}
    glob["V_format"] = _mean([float(r["v_format"]) for r in forward_rows])
    glob["roundtrip_samples"] = len(all_ok)
    glob["forward_samples"] = len(forward_rows)

    counter: Counter = Counter()
    example: Dict[Tuple[str, str], str] = {}
    for row in forward_rows:
        for item in row["L"]:
            key = (item["field"], item["kind"])
            counter[key] += 1
            example.setdefault(key, item["reason"])
    for row in roundtrip_rows:
        for item in row["L"]:
            key = (item["field"], item["kind"])
            counter[key] += 1
            example.setdefault(key, item["reason"])

    loss_freq = [
        {"field": field, "kind": kind, "count": count, "example": example[(field, kind)][:200]}
        for (field, kind), count in counter.most_common()
    ]
    return {"per_target": per_target, "global": glob, "loss_freq": loss_freq}


def _fmt(value: Optional[float]) -> str:
    return "parser-missing" if value is None else f"{value:.4f}"


def build_markdown(summary: Dict[str, Any], notes: Dict[str, str], run_date: str) -> str:
    """results.md:汇总表 + Loss 频次表(parser-missing 行在表中显式标注)。"""
    lines: List[str] = []
    lines.append("# agentskills-bridge 评测基线")
    lines.append("")
    lines.append(f"- 运行日期:{run_date}")
    lines.append("- 矩阵:3 corpus(S1_real / S2_cn / S3_min)× 8 target;")
    lines.append("  forward = emit + V_format 静态校验;roundtrip = emit → parse → write_skill → load_skill 后的 F 指标。")
    lines.append("- F 列为 roundtrip 有效行均值(总样本数见 n;parser-missing/error 行不计入);V_format 为 forward 3 行均值。")
    if notes:
        lines.append("- corpus 备注:" + ";".join(f"{k} {v}" for k, v in notes.items()))
    lines.append("")
    lines.append("## 汇总表")
    lines.append("")
    header = ["target", "F_name", "F_desc", "F_prompt", "F_know_q", "F_know_c",
              "S_struct", "S_terms", "V_format", "n"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for target in TARGETS:
        e = summary["per_target"][target]
        row = [target] + [_fmt(e[k]) for k in F_KEYS] + [f"{e['V_format']:.4f}", str(e["roundtrip_samples"])]
        if e["F_name"] is None:
            row[1] = "parser-missing"
        lines.append("| " + " | ".join(row) + " |")
    g = summary["global"]
    lines.append("| **全局均值** | " + " | ".join(
        [f"{g[k]:.4f}" if g[k] is not None else "-" for k in F_KEYS]
        + [f"{g['V_format']:.4f}", str(g["roundtrip_samples"])]) + " |")
    lines.append("")
    lines.append("## Top Loss points 频次(L 去重统计)")
    lines.append("")
    lines.append("| field | kind | count | 典型原因 |")
    lines.append("|---|---|---|---|")
    if summary["loss_freq"]:
        for item in summary["loss_freq"][:20]:
            reason = item["example"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {item['field']} | {item['kind']} | {item['count']} | {reason} |")
    else:
        lines.append("| (无) | | 0 | |")
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="skill↔agent 双向转换保真度评测")
    parser.add_argument("--out", default=str(EVAL_DIR / "results"),
                        help="结果目录(默认 evaluation/results)")
    args = parser.parse_args()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    corpus_report = make_corpus.ensure_all()
    run_date = date.today().isoformat()

    with tempfile.TemporaryDirectory(prefix="skills-eval-") as tmp:
        forward_rows, roundtrip_rows, notes = run_matrix(Path(tmp))

    summary = summarize(forward_rows, roundtrip_rows)

    results = {
        "meta": {
            "run_date": run_date,
            "matrix": {"corpora": [c for c, _ in CORPORA], "targets": TARGETS},
            "corpus_notes": notes,
            "corpus_files": corpus_report,
            "parsers_available": sorted(PARSERS.keys()),
            "emitters_available": sorted(EMITTERS.keys()),
            "metrics_formulas": {
                "F_name": "slugify(name) 相等 → 1.0/0.0",
                "F_desc": "归一(strip+换行→空格)相等 → 1.0,否则 1 - levenshtein/max(len)",
                "F_prompt": "归一(strip+\\r\\n→\\n)相等 → 1.0,否则 1 - levenshtein/max(len)",
                "F_know_q": "len(out.knowledge)/len(in.knowledge),in=0 → 1.0",
                "F_know_c": "sha256 内容一致的 knowledge 数/len(in.knowledge),in=0 → 1.0",
                "S_struct": "0.4*steps(LCS/max) + 0.3*know Jaccard + 0.2*slug name 相等 + 0.1*desc 非空",
                "S_terms": "5 类语义关键 token(数字/限定词/否定/强命令/专有名词)保留率等权平均",
                "V_format": "forward 产物静态校验,通过=1 否则=0(附原因)",
            },
        },
        "forward": forward_rows,
        "roundtrip": roundtrip_rows,
        "summary": summary,
    }
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = build_markdown(summary, notes, run_date)
    (out_dir / "results.md").write_text(md + "\n", encoding="utf-8")

    # stdout 摘要表
    print(md)
    print(f"results: {out_dir / 'results.json'}")
    print(f"results: {out_dir / 'results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
