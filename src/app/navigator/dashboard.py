"""Staff dashboard: what Apertus costs (live usage log) and how well the search finds experts (saved eval runs).

Usage log: one line per web request that called Apertus, appended to data/usage.jsonl by api.py. It holds the
route, the request (case) id, tokens and latency, never the text of the request or any contact detail.
Cost = tokens x the price per million tokens in .env (LLM_PRICE_IN_CHF_PER_M / LLM_PRICE_OUT_CHF_PER_M); until
those are set the price is a placeholder and the dashboard says so.
"""
from __future__ import annotations

import json
import math
import statistics
import threading
import time
from collections import defaultdict
from pathlib import Path

from . import extract, llm
from .config import DATA_DIR, settings

USAGE_PATH = DATA_DIR / "usage.jsonl"
EVAL_DIR = DATA_DIR / "eval"
RECALL_TARGET = 80          # challenge success criterion: recall@10 >= 80 %
CHARS_PER_TOKEN = 4         # rough size of a token, only used until a real Apertus extraction has been measured
ASSUMED_OUTPUT_TOKENS = 600 # per extracted page, likewise
_lock = threading.Lock()


def record(route: str, meter: llm.Meter, total_s: float) -> None:
    """Append one request's Apertus usage to the log (only requests that called Apertus)."""
    if not meter.calls:
        return
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": route, "case_id": meter.case_id,
           "calls": meter.calls, "prompt_tokens": meter.prompt_tokens, "completion_tokens": meter.completion_tokens,
           "llm_s": round(meter.seconds, 2), "total_s": round(total_s, 2), "model": settings.llm_model}
    with _lock:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_PATH.open("a") as fh:
            fh.write(json.dumps(row) + "\n")


def _rows() -> list[dict]:
    if not USAGE_PATH.exists():
        return []
    out = []
    for line in USAGE_PATH.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue                      # a line cut short by a crash must not hide the rest
    return out


def cost(prompt_tokens: float, completion_tokens: float) -> float:
    return (prompt_tokens * settings.llm_price_in + completion_tokens * settings.llm_price_out) / 1e6


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[max(0, math.ceil(p * len(s)) - 1)]


def _sum(rows: list[dict]) -> dict:
    pt = sum(r.get("prompt_tokens", 0) for r in rows)
    ct = sum(r.get("completion_tokens", 0) for r in rows)
    lat = [r.get("total_s", 0.0) for r in rows]
    return {"requests": len(rows), "calls": sum(r.get("calls", 0) for r in rows), "prompt_tokens": pt,
            "completion_tokens": ct, "cost_chf": round(cost(pt, ct), 4),
            "median_s": round(statistics.median(lat), 2) if lat else 0.0, "p95_s": round(_pct(lat, 0.95), 2)}


def live(case_names: dict[str, str] | None = None) -> dict:
    rows = _rows()
    by_route: dict[str, list[dict]] = defaultdict(list)
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_route[r.get("route", "?")].append(r)
        if r.get("case_id"):
            by_case[r["case_id"]].append(r)
    names = case_names or {}
    cases = [{"id": cid, "company": names.get(cid, ""), "deleted": case_names is not None and cid not in names,
              "last": max(r.get("at", "") for r in rs), **_sum(rs)} for cid, rs in by_case.items()]
    cases.sort(key=lambda c: c["last"], reverse=True)
    per_case = [c["cost_chf"] for c in cases]
    return {"since": rows[0]["at"] if rows else None, **_sum(rows),
            "cost_per_request_chf": round(statistics.mean(per_case), 4) if per_case else None,
            "by_route": sorted(({"route": k, **_sum(v)} for k, v in by_route.items()), key=lambda x: -x["cost_chf"]),
            "cases": cases[:25]}


def _num(v) -> float | None:
    try:
        return float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _mode(r: dict) -> str:
    c = r.get("config", {})
    web = sorted(k for k in (c.get("entities_by_extractor") or {}) if k != "openalex")
    return f"extraction {'+'.join(web) or '?'}; query terms {'Apertus' if c.get('llm_expansion') else 'glossary'}"


def quality() -> list[dict]:
    """Every saved eval run (make eval TAG=...), oldest first."""
    runs = []
    for p in EVAL_DIR.glob("*.json") if EVAL_DIR.exists() else []:
        try:
            r = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        tpq = r.get("llm_tokens_per_query", 0) or 0
        # older runs only kept the total: priced as input tokens, which are most of a search's tokens
        pq, cq = r.get("llm_prompt_tokens_per_query", tpq), r.get("llm_completion_tokens_per_query", 0)
        runs.append({"tag": r.get("tag") or p.stem, "at": r.get("at", ""), "mode": _mode(r),
                     "model": (r.get("config") or {}).get("model", ""),
                     "llm": bool((r.get("config") or {}).get("llm_reachable")) and tpq > 0,
                     "recall": _num(r.get("recall_at_k")), "twins": _num(r.get("synonym_twins_consistent")),
                     "traceability": _num(r.get("traceability")), "abstention": _num(r.get("abstention_correct")),
                     "queries": r.get("queries"), "k": r.get("k"),
                     "median_s": (r.get("latency_s") or {}).get("median"),
                     "calls_per_query": r.get("llm_calls_per_query", 0), "tokens_per_query": tpq,
                     "cost_per_query_chf": round(cost(pq, cq), 5)})
    return sorted(runs, key=lambda x: x["at"])


def reextraction() -> dict:
    """Cost of extracting every saved page again with Apertus: measured when an Apertus extraction ran,
    otherwise estimated from the length of the pages."""
    pages = []
    for f in sorted((DATA_DIR / "pages").glob("*.jsonl")) if (DATA_DIR / "pages").exists() else []:
        for line in f.open():
            try:
                pages.append(len(json.loads(line).get("text", "")))
            except json.JSONDecodeError:
                continue
    calls = pt = ct = 0
    for f in DATA_DIR.glob("extract_stats*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("extractor") == "apertus":
            u = s.get("llm_usage") or {}
            calls, pt, ct = calls + u.get("calls", 0), pt + u.get("prompt_tokens", 0), ct + u.get("completion_tokens", 0)
    n = len(pages)
    if calls:
        p_in, p_out, basis = pt / calls, ct / calls, "measured"
    else:
        overhead = len(extract.SYSTEM) + len(extract.USER_TMPL)
        p_in = (sum(min(c, extract.MAX_CHARS) for c in pages) / max(1, n) + overhead) / CHARS_PER_TOKEN
        p_out, basis = ASSUMED_OUTPUT_TOKENS, "estimated"
    return {"pages": n, "basis": basis, "prompt_tokens_per_page": round(p_in), "completion_tokens_per_page": round(p_out),
            "tokens": round(n * (p_in + p_out)), "cost_chf": round(cost(n * p_in, n * p_out), 2),
            "measured_calls": calls}


def build(case_names: dict[str, str] | None = None) -> dict:
    return {"price": {"in_chf_per_m": settings.llm_price_in, "out_chf_per_m": settings.llm_price_out,
                      "configured": settings.llm_price_set, "model": settings.llm_model},
            "recall_target": RECALL_TARGET, "live": live(case_names), "quality": quality(),
            "reextraction": reextraction()}
