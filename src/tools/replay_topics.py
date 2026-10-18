"""Offline replay of recorded topic decisions (nav.topic_map export) with the current topic logic, no LLM.

    python tools/replay_topics.py --topic-map topic_map.csv --graph-topics graph_topics.csv [--shortlist 8]

Inputs (exports of a populated database, read only):
  topic_map.csv     openalex_topic_id, openalex_label, topic_key, topic_label, is_new, decided_by, reason,
                    candidates (JSON list of candidate keys in shortlist order), decided_at
  graph_topics.csv  key, label of every Topic vertex after the run (agtype, i.e. JSON-encoded strings)

The LLM is replaced by the answer it gave in the recorded run, recovered from the audit:
  reason "invalid choice <repr> discarded, ..."  -> that string        (the answer the old parser rejected)
  is_new = false                                 -> the chosen key     (the answer was a valid key)
  any other new decision                         -> "NEW"              (the LLM answered new)
The vocabulary before the run = graph Topics minus the ones the run created (keys of new decisions that were
never a candidate). Each recorded answer is resolved again by papers.map_topic (identity rule, whitelist-bound
parsing); --shortlist truncates the recorded candidate lists (an answer beyond it becomes invalid -> new).

--llm-sample N asks the configured LLM (LLM_BASE_URL / LLM_NAME / LLM_API_KEY) again for at most N decisions
that still need it (not decided by the identity rule), stratified by original category, with the current prompt,
the recorded candidates and the OpenAlex subfield/field (one OpenAlex request for the sample).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import llm, papers  # noqa: E402
from navigator.graph import topic_key  # noqa: E402

# our own audit format (papers.map_topic before the fix): a fixed pattern, so a regex is the right tool
_INVALID = re.compile(r"""^invalid choice ('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")(?: \(\w+\))? discarded""")


def recorded_answer(row: dict) -> tuple[str, str]:
    """-> (answer the LLM gave, original category: invalid | reused | new_other)."""
    m = _INVALID.match(row["reason"])
    if m:
        return ast.literal_eval(m.group(1)), "invalid"
    if row["is_new"] in ("f", "false", "False", "0"):
        return row["topic_key"], "reused"
    return papers.TOPIC_NEW, "new_other"


def load(topic_map: Path, graph_topics: Path) -> tuple[list[dict], dict[str, str]]:
    rows = list(csv.DictReader(topic_map.open(encoding="utf-8")))
    graph = {json.loads(r["key"]): json.loads(r["label"]) for r in csv.DictReader(graph_topics.open(encoding="utf-8"))}
    for r in rows:
        r["cands"] = json.loads(r["candidates"])
    return rows, graph


def vocabulary_before(rows: list[dict], graph: dict[str, str]) -> dict[str, str]:
    cands = {k for r in rows for k in r["cands"]}
    created = {r["topic_key"] for r in rows if r["is_new"] == "t"} - cands
    return {k: l for k, l in graph.items() if k not in created}


@contextlib.contextmanager
def recorded_llm(answer: dict):
    """llm.chat_json answers answer["v"] (the recorded choice) instead of calling the endpoint."""
    real = llm.chat_json
    llm.chat_json = lambda messages, schema, **kw: schema(choice=answer["v"], reason="replayed")
    try:
        yield
    finally:
        llm.chat_json = real


def decide(r: dict, vocab: dict[str, str], shortlist: int | None, context: str = "") -> dict:
    key, by, reason = papers.map_topic(r["openalex_label"], context or "no subfield/field",
                                       [(k, vocab.get(k, k)) for k in r["cands"][:shortlist]], True,
                                       existing=set(vocab))
    return {"key": key, "by": by, "after": "reuse" if key else "new", "reason": reason,
            "identity": reason.startswith("identical normalised label"),
            "invalid": reason.startswith("invalid choice")}


def replay(rows: list[dict], vocab: dict[str, str], shortlist: int | None = None) -> list[dict]:
    out: list[dict] = []
    answer: dict = {}
    with recorded_llm(answer):
        for r in rows:
            answer["v"], cat = recorded_answer(r)
            out.append({"id": r["openalex_topic_id"], "label": r["openalex_label"], "before": cat,
                        "answer": answer["v"], **decide(r, vocab, shortlist)})
    return out


def openalex_context(ids: list[str]) -> dict[str, str]:
    """{topic id: "subfield: ..; field: .."} in one OpenAlex request (topics endpoint, OR filter)."""
    import httpx
    from navigator.config import settings
    params = {"filter": "id:" + "|".join(ids), "select": "id,subfield,field", "per-page": 100}
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
    r = httpx.get(f"{settings.openalex_base_url}/topics", params=params, timeout=30)
    r.raise_for_status()
    out = {}
    for t in r.json().get("results", []):
        parts = [f"{n}: {(t.get(n) or {}).get('display_name')}" for n in ("subfield", "field") if t.get(n)]
        out[t["id"].rsplit("/", 1)[-1]] = "; ".join(parts)
    return out


def llm_sample(rows: list[dict], res: list[dict], vocab: dict[str, str], n: int, shortlist: int | None,
               seed: int = 7) -> dict:
    """Ask the real LLM again for <= n decisions that need it, stratified by original category."""
    need = [(r, x) for r, x in zip(rows, res) if not x["identity"]]
    strata: dict[str, list] = {}
    for r, x in need:
        strata.setdefault(x["before"], []).append((r, x))
    rnd = random.Random(seed)
    quota = {c: max(1, round(n * len(v) / len(need))) for c, v in strata.items()}
    for c, v in strata.items():  # small strata are taken whole, the rest shares what is left
        quota[c] = min(len(v), max(quota[c], min(len(v), n // len(strata))))
    while sum(quota.values()) > n:
        quota[max(quota, key=quota.get)] -= 1
    picked = [p for c, v in strata.items() for p in rnd.sample(v, quota[c])]
    ctx = openalex_context([r["openalex_topic_id"] for r, _ in picked])
    llm.reset_usage()
    out = []
    for r, x in picked:
        y = decide(r, vocab, shortlist, ctx.get(r["openalex_topic_id"], ""))
        out.append({"id": r["openalex_topic_id"], "label": r["openalex_label"], "before": x["before"],
                    "recorded_answer": x["answer"], "offline": x["after"], "llm": y["after"], "key": y["key"],
                    "invalid": y["invalid"], "reason": y["reason"]})
    dist = {c: dict(Counter("invalid" if o["invalid"] else o["llm"] for o in out if o["before"] == c))
            for c in strata}
    return {"sample": len(out), "quota": quota, "llm_model": llm.settings.llm_model,
            "shortlist": shortlist or "recorded", "distribution_by_original_category": dist,
            "total": dict(Counter("invalid" if o["invalid"] else o["llm"] for o in out)),
            "usage": dict(llm.usage), "decisions": out}


def summary(res: list[dict]) -> dict:
    by_before = {}
    for cat in ("invalid", "reused", "new_other"):
        sub = [x for x in res if x["before"] == cat]
        by_before[cat] = {"n": len(sub), "reuse": sum(x["after"] == "reuse" for x in sub),
                          "reuse_identical_key": sum(x["identity"] for x in sub),
                          "reuse_other_candidate": sum(x["after"] == "reuse" and not x["identity"] for x in sub),
                          "new": sum(x["after"] == "new" for x in sub),
                          "still_invalid": sum(x["invalid"] for x in sub)}
    new_keys = {topic_key(x["label"]) for x in res if x["after"] == "new"}
    return {"decisions": len(res), "after": dict(Counter(x["after"] for x in res)),
            "llm_calls_needed": sum(not x["identity"] for x in res), "new_topic_vertices": len(new_keys),
            "by_original_category": by_before}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic-map", type=Path, required=True)
    ap.add_argument("--graph-topics", type=Path, required=True)
    ap.add_argument("--shortlist", type=int, default=None, help="truncate recorded candidates (default: all)")
    ap.add_argument("--csv", type=Path, help="write the per-decision replay here")
    ap.add_argument("--llm-sample", type=int, default=0, help="ask the configured LLM again for <= N decisions")
    ap.add_argument("--llm-out", type=Path, help="write the LLM sample (JSON) here")
    a = ap.parse_args(argv)
    rows, graph = load(a.topic_map, a.graph_topics)
    vocab = vocabulary_before(rows, graph)
    before = Counter(recorded_answer(r)[1] for r in rows)
    res = replay(rows, vocab, a.shortlist)
    print(json.dumps({"vocabulary_before_run": len(vocab), "graph_topics_after_run": len(graph),
                      "before": dict(before), "shortlist": a.shortlist or "recorded", **summary(res)}, indent=2))
    if a.csv:
        with a.csv.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(res[0]))
            w.writeheader()
            w.writerows(res)
    if a.llm_sample:
        if not llm.available():
            print(f"LLM endpoint {llm.settings.llm_base_url} not available", file=sys.stderr)
            return 2
        s = llm_sample(rows, res, vocab, a.llm_sample, a.shortlist)
        print(json.dumps({k: v for k, v in s.items() if k != "decisions"}, indent=2))
        if a.llm_out:
            a.llm_out.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8",
                                 newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
