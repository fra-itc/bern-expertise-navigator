"""Evaluation against the challenge's success criteria.

  1. recall@10 >= 80%          (expected experts/units in top 10)
  2. synonym twins             (lay-term query finds the same experts as the site term)
  3. traceability = 100%       (every result has a source URL + a snippet found on a crawled page)
  7. abstention                (out-of-domain queries -> 'no verifiable source')

Usage:  python eval/run_eval.py [--k 10] [--tag NAME]   (inside the api container: make eval)
        --tag also keeps the report as data/eval/NAME.json, so runs can be compared (eval/compare.py)
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from navigator import index, llm  # noqa: E402
from navigator.config import DATA_DIR, settings  # noqa: E402
from navigator.crawl import load_pages  # noqa: E402
from navigator.extract import _norm as snippet_norm  # noqa: E402
from navigator.search import search  # noqa: E402


def norm(s: str) -> str:
    """Name matching: case-, accent-, title- and punctuation-insensitive."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    s = re.sub(r"\b(prof|dr|med|phil|pd|msc|phd)\.?\b", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--golden", default=str(Path(__file__).parent / "golden_set.yaml"))
    ap.add_argument("--tag", default="", help="also save the report as data/eval/<tag>.json")
    a = ap.parse_args()
    if a.tag and not re.fullmatch(r"[\w.+-]+", a.tag):
        raise SystemExit("--tag: letters, digits, . + - _ only")
    # what this run measures: the index's extractor, and whether Apertus is used at query time
    llm_on = llm.available()
    extractors = Counter(e.extractor for e in index.load_entities().values())

    gs = yaml.safe_load(Path(a.golden).read_text())["queries"]
    # Same normalisation the extractor's verifier uses, so the check is identical to ingestion
    page_text = {p.url: snippet_norm(p.text + " " + p.title) for p in load_pages()}

    found_total = expected_total = 0
    results_total = traceable = 0
    abst_ok = abst_total = 0
    twins_ok = twins_total = 0
    top_names: dict[str, set[str]] = {}
    rows = []
    per_query: list[dict] = []
    latencies: list[float] = []
    untraceable: list[dict] = []
    llm.reset_usage()

    for item in gs:
        t0 = time.time()
        r = search(item["query"], k=a.k)
        latencies.append(time.time() - t0)
        names = [norm(x.person_or_unit) for x in r.results]
        top_names[item["id"]] = set(names)
        for res in r.results:
            results_total += 1
            if res.sources and all(s.url in page_text and snippet_norm(s.snippet) in page_text[s.url]
                                   for s in res.sources):
                traceable += 1
            else:
                untraceable.append({"query": item["query"], "result": res.person_or_unit})
        q = {"id": item["id"], "query": item["query"], "abstained": r.abstained,
             "expanded_terms": r.expanded_terms, "top": [x.person_or_unit for x in r.results]}
        per_query.append(q)
        if item.get("expect_abstain"):
            abst_total += 1
            abst_ok += int(r.abstained)
            q["ok"] = r.abstained
            rows.append((item["id"], item["query"], "abstained" if r.abstained else f"FAILED ({len(names)} results)"))
            continue
        exp = [norm(x) for x in item.get("expected", []) if not x.startswith("<")]
        hit_list = [any(e in n or n in e for n in names if n) for e in exp]
        hit = sum(hit_list)
        found_total += hit
        expected_total += len(exp)
        missing = [x for x, h in zip(item.get("expected", []), hit_list) if not h]
        q.update(found=hit, expected=len(exp), missing=missing)
        rows.append((item["id"], item["query"], f"{hit}/{len(exp)} expected in top {a.k}"
                     + (f"  missing: {', '.join(missing)}" if missing else "")
                     + ("  (ABSTAINED)" if r.abstained else "")))

    twins: list[dict] = []
    for item in gs:
        t = item.get("twin_of")
        if t and t in top_names:
            twins_total += 1
            a_, b_ = top_names[item["id"]], top_names[t]
            ok = bool(a_ and b_) and len(a_ & b_) / max(1, len(b_)) >= 0.5
            twins_ok += int(ok)
            twins.append({"id": item["id"], "twin_of": t, "query": item["query"], "ok": ok})

    pct = lambda x, y: f"{100 * x / y:.0f}%" if y else "n/a"
    report = {
        "recall_at_k": pct(found_total, expected_total),
        "synonym_twins_consistent": pct(twins_ok, twins_total),
        "traceability": pct(traceable, results_total),
        "abstention_correct": pct(abst_ok, abst_total),
        "queries": len(gs),
        "k": a.k,
        "latency_s": {"median": round(statistics.median(latencies), 2), "max": round(max(latencies), 2)},
        "llm_calls_per_query": round(llm.usage["calls"] / max(1, len(gs)), 2),
        "llm_tokens_per_query": round((llm.usage["prompt_tokens"] + llm.usage["completion_tokens"]) / max(1, len(gs))),
        "config": {"model": settings.llm_model, "embed_model": settings.embed_model,
                   "min_vector_score": settings.min_vector_score, "min_coverage": settings.min_coverage,
                   # the switches only matter when the endpoint answers: report what was actually used
                   "llm_reachable": llm_on,
                   "llm_expansion": settings.use_llm_expansion and llm_on,
                   "llm_explain": settings.use_llm_explain and llm_on,
                   "entities_by_extractor": dict(extractors)},
        "tag": a.tag,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "untraceable_results": untraceable[:20],
        "per_query": per_query,
        "twins": twins,
    }
    for row in rows:
        print(f"  {row[0]:4} {row[1][:45]:45} {row[2]}")
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_query", "twins")}, indent=2))
    DATA_DIR.mkdir(exist_ok=True)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    (DATA_DIR / "eval_report.json").write_text(out)
    if a.tag:
        (DATA_DIR / "eval").mkdir(exist_ok=True)
        (DATA_DIR / "eval" / f"{a.tag}.json").write_text(out)
        print(f"[eval] saved as data/eval/{a.tag}.json")


if __name__ == "__main__":
    main()
