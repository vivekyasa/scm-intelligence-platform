"""
Run the golden question set against the agent and score it.

Scoring is rule based (no AI judge), so results are repeatable:
  answer   the final answer contains the expected facts and numbers
  tools    the agent used the tools the question needs
  source   for policy questions, the right document was cited
  section  for policy questions, the right section was retrieved
  sql      for data questions, the last query's rows hold the expected values

Results are saved after every question, so a quota stop never loses work.
Run again with the same --name to continue where it stopped.

Usage:
    py run_evals.py --name baseline
    py run_evals.py --name baseline --ids D01,P01
    py run_evals.py --name baseline --pause 6
Needs GEMINI_API_KEY and DATABASE_URL_RO.
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
GOLDEN = ROOT / "evals" / "golden.json"
RESULTS = ROOT / "evals" / "results"


# ------------------------------------------------------------------ scoring

def normalise(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", str(text)).lower()


def numbers_in(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", normalise(text))]


def has_number(text: str, value: float, tol: float) -> bool:
    return any(abs(abs(n) - abs(value)) <= tol for n in numbers_in(text))


def check_text(text: str, checks: dict) -> list[str]:
    """Return a list of failure messages (empty means pass)."""
    low = normalise(text)
    problems = []
    for want in checks.get("all", []):
        options = [want] if isinstance(want, str) else want
        if not any(o.lower() in low for o in options):
            problems.append(f"missing {options[0]!r}")
    for n in checks.get("numbers", []):
        if not has_number(text, n["value"], n.get("tol", 0)):
            problems.append(f"missing number {n['value']}")
    any_of = checks.get("any", [])
    if any_of and not any(a.lower() in low for a in any_of):
        problems.append("none of the expected phrases found")
    for bad in checks.get("forbid", []):
        if bad.lower() in low:
            problems.append(f"forbidden text {bad!r}")
    return problems


def score_case(case: dict, result: dict) -> dict:
    """result has: answer, tool_calls (list of dicts), sources (list), rows."""
    answer = result.get("answer", "")
    used = {c["tool"] for c in result.get("tool_calls", [])}
    scores, notes = {}, []

    problems = check_text(answer, case.get("answer_checks", {}))
    scores["answer"] = not problems
    notes += [f"answer: {p}" for p in problems]

    expected = set(case.get("expect_tools", []))
    scores["tools"] = expected <= used
    if not scores["tools"]:
        notes.append(f"tools: expected {sorted(expected)}, used {sorted(used)}")

    if case.get("expect_source"):
        titles = {s["doc_title"] for s in result.get("sources", [])}
        scores["source"] = case["expect_source"] in titles
        if not scores["source"]:
            notes.append(f"source: {case['expect_source']} not among {sorted(titles)}")
        want = (case["expect_source"], case.get("expect_section"))
        got = {(s["doc_title"], s["section"]) for s in result.get("sources", [])}
        scores["section"] = want in got
        if not scores["section"]:
            notes.append(f"section: {want[1]!r} not retrieved")

    if case.get("sql_checks"):
        rows_text = json.dumps(result.get("rows", []), default=str)
        problems = check_text(rows_text, case["sql_checks"])
        scores["sql"] = not problems
        notes += [f"sql: {p}" for p in problems]

    if case.get("expect_no_write"):
        scores["no_write"] = not any(
            c.get("error") is None and re.search(r"\b(delete|drop)\b", c.get("input", ""), re.I)
            for c in result.get("tool_calls", [])
        )

    return {"scores": scores, "passed": all(scores.values()), "notes": notes}


# ------------------------------------------------------------------ running

def ask_agent(question: str) -> dict:
    import app  # imported late so scoring tests need no API keys

    r = app.answer_question(question)
    return json.loads(r.model_dump_json())


def summarise(cases: list[dict], graded: dict) -> str:
    by_cat = defaultdict(lambda: [0, 0])
    metric = defaultdict(lambda: [0, 0])
    latencies = []
    for c in cases:
        g = graded.get(c["id"])
        if not g:
            continue
        by_cat[c["category"]][1] += 1
        by_cat[c["category"]][0] += g["passed"]
        for k, v in g["scores"].items():
            metric[k][1] += 1
            metric[k][0] += bool(v)
        if g.get("latency_ms"):
            latencies.append(g["latency_ms"])
    done = sum(v[1] for v in by_cat.values())
    passed = sum(v[0] for v in by_cat.values())
    lines = [f"\nOverall: {passed}/{done} passed" + (f" ({100 * passed / done:.0f}%)" if done else "")]
    lines.append("\nBy category")
    for cat, (p, n) in sorted(by_cat.items()):
        lines.append(f"  {cat:12} {p}/{n}")
    lines.append("\nBy check")
    for k, (p, n) in sorted(metric.items()):
        lines.append(f"  {k:12} {p}/{n}")
    if latencies:
        latencies.sort()
        lines.append(f"\nLatency: median {latencies[len(latencies) // 2] / 1000:.1f}s, "
                     f"max {latencies[-1] / 1000:.1f}s")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="baseline")
    ap.add_argument("--ids", default="")
    ap.add_argument("--redo", action="store_true", help="rerun the chosen --ids even if saved")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between questions")
    args = ap.parse_args()

    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.name}.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    for i, case in enumerate(cases, 1):
        cid = case["id"]
        if cid in saved and not saved[cid].get("error") and not args.redo:
            continue
        print(f"[{i}/{len(cases)}] {cid} {case['question'][:70]}", flush=True)
        try:
            result = ask_agent(case["question"])
            graded = score_case(case, result)
            graded.update(answer=result["answer"], model=result["model"],
                          latency_ms=result["latency_ms"],
                          tool_calls=result["tool_calls"], sources=result["sources"],
                          rows=result.get("rows", []))
            print("   ", "PASS" if graded["passed"] else "FAIL", *graded["notes"], sep="  ")
        except Exception as e:  # keep going; rerun picks this up again
            msg = str(e).strip().splitlines()[0][:200]
            graded = {"error": msg, "passed": False, "scores": {}, "notes": [msg]}
            print("    ERROR ", msg)
            if "quota" in msg.lower() or "429" in msg:
                print("    Quota hit. Saved progress; rerun later with the same --name.")
                saved[cid] = graded
                path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                break
        saved[cid] = graded
        path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        time.sleep(args.pause)

    scored = {k: v for k, v in saved.items() if not v.get("error")}
    print(summarise(cases, scored))
    errors = [k for k, v in saved.items() if v.get("error")]
    if errors:
        print(f"\nNot scored (errors): {', '.join(errors)}. Rerun to retry them.")
    print(f"\nSaved to {path}")


if __name__ == "__main__":
    sys.exit(main())
