"""Compare saved eval runs (data/eval/<tag>.json, written by run_eval.py --tag) as Markdown tables.

Usage:  python eval/compare.py [TAG ...]     (no tags: every saved run, oldest first; the first is the baseline)

Prints the headline metrics side by side, then every query whose outcome differs from the baseline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from navigator.config import DATA_DIR  # noqa: E402

RUNS = DATA_DIR / "eval"
METRICS = [("recall_at_k", "Recall@10"), ("synonym_twins_consistent", "Lay-term twins consistent"),
           ("traceability", "Traceability"), ("abstention_correct", "Correct abstention")]


def load(tags: list[str]) -> list[dict]:
    if not tags:
        runs = [json.loads(p.read_text()) for p in RUNS.glob("*.json")]
        return sorted(runs, key=lambda r: r.get("at", ""))
    out = []
    for t in tags:
        p = RUNS / f"{t}.json"
        if not p.exists():
            raise SystemExit(f"No saved run '{t}' ({p}); run: make eval TAG={t}")
        out.append(json.loads(p.read_text()))
    return out


def _mode(r: dict) -> str:
    c = r.get("config", {})
    ex = c.get("entities_by_extractor") or {}
    web = {k: v for k, v in ex.items() if k != "openalex"}
    extraction = "+".join(sorted(web)) or "?"
    query = "Apertus" if c.get("llm_expansion") else "glossary"
    model = f"; model {c.get('model', '?')}" if c.get("llm_expansion") or "apertus" in web else "; no LLM"
    return f"extraction: {extraction}; query terms: {query}{model}"


def _outcome(q: dict) -> str:
    if "found" not in q:
        return "abstained" if q.get("abstained") else "answered (should abstain)"
    s = f"{q['found']}/{q['expected']}"
    return s + (" (abstained)" if q.get("abstained") else "")


def main():
    runs = load(sys.argv[1:])
    if not runs:
        raise SystemExit(f"No saved runs in {RUNS}; run: make eval TAG=<name>")
    tags = [r.get("tag") or "?" for r in runs]
    row = lambda cells: "| " + " | ".join(str(c) for c in cells) + " |"  # noqa: E731

    print(row(["", *tags]))
    print(row(["---"] * (len(runs) + 1)))
    for key, label in METRICS:
        print(row([label, *(r.get(key, "n/a") for r in runs)]))
    print(row(["Median latency (s)", *(r.get("latency_s", {}).get("median", "n/a") for r in runs)]))
    print(row(["LLM calls / query", *(r.get("llm_calls_per_query", "n/a") for r in runs)]))
    print(row(["LLM tokens / query", *(r.get("llm_tokens_per_query", "n/a") for r in runs)]))
    print(row(["Entities", *(sum((r.get("config", {}).get("entities_by_extractor") or {}).values()) or "n/a"
                             for r in runs)]))
    print()
    for t, r in zip(tags, runs):
        print(f"- **{t}**: {_mode(r)}")

    if len(runs) < 2:
        return
    base = {q["id"]: q for q in runs[0].get("per_query", [])}
    others = [{q["id"]: q for q in r.get("per_query", [])} for r in runs[1:]]
    changed = [i for i in base if any(i in o and _outcome(o[i]) != _outcome(base[i]) for o in others)]
    twin_base = {t["id"]: t["ok"] for t in runs[0].get("twins", [])}
    twin_changed = [(i, [{t["id"]: t["ok"] for t in r.get("twins", [])}.get(i) for r in runs])
                    for i in twin_base if any({t["id"]: t["ok"] for t in r.get("twins", [])}.get(i) != twin_base[i]
                                              for r in runs[1:])]
    print(f"\n**Queries that changed** (vs {tags[0]}): {len(changed)}\n")
    if changed:
        print(row(["Query", *tags]))
        print(row(["---"] * (len(runs) + 1)))
        for i in changed:
            print(row([f"{i}: {base[i]['query']}", _outcome(base[i]),
                       *(_outcome(o[i]) if i in o else "–" for o in others)]))
    if twin_changed:
        print(f"\n**Twin pairs that changed**: {len(twin_changed)}\n")
        print(row(["Lay-term query", *tags]))
        print(row(["---"] * (len(runs) + 1)))
        q = {x["id"]: x["query"] for x in runs[0].get("per_query", [])}
        for i, oks in twin_changed:
            print(row([f"{i}: {q.get(i, '')}", *("same experts" if ok else "differ" if ok is not None else "–"
                                                  for ok in oks)]))


if __name__ == "__main__":
    main()
