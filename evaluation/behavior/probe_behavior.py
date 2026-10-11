#!/usr/bin/env python3
"""L3 行为等价实测:转换前后,同一模型对同一探针问题的回答语义是否一致。

协议(v2,探针 5→8 题 + 1 道多轮):
  - 8 道单轮探针,答案均在 examples/agent-fullcycle-engineering/SKILL.md 正文中有明确依据
  - 1 道多轮探针 R1(两轮,仅 A/C 形态):
      R1a "Senior Acceptance Gates 问哪几类问题?" → 拿到回答后
      R1b "就其中第 3 类,给出两个具体问题示例" —— judge 比较 A/C 第二轮答案
  - 三形态 system prompt,同模型同参(temperature=0.2, max_tokens=600):
      A 基准   : 原 SKILL.md 正文(strip frontmatter)
      B agent  : cli.py skill2agent --target crewai 产物 config/agents.yaml 的 backstory
      C workflow: cli.py skill2agent --target n8n 产物 workflow.json 的 x-source-skill.systemPrompt
  - 每形态每题各调一次 {GLM_BASE_URL}chat/completions(失败重试 1 次,仍失败记录错误)
  - judge(同模型)对 (A 答, X 答) 与原问题只输出 JSON {"equivalent":bool,"reason":"≤30字"}
  - 不一致(含判定错误)时:双方答案摘录各 100 字 + judge reason 完整落盘
  - 产出 results.md / results.json(与本脚本同目录)

运行:
  source /tmp/glm_keys.env && python3 evaluation/behavior/probe_behavior.py
仅标准库;GLM_API_KEY 缺失时整体 skip 并 exit 0。
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
SKILL_MD = ROOT / "examples" / "agent-fullcycle-engineering" / "SKILL.md"

DATE = "2026-10-11"
TEMPERATURE = 0.2
MAX_TOKENS = 600
TIMEOUT = 120

QUESTIONS = [
    ("Q1", "这个 skill 列出的 Response Modes 有哪几种?只列名字"),
    ("Q2", "最多同时运行几个 subagents?(数字)"),
    ("Q3", "选择架构时,什么时候才考虑 planner/executor 或 multi-agent?"),
    ("Q4", "skill 说调试时应该 patch 哪一层?"),
    ("Q5", "首次发布前必须完成哪些最低要求中的两项即可,任举两项"),
    ("Q6", "skill 说 subagent 委派要满足哪些 gate 条件?(至少两条)"),
    ("Q7", "这个 skill 对 RAG 的 no-answer 情况怎么要求?"),
    ("Q8", "adaptive optimization 什么时候允许执行 safe no-op?"),
]

# 多轮探针 R1:仅 A/C 形态,两轮;judge 比较 R1b 答案
MULTI_TURN_FORMS = ("A", "C")
R1A_Q = "这个 skill 的 Senior Acceptance Gates 问哪几类问题?"
R1B_Q = "就其中第 3 类,给出两个具体问题示例"
R1_JUDGE_Q = f"[多轮探针 R1] 第一轮:{R1A_Q} 第二轮:{R1B_Q}(judge 只比第二轮答案)"

JUDGE_SYSTEM = (
    "你是严格的答案等价性判定员。判定同一问题下两个回答是否语义一致:"
    "数字、列表项集合、核心结论一致即等价;措辞、顺序、详略不同不算不一致。"
    "只输出 JSON,不要输出任何其他内容。"
)


def excerpt(text: str, n: int = 60) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


# ---------------------------------------------------------------- 形态构建

def strip_frontmatter(raw: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.S).strip()


def yaml_literal_block(text: str, key: str) -> str:
    """取 agents.yaml 中 `key: |` 字面块内容(按公共缩进去缩进)。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}:\s*\|\s*$", ln):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"key {key!r} not found")
    block: list[str] = []
    for ln in lines[start:]:
        if ln.strip() == "":
            block.append("")
            continue
        if not ln.startswith((" ", "\t")):
            break
        block.append(ln)
    while block and block[-1] == "":
        block.pop()
    indents = [len(ln) - len(ln.lstrip()) for ln in block if ln.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(ln[cut:] if ln.strip() else "" for ln in block).strip()


def build_forms() -> dict[str, str]:
    """A: 原 SKILL.md 正文;B/C: 现场转换产物。返回 {form: system_prompt}。"""
    forms = {"A": strip_frontmatter(SKILL_MD.read_text(encoding="utf-8"))}

    tmp = Path(tempfile.mkdtemp(prefix="behavior_prods_"))
    for target in ("crewai", "n8n"):
        cmd = [sys.executable, "cli.py", "skill2agent",
               "examples/agent-fullcycle-engineering",
               "--target", target, "--out", str(tmp / target)]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"skill2agent {target} failed: {r.stderr.strip()[:300]}")

    crew_yaml = (tmp / "crewai" / "config" / "agents.yaml").read_text(encoding="utf-8")
    forms["B"] = yaml_literal_block(crew_yaml, "backstory")

    wf = json.loads((tmp / "n8n" / "workflow.json").read_text(encoding="utf-8"))
    forms["C"] = wf["x-source-skill"]["systemPrompt"].strip()
    return forms


# ---------------------------------------------------------------- API 调用

def chat_messages(messages: list[dict], api_key: str, base_url: str, model: str,
                  max_tokens: int = MAX_TOKENS) -> str:
    """一次 chat 调用(显式 messages),失败重试 1 次;仍失败抛最后异常。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(2):  # 1 次 + 重试 1 次
        if attempt:
            time.sleep(2)
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                KeyError, IndexError, json.JSONDecodeError) as e:
            last_err = e
            body = ""
            if isinstance(e, urllib.error.HTTPError):
                try:
                    body = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
            print(f"  [warn] api attempt {attempt + 1} failed: {e} {body}", file=sys.stderr)
    raise RuntimeError(f"API failed after retry: {last_err}")


def chat(system: str, user: str, api_key: str, base_url: str, model: str,
         max_tokens: int = MAX_TOKENS) -> str:
    return chat_messages(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        api_key, base_url, model, max_tokens)


def run_multi_turn(system: str, api_key: str, base_url: str, model: str) -> dict:
    """R1 两轮:R1a → 把 R1a 问答拼进上下文再问 R1b。"""
    rec: dict[str, dict] = {"R1a": {"question": R1A_Q, "answer": "", "error": None},
                            "R1b": {"question": R1B_Q, "answer": "", "error": None}}
    rec["R1a"]["answer"] = chat(system, R1A_Q, api_key, base_url, model)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": R1A_Q},
        {"role": "assistant", "content": rec["R1a"]["answer"]},
        {"role": "user", "content": R1B_Q},
    ]
    rec["R1b"]["answer"] = chat_messages(messages, api_key, base_url, model)
    return rec


def judge(a_ans: str, x_ans: str, question: str, *, api_key: str,
          base_url: str, model: str) -> dict:
    """judge 调用(最多 2 次),返回 {"equivalent":bool,"reason":str} 或错误标记。"""
    user = (
        f"问题:{question}\n\n"
        f"回答A:\n{a_ans}\n\n"
        f"回答B:\n{x_ans}\n\n"
        '两个回答是否语义等价?只输出 JSON:'
        '{"equivalent": true或false, "reason": "不超过30个字的原因"}'
    )
    last_err = ""
    for _ in range(2):
        try:
            out = chat(JUDGE_SYSTEM, user, api_key, base_url, model, max_tokens=200)
            m = re.search(r"\{.*\}", out, re.S)
            if not m:
                raise ValueError(f"no JSON in judge output: {excerpt(out, 80)}")
            d = json.loads(m.group(0))
            if not isinstance(d.get("equivalent"), bool):
                raise ValueError(f"equivalent not bool: {d}")
            return {"equivalent": d["equivalent"], "reason": str(d.get("reason", ""))[:60]}
        except Exception as e:
            last_err = str(e)
            time.sleep(2)
    return {"equivalent": None, "reason": f"judge error: {last_err[:120]}"}


# ---------------------------------------------------------------- 主流程

def main() -> int:
    api_key = os.environ.get("GLM_API_KEY", "").strip()
    base_url = os.environ.get("GLM_BASE_URL", "").strip()
    model = os.environ.get("GLM_MODEL", "glm-4-flash").strip()
    if not api_key or not base_url:
        print("[skip] GLM_API_KEY / GLM_BASE_URL 缺失,L3 行为等价实测跳过(exit 0)")
        return 0

    ctx = {"api_key": api_key, "base_url": base_url, "model": model}
    qmap = dict(QUESTIONS)

    print("[1/5] 构建三形态 system prompt(现场运行 skill2agent)...")
    forms = build_forms()
    for k, v in forms.items():
        print(f"  form {k}: {len(v)} chars | {excerpt(v, 50)}")

    # ---------- 单轮:8 题 × 3 形态 ----------
    print(f"[2/5] 三形态 × {len(QUESTIONS)} 单轮探针 → {model} "
          f"(temperature={TEMPERATURE}, max_tokens={MAX_TOKENS})...")
    answers: dict[str, dict[str, dict]] = {f: {} for f in "ABC"}
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for form, system in forms.items():
            for qid, q in QUESTIONS:
                jobs.append((form, qid, pool.submit(chat, system, q, **ctx)))
        for form, qid, fut in jobs:
            try:
                answers[form][qid] = {"question": qmap[qid],
                                      "answer": fut.result(), "error": None}
                print(f"  {form}/{qid} ok ({len(answers[form][qid]['answer'])} chars)")
            except Exception as e:
                answers[form][qid] = {"question": qmap[qid],
                                      "answer": "", "error": str(e)[:200]}
                print(f"  {form}/{qid} ERROR: {e}")

    # ---------- 多轮:R1 两轮 × A/C 形态 ----------
    print(f"[3/5] 多轮探针 R1(两轮)× {'/'.join(MULTI_TURN_FORMS)} 形态...")
    mt_answers: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=len(MULTI_TURN_FORMS)) as pool:
        futs = {f: pool.submit(run_multi_turn, forms[f], **ctx)
                for f in MULTI_TURN_FORMS}
        for f, fut in futs.items():
            try:
                mt_answers[f] = fut.result()
                print(f"  {f}/R1a ok ({len(mt_answers[f]['R1a']['answer'])} chars) | "
                      f"{f}/R1b ok ({len(mt_answers[f]['R1b']['answer'])} chars)")
            except Exception as e:
                # 尽量保留已成功的那一轮
                mt_answers[f] = mt_answers.get(f) or {
                    "R1a": {"question": R1A_Q, "answer": "", "error": str(e)[:200]},
                    "R1b": {"question": R1B_Q, "answer": "", "error": str(e)[:200]}}
                for rnd in ("R1a", "R1b"):
                    if not mt_answers[f][rnd]["error"]:
                        mt_answers[f][rnd]["error"] = str(e)[:200]
                print(f"  {f}/R1 ERROR: {e}")

    # ---------- judge ----------
    print(f"[4/5] judge:A vs B、A vs C 各 {len(QUESTIONS)} 题 + R1 多轮 1 题...")
    judgments: list[dict] = []
    jjobs = []
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for pair, x in (("A-B", "B"), ("A-C", "C")):
            for qid, q in QUESTIONS:
                a_rec, x_rec = answers["A"][qid], answers[x][qid]
                jjobs.append((pair, x, qid, False, pool.submit(
                    judge, a_rec["answer"], x_rec["answer"], q, **ctx)))
        if all(not mt_answers[f]["R1b"]["error"] for f in MULTI_TURN_FORMS):
            jjobs.append(("A-C", "C", "R1", True, pool.submit(
                judge, mt_answers["A"]["R1b"]["answer"],
                mt_answers["C"]["R1b"]["answer"], R1_JUDGE_Q, **ctx)))
        for pair, x, qid, is_mt, fut in jjobs:
            r = fut.result()
            judgments.append({"pair": pair, "other_form": x, "qid": qid,
                              "multi_turn": is_mt,
                              "question": R1_JUDGE_Q if is_mt else qmap.get(qid, qid),
                              **r})
            print(f"  {pair}/{qid}{'(多轮R1)' if is_mt else ''}: "
                  f"{r['equivalent']} | {r['reason']}")

    # ---------- 汇总 ----------
    single_js = [j for j in judgments if not j["multi_turn"]]
    mt_js = [j for j in judgments if j["multi_turn"]]
    rates = {}
    for pair in ("A-B", "A-C"):
        js = [j for j in single_js if j["pair"] == pair]
        ok = [j for j in js if j["equivalent"] is True]
        bad = [j for j in js if j["equivalent"] is False]
        err = [j for j in js if j["equivalent"] is None]
        rates[pair] = {"equivalent": len(ok), "not_equivalent": len(bad),
                       "errors": len(err), "total": len(js),
                       "rate": round(len(ok) / len(js), 4) if js else None}
    mt_rate = None
    if mt_js:
        j = mt_js[0]
        mt_rate = {"equivalent": 1 if j["equivalent"] is True else 0,
                   "not_equivalent": 1 if j["equivalent"] is False else 0,
                   "errors": 1 if j["equivalent"] is None else 0, "total": 1,
                   "rate": 1.0 if j["equivalent"] is True else 0.0}
    mismatches = [j for j in judgments if j["equivalent"] is not True]

    # ---------- 落盘 ----------
    print("[5/5] 写 results.md / results.json ...")
    payload = {
        "date": DATE, "model": model, "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "probe_protocol": (
            "v2:8 道单轮探针(答案均明确依据于 SKILL.md 正文)+ 1 道多轮探针 R1"
            "(R1a Senior Acceptance Gates 问哪几类问题 → R1b 就第 3 类举两个具体问题,"
            "仅 A/C 形态,judge 比较第二轮答案);三形态同模型同参各答一次;"
            "judge 同模型输出 {equivalent, reason};A=原 SKILL.md 正文,"
            "B=crewai backstory,C=n8n x-source-skill.systemPrompt;"
            "不一致时双方答案摘录各 100 字与 judge reason 完整记录于 mismatches"),
        "forms_chars": {k: len(v) for k, v in forms.items()},
        "questions": [{"qid": qid, "question": q} for qid, q in QUESTIONS],
        "multi_turn": {
            "rounds": [{"rid": "R1a", "question": R1A_Q},
                       {"rid": "R1b", "question": R1B_Q}],
            "forms": list(MULTI_TURN_FORMS),
            "judge_question": R1_JUDGE_Q,
            "answers": mt_answers,
        },
        "answers": answers,
        "judgments": judgments,
        "rates": rates,
        "multi_turn_rate": mt_rate,
        "mismatches": [
            {"pair": j["pair"], "qid": j["qid"], "question": j["question"],
             "multi_turn": j["multi_turn"], "equivalent": j["equivalent"],
             "reason": j["reason"],
             "a_answer_100": excerpt(answers["A"][j["qid"]]["answer"], 100)
             if not j["multi_turn"] else excerpt(mt_answers["A"]["R1b"]["answer"], 100),
             "x_answer_100": excerpt(
                 (answers[j["other_form"]][j["qid"]]["answer"]
                  if not j["multi_turn"]
                  else mt_answers["C"]["R1b"]["answer"]), 100),
             "a_error": (answers["A"][j["qid"]]["error"] if not j["multi_turn"]
                         else mt_answers["A"]["R1b"]["error"]),
             "x_error": (answers[j["other_form"]][j["qid"]]["error"] if not j["multi_turn"]
                         else mt_answers["C"]["R1b"]["error"]),
            } for j in mismatches],
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = ["# L3 行为等价实测结果", "",
          f"- 日期:{DATE}",
          f"- 模型:{model} | temperature:{TEMPERATURE} | max_tokens:{MAX_TOKENS}",
          f"- 探针协议(v2):{len(QUESTIONS)} 道单轮探针(答案均有 SKILL.md 正文依据)"
            "+ 1 道多轮探针 R1(两轮:R1a 问 Senior Acceptance Gates 问哪几类问题 → "
            "R1b 就其中第 3 类举两个具体问题;仅 A/C 形态,judge 比较 R1b 答案);"
            "三形态 system prompt 同模型同参各答一次;judge 用同模型对 (A 答, X 答) 只输出 "
          '`{"equivalent":bool,"reason":"≤30字"}`',
          "- 形态:A=原 SKILL.md 正文(strip frontmatter,"
          f"{len(forms['A'])} 字);B=crewai 产物 backstory"
          f"({len(forms['B'])} 字);C=n8n 产物 x-source-skill.systemPrompt"
          f"({len(forms['C'])} 字)", "",
          "## 一致率", "",
          "| 对比 | 等价 | 不等价 | 判定错误 | 一致率 |", "|---|---|---|---|---|"]
    for pair in ("A-B", "A-C"):
        r = rates[pair]
        md.append(f"| {pair}(单轮 {r['total']} 题) | {r['equivalent']} "
                  f"| {r['not_equivalent']} | {r['errors']} | {r['rate']:.0%} |")
    if mt_rate:
        md.append(f"| A-C(多轮 R1,judge 第二轮) | {mt_rate['equivalent']} "
                  f"| {mt_rate['not_equivalent']} | {mt_rate['errors']} "
                  f"| {mt_rate['rate']:.0%} |")
    md += ["", "## 逐题判定与摘录", ""]
    for pair, x in (("A-B", "B"), ("A-C", "C")):
        md += [f"### {pair}(A vs {x})", ""]
        for qid, q in QUESTIONS:
            j = next(j for j in single_js
                     if j["pair"] == pair and j["qid"] == qid)
            a_rec, x_rec = answers["A"][qid], answers[x][qid]
            md.append(f"**{qid}** {q}")
            md.append(f"- 判定:`{j['equivalent']}` | 理由:{j['reason']}")
            md.append(f"- A 答:{excerpt(a_rec['answer'])}"
                      + (f" (错误:{a_rec['error']})" if a_rec["error"] else ""))
            md.append(f"- {x} 答:{excerpt(x_rec['answer'])}"
                      + (f" (错误:{x_rec['error']})" if x_rec["error"] else ""))
            md.append("")
    if mt_js:
        j = mt_js[0]
        md += ["## 多轮探针 R1(A vs C,judge 第二轮答案)", "",
               f"- 第一轮问题:{R1A_Q}",
               f"- 第二轮问题:{R1B_Q}",
               f"- 判定:`{j['equivalent']}` | 理由:{j['reason']}", ""]
        for f in MULTI_TURN_FORMS:
            for rnd in ("R1a", "R1b"):
                rec = mt_answers[f][rnd]
                md.append(f"- {f} {rnd} 答:{excerpt(rec['answer'])}"
                          + (f" (错误:{rec['error']})" if rec["error"] else ""))
        md.append("")
    if mismatches:
        md += ["## 不一致明细(摘录各 100 字 + judge reason 完整)", ""]
        for m in payload["mismatches"]:
            md.append(f"**{m['pair']}/{m['qid']}**{'(多轮)' if m['multi_turn'] else ''} "
                      f"{m['question']}")
            md.append(f"- 判定:`{m['equivalent']}` | judge reason:{m['reason']}")
            md.append(f"- A 答(100字):{m['a_answer_100']}"
                      + (f" (错误:{m['a_error']})" if m["a_error"] else ""))
            md.append(f"- {m['pair'].split('-')[1]} 答(100字):{m['x_answer_100']}"
                      + (f" (错误:{m['x_error']})" if m["x_error"] else ""))
            md.append("")
    else:
        md += ["## 不一致明细", "", "无:全部判定等价。", ""]
    (OUT_DIR / "results.md").write_text("\n".join(md), encoding="utf-8")

    print("\n===== L3 行为等价实测汇总(v2) =====")
    for pair in ("A-B", "A-C"):
        r = rates[pair]
        print(f"{pair}: 一致率 {r['rate']:.0%} "
              f"(等价 {r['equivalent']}/不等价 {r['not_equivalent']}/错误 {r['errors']},"
              f"共 {r['total']} 题)")
    if mt_rate:
        j = mt_js[0]
        print(f"多轮 R1(A-C,judge 第二轮): {'等价' if j['equivalent'] is True else '不等价'}"
              f" | {j['reason']}")
    else:
        print("多轮 R1(A-C): 未完成(存在调用错误)")
    if mismatches:
        print("不一致明细:")
        for m in payload["mismatches"]:
            print(f"  - {m['pair']}/{m['qid']}: equivalent={m['equivalent']} "
                  f"| {m['reason']}")
    n_ok = sum(1 for j in judgments if j["equivalent"] is not None)
    n_all = len(single_js) + len(mt_js)
    print(f"判定完成 {n_ok}/{n_all};结果: {OUT_DIR / 'results.md'}")
    return 0 if n_ok == n_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
