"""外部真实 corpus 泛化测试(全部输入来自第三方,非本项目 emitter 产物)。

    python3 evaluation/external/run_external.py --corpus-root <corpus> [--out-dir <results>]

数据流(两个方向):
  agent→skill(真实 agent 输入)
      4 个 crewAI-examples 项目(PARSERS["crewai"],传项目根自动探测 src/config/)
      4 个 langflow 官方 fixture flow(3 个 v1.9.0 starter + 1 个 v1.6.0 无
      Prompt 节点的 Agent flow,覆盖回退链)
      3 个真实 Claude Code subagent(wshobson/agents,临时组装 .claude/agents/)
      → parse → 记录 name/display_name/description 长度/system_prompt 长度/
      tasks 数/knowledge 数/traceback → write_skill → validate → load_skill 回读
  skill→agent(真实 skill 输入)
      3 个 anthropics/skills(docx / pdf / pptx)
      → load_skill → 全部 EMITTERS 键逐个 emit → V_format 静态校验
      → crewai / langflow / claude-subagent / generic 四链 parse 回
      → F_name/F_desc/F_prompt(复用 evaluation/metrics.py)

产物:默认写入 evaluation/external/latest/；历史 results.json/results.md 保留。
语料须由调用者明确指定，不自动查找本机 clone。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EVAL_DIR = Path(__file__).resolve().parent          # evaluation/external
ROOT = EVAL_DIR.parent.parent                        # 项目根
sys.path.insert(0, str(ROOT))                        # converter 包
sys.path.insert(0, str(ROOT / "evaluation"))         # metrics

import metrics as M  # noqa: E402

from converter.emitters import EMITTERS  # noqa: E402
from converter.parsers import PARSERS  # noqa: E402
from converter.skill_loader import load_skill  # noqa: E402
from converter.skill_writer import write_skill  # noqa: E402

RUN_DATE = date.today().isoformat()

# --------------------------------------------------------------------------
# 真实输入清单(全部第三方仓库;缺失时该行标 missing,不崩)
# --------------------------------------------------------------------------

CREWAI_PROJECTS: List[Tuple[str, Path]] = [
    ("game-builder-crew", Path("crewai-examples") / "crews" / "game-builder-crew"),
    ("landing_page_generator", Path("crewai-examples") / "crews" / "landing_page_generator"),
    ("marketing_strategy", Path("crewai-examples") / "crews" / "marketing_strategy"),
    ("recruitment", Path("crewai-examples") / "crews" / "recruitment"),
]

SKILL_DIRS: List[Tuple[str, Path]] = [
    ("docx", Path("anthropic-skills") / "skills" / "docx"),
    ("pdf", Path("anthropic-skills") / "skills" / "pdf"),
    ("pptx", Path("anthropic-skills") / "skills" / "pptx"),
]

LANGFLOW_FLOWS: List[Tuple[str, Path]] = [
    ("basic_prompting@1.9.0", Path("langflow-repo") / "src" / "lfx" / "tests"
        / "fixtures" / "starter_flows" / "v1.9.0" / "basic_prompting.json"),
    ("research_agent@1.9.0", Path("langflow-repo") / "src" / "lfx" / "tests"
        / "fixtures" / "starter_flows" / "v1.9.0" / "research_agent.json"),
    ("meeting_summary@1.9.0", Path("langflow-repo") / "src" / "lfx" / "tests"
        / "fixtures" / "starter_flows" / "v1.9.0" / "meeting_summary.json"),
    ("pokedex_agent@1.6.0", Path("langflow-repo") / "src" / "lfx" / "tests"
        / "data" / "starter_projects_1_6_0" / "Pokédex Agent.json"),
]

# 真实 Claude Code subagent(wshobson/agents 集合),组装成 .claude/agents/ 目录
SUBAGENT_SOURCES: List[Tuple[str, Path]] = [
    ("backend-architect", Path("wshobson-agents") / "plugins"
        / "backend-development" / "agents" / "backend-architect.md"),
    ("eval-judge", Path("wshobson-agents") / "plugins"
        / "plugin-eval" / "agents" / "eval-judge.md"),
    ("image-generator", Path("wshobson-agents") / "plugins"
        / "meigen-ai-design" / "agents" / "image-generator.md"),
]

# skill→agent 四条回读链(target → parse 入口;与 evaluation/run_eval.py 一致)
BACK_CHAINS: Dict[str, str] = {
    "crewai": "root",
    "langflow": "flow.json",
    "claude-subagent": "root",
    "generic": "agent.json",
}

# 兼容修复记录(真实格式 → 修的兼容点;与 parser 代码同步维护)
COMPAT_NOTES: List[Tuple[str, str]] = [
    ("crewai: 真实项目模板路径是 src/<pkg>/config/agents.yaml 且包名 ≠ 项目目录名"
     "(game-builder-crew → src/game_builder_crew/config/),原探测只到 src/config/",
     "crewai.py _candidates 增加 sorted((root/src).glob('*/config/agents.yaml')) 兜底;"
     "首跑 4/4 项目 FileNotFoundError,修后 4/4 通过"),
    ("crewai: 多 agent 文件(真实项目每文件 3-4 个 agent)",
     "parse_crewai 仍取第一个,metadata 新增 agents_all(全部 agent 名)+ agents_count,"
     "不静默丢弃(首跑后已验证 marketing_strategy 4 agent 全记录)"),
    ("crewai: agents.yaml 未知字段(llm:/tools:/knowledge_sources: 等;真实仓库当前"
     "仅 role/goal/backstory,防御性兼容)、> 折叠块内带引号与 {var} 占位"
     "(landing_page_generator)",
     "白名单 agent.get 取值,未知字段静默忽略(原有行为,保持);pyyaml 天然支持折叠块,"
     "_minimal_yaml_load 容错路径不变"),
    ("langflow: 无 Prompt 节点的 Agent flow(官方 starter \"Pokédex Agent\"@1.6.0,"
     "system_prompt 在 Agent 组件 template.system_prompt.value)",
     "_extract_system_prompt 新增优先级③ Agent 组件 system_prompt(≥20 字符);"
     "原模糊回退(>50 字符)降为④;新增⑤ Note 组件文本兜底(noteNode)"),
    ("langflow: 1.9+ LLM 组件 model_name 是覆盖名常为空,模型在 model 字段(ModelInput)",
     "_extract_model 每键依次尝试 model_name → model,取第一个非空 value"),
    ("claude-subagent: tools 为行内逗号串或单值(eval-judge.md `tools: Read, Grep, Glob`;"
     "image-generator.md `tools: mcp__meigen__generate_image`),原解析只得 []",
     "_parse_tools_list 增加行内无方括号分支(逗号切分 + 单值),修后 tools=3 / tools=1"),
    ("claude-subagent: description 用 >- 折叠块(image-generator.md),"
     "ir.parse_frontmatter 把块标记拼进值形成 \">- \" 脏前缀",
     "claude_subagent.py 新增 _clean_scalar 剥离块标量前缀(|/>/-/|-/+/数字指示符);"
     "ir.py 按契约不可改,在 parser 层修"),
    ("claude-subagent: 双引号标量值内含 \\\" 转义(anthropics/skills pptx 的 "
     "description 含 \\\"deck,\\\" \\\"slides,\\\"),parser 不做 YAML 反转义,"
     "每过一轮 emitter→parser 漂移一层(\\\" → \\\\\\\"),F_desc=0.9840",
     "_clean_scalar 叠加 _yaml_unescape(\\\\ → \\、\\\" → \"、\\n → 换行,单趟扫描);"
     "修后该链 F_desc 0.9840 → 1.0000,四链 12/12 满分"),
    ("claude-subagent: frontmatter 额外键(color: magenta 等)与缺失可选键"
     "(backend-architect.md 无 tools)",
     "平面提取天然容忍:额外键忽略、缺失键空值,不崩(原有行为,保持)"),
]


def _tb_first(exc: BaseException, corpus_root: Path, work: Path) -> str:
    """异常摘要:traceback 首行 + 异常类型与消息。"""
    tb = traceback.extract_tb(exc.__traceback__)
    if tb:
        try:
            source = Path(tb[0].filename).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            source = Path(tb[0].filename).name
        first = f"{source}:{tb[0].lineno} in {tb[0].name}"
    else:
        first = ""
    message = str(exc)
    replacements = ((str(ROOT.resolve()), "<project>"),
                    (str(corpus_root.resolve()), "<corpus>"),
                    (str(work.resolve()), "<work>"))
    for private, public in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        message = message.replace(private, public)
    return f"{first}: {type(exc).__name__}: {message}"[:300]


def assemble_subagents(corpus_root: Path, work: Path) -> List[Tuple[str, Path]]:
    """把真实 subagent md 组装成 parse_claude_subagent 需要的目录形态。

    <work>/assembled/<key>/.claude/agents/<原名>.md
    """
    out: List[Tuple[str, Path]] = []
    for key, relative in SUBAGENT_SOURCES:
        src = corpus_root / relative
        if not src.is_file():
            continue
        dst_dir = work / "assembled" / key / ".claude" / "agents"
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        shutil.copy2(src, dst)
        out.append((key, dst_dir.parent.parent))
    return out


# --------------------------------------------------------------------------
# Stage A:agent→skill(真实 agent 输入)
# --------------------------------------------------------------------------

def run_agent_to_skill(work: Path, corpus_root: Path) -> List[dict]:
    rows: List[dict] = []
    inputs: List[Tuple[str, str, Path]] = []
    for key, path in CREWAI_PROJECTS:
        inputs.append((key, "crewai", corpus_root / path))
    for key, path in LANGFLOW_FLOWS:
        inputs.append((key, "langflow", corpus_root / path))
    for key, path in assemble_subagents(corpus_root, work):
        inputs.append((key, "claude-subagent", path))

    for key, fmt, path in inputs:
        row: Dict[str, Any] = {
            "input": key, "format": fmt, "exists": path.exists(),
            "parse_ok": False, "error": None,
            "name": "", "display_name": "", "desc_len": 0,
            "system_prompt_len": 0, "tasks": 0, "knowledge": 0,
            "agents_all": None,
            "write_load_ok": False, "write_load_error": None,
            "tools": 0,
        }
        rows.append(row)
        if not path.exists():
            row["error"] = "missing-input"
            continue
        if not PARSERS.get(fmt):
            row["error"] = f"parser-missing:{fmt}"
            continue
        try:
            ir = PARSERS[fmt](path)
        except Exception as exc:  # noqa: BLE001 - 真实输入的任何异常都记录
            row["error"] = _tb_first(exc, corpus_root, work)
            continue
        row.update(
            parse_ok=True,
            name=ir.name, display_name=ir.display_name,
            desc_len=len(ir.description or ""),
            system_prompt_len=len(ir.system_prompt or ""),
            tasks=len(ir.tasks), knowledge=len(ir.knowledge),
            tools=len(ir.tools),
            agents_all=ir.metadata.get("agents_all"),
        )
        # 写出 skill 目录再回读
        skill_dir = work / "a2s" / f"{fmt}-{key}.skill"
        try:
            write_skill(ir, skill_dir)
            ok, _why = M.validate_skill_dir(skill_dir)
            if not ok:
                raise ValueError(f"SKILL.md 校验失败: {_why}")
            ir2 = load_skill(skill_dir)
            if not ir2.name:
                raise ValueError("回读 name 为空")
        except Exception as exc:  # noqa: BLE001
            row["write_load_error"] = _tb_first(exc, corpus_root, work)
            continue
        row["write_load_ok"] = True
    return rows


# --------------------------------------------------------------------------
# Stage B:skill→agent(真实 skill 输入)
# --------------------------------------------------------------------------

def run_skill_to_agent(work: Path, corpus_root: Path) -> Tuple[List[dict], List[dict]]:
    forward_rows: List[dict] = []
    back_rows: List[dict] = []

    for key, relative in SKILL_DIRS:
        skill_dir = corpus_root / relative
        if not (skill_dir / "SKILL.md").is_file():
            forward_rows.append({"skill": key, "target": "-", "v_format": 0,
                                 "error": "missing-input", "L": []})
            continue
        try:
            ir_in = load_skill(skill_dir)
        except Exception as exc:  # noqa: BLE001
            forward_rows.append({"skill": key, "target": "-", "v_format": 0,
                                 "error": f"load-error: {_tb_first(exc, corpus_root, work)}", "L": []})
            continue

        for target, emit_fn in EMITTERS.items():
            agent_dir = work / "s2a" / key / target
            frow: Dict[str, Any] = {"skill": key, "target": target,
                                    "v_format": 0, "v_reasons": [], "error": None, "L": []}
            forward_rows.append(frow)
            try:
                emit_fn(ir_in, agent_dir)
            except Exception as exc:  # noqa: BLE001
                frow["error"] = f"emit-error: {_tb_first(exc, corpus_root, work)}"
                frow["v_reasons"] = [frow["error"]]
            else:
                frow["v_format"], frow["v_reasons"] = M.validate_forward(target, agent_dir)
            if frow["v_format"] == 0:
                frow["L"].append({"field": "v_format", "kind": "vformat-fail",
                                  "reason": "; ".join(frow["v_reasons"])[:300]})

            # 四链 parse 回:仅对链匹配的 emitter 产物(crewai 产物用 crewai
            # parser 读回,依此类推;其余 target 不属于本任务的四链范围)
            if target not in dict(BACK_CHAINS):
                continue
            entry = dict(BACK_CHAINS)[target]
            brow: Dict[str, Any] = {"skill": key, "target": target, "chain": target,
                                    "status": "ok", "F_name": None, "F_desc": None,
                                    "F_prompt": None, "error": None}
            back_rows.append(brow)
            if frow["error"] is not None:
                brow["status"] = "emit-failed"
                brow["error"] = frow["error"]
                continue
            parser = PARSERS.get(target)
            if parser is None:
                brow["status"] = "parser-missing"
                brow["error"] = f"PARSERS 缺键 {target}"
                continue
            entry_path = agent_dir / entry if entry != "root" else agent_dir
            try:
                ir_mid = parser(entry_path)
            except Exception as exc:  # noqa: BLE001
                brow["status"] = "parse-error"
                brow["error"] = _tb_first(exc, corpus_root, work)
                continue
            brow["F_name"] = M.f_name(ir_in, ir_mid)
            brow["F_desc"] = M.f_desc(ir_in, ir_mid)
            brow["F_prompt"] = M.f_prompt(ir_in, ir_mid)
    return forward_rows, back_rows


# --------------------------------------------------------------------------
# 汇总与落盘
# --------------------------------------------------------------------------

def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def build_markdown(a_rows: List[dict], fwd: List[dict], back: List[dict]) -> str:
    lines: List[str] = []
    lines.append("# 外部真实 corpus 泛化测试(2026-10-11)")
    lines.append("")
    lines.append("输入全部来自第三方仓库(crewAIInc/crewAI-examples、anthropics/skills、")
    lines.append("langflow-ai/langflow 官方 fixtures、wshobson/agents 真实 subagents),")
    lines.append("无一份由本项目 emitter 生成 —— 针对「corpus 同源」威胁的正面测试。")
    lines.append("")

    # ---- Stage A ----
    total = [r for r in a_rows if r["exists"]]
    ok = [r for r in total if r["parse_ok"]]
    wl = [r for r in ok if r["write_load_ok"]]
    lines.append("## Stage A:agent→skill(真实 agent 输入 → parse → write_skill → load_skill)")
    lines.append("")
    lines.append(f"- parse 成功率:**{len(ok)}/{len(total)}**;"
                 f"write+load 回读成功:**{len(wl)}/{len(ok)}**")
    lines.append("")
    lines.append("| 输入 | 格式 | parse | name | display_name | desc_len | prompt_len | tasks | knowledge | tools | agents_all | write+load |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in a_rows:
        agents_all = ",".join(r["agents_all"]) if r["agents_all"] else "-"
        wl_txt = "ok" if r["write_load_ok"] else (r["write_load_error"] or "-")[:60]
        parse_txt = "ok" if r["parse_ok"] else (r["error"] or "-")[:60]
        lines.append(
            f"| {r['input']} | {r['format']} | {parse_txt} | {r['name']} | "
            f"{r['display_name']} | {r['desc_len']} | {r['system_prompt_len']} | "
            f"{r['tasks']} | {r['knowledge']} | {r['tools']} | {agents_all} | {wl_txt} |")
    lines.append("")

    # ---- Stage B forward ----
    lines.append("## Stage B:skill→agent(anthropics/skills 真实 skill × 全部 emitter)")
    lines.append("")
    fv = [r for r in fwd if r["target"] != "-"]
    v_pass = [r for r in fv if r["v_format"] == 1]
    lines.append(f"- V_format 通过:**{len(v_pass)}/{len(fv)}**"
                 f"(emitter 键 {len(EMITTERS)} 个 × skill {len(SKILL_DIRS)} 个)")
    lines.append("")
    lines.append("| skill | target | V_format | 失败原因 |")
    lines.append("|---|---|---|---|")
    for r in fwd:
        if r["target"] == "-":
            lines.append(f"| {r['skill']} | - | 0 | {r['error']} |")
            continue
        reason = "; ".join(r["v_reasons"]).replace("|", "\\|").replace("\n", " ")[:160] if r["v_format"] == 0 else ""
        lines.append(f"| {r['skill']} | {r['target']} | {r['v_format']} | {reason} |")
    lines.append("")

    # ---- Stage B back chains ----
    valid = [r for r in back if r["status"] == "ok"]
    lines.append("### 四链 parse 回(F vs load_skill 的 ir_in)")
    lines.append("")
    for metric in ("F_name", "F_prompt", "F_desc"):
        vals = [r[metric] for r in valid if r[metric] is not None]
        perfect = sum(1 for v in vals if v == 1.0)
        lines.append(f"- {metric}:均值 {_mean(vals) if vals else '-'},"
                     f"满分 {perfect}/{len(vals)}")
    lines.append("")
    lines.append("| skill | target→chain | 状态 | F_name | F_prompt | F_desc | 原因 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in back:
        fmt_v = lambda v: "-" if v is None else f"{v:.4f}"  # noqa: E731
        reason = (r["error"] or "").replace("|", "\\|")[:120]
        lines.append(
            f"| {r['skill']} | {r['target']}→{r['chain']} | {r['status']} | "
            f"{fmt_v(r['F_name'])} | {fmt_v(r['F_prompt'])} | {fmt_v(r['F_desc'])} | {reason} |")
    lines.append("")

    # ---- 兼容修复记录 ----
    lines.append("## 发现的真实格式 → 修的兼容点")
    lines.append("")
    lines.append("| 真实格式(第三方仓库) | 兼容点(parser 改动)|")
    lines.append("|---|---|")
    for found, fix in COMPAT_NOTES:
        lines.append(f"| {found.replace('|', '\\|')} | {fix.replace('|', '\\|')} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True,
                        help="Directory containing crewai-examples, anthropic-skills, langflow-repo and wshobson-agents")
    parser.add_argument("--out-dir", type=Path, default=EVAL_DIR / "latest",
                        help="Fresh results directory; historical reports are not overwritten by default")
    args = parser.parse_args()
    if not args.corpus_root.is_dir():
        parser.error("--corpus-root must be an existing corpus directory")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ext-eval-") as tmp:
        work = Path(tmp)
        a_rows = run_agent_to_skill(work, args.corpus_root)
        fwd, back = run_skill_to_agent(work, args.corpus_root)

    results = {
        "meta": {
            "run_date": RUN_DATE,
            "design": "外部真实 corpus 泛化测试:输入全部来自第三方仓库,非本项目 emitter 产物",
            "sources": {
                "crewai": "github.com/crewAIInc/crewAI-examples(4 项目)",
                "skills": "github.com/anthropics/skills(docx/pdf/pptx)",
                "langflow": "github.com/langflow-ai/langflow 官方 fixtures(3×v1.9.0 + 1×v1.6.0 无 Prompt)",
                "claude-subagents": "github.com/wshobson/agents(3 个真实 .claude 形态 subagent)",
            },
            "emitter_keys": sorted(EMITTERS.keys()),
            "parser_keys": sorted(PARSERS.keys()),
            "compat_notes": [{"found": f, "fix": fx} for f, fx in COMPAT_NOTES],
        },
        "agent_to_skill": a_rows,
        "skill_to_agent_forward": fwd,
        "skill_to_agent_back": back,
    }
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = build_markdown(a_rows, fwd, back)
    (out_dir / "results.md").write_text(md + "\n", encoding="utf-8")

    total = [r for r in a_rows if r["exists"]]
    ok = [r for r in total if r["parse_ok"]]
    print(md)
    print(f"results: {out_dir / 'results.json'}")
    print(f"results: {out_dir / 'results.md'}")
    return 0 if len(ok) == len(total) else 1


if __name__ == "__main__":
    raise SystemExit(main())
