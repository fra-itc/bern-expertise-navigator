"""Company-case regression oracle (eval/company_oracle.yaml): must-recall and trap rate per case.

For every stored request of a case, the stored company analysis is matched again (cases.find_matches) and the
assets the offer would cite are selected (cases.pick_assets over the matches whose explanation is not
"Weak match"). No paragraph is written and nothing is saved.

  must-recall = share of the case's `must` assets in the offer        (gate: 100% for every request)
  trap rate   = share of the case's `traps` in the offer              (reported; lower is better)

Usage:  python eval/run_oracle.py [--oracle FILE] [--case ID] [--json OUT] [--analyses FILE]
        --analyses: JSON {request id: stored analysis}, read instead of the case store (e.g. to replay requests
        stored in Postgres on the file backend: same analyses, other backend)
Exit:   0 all must assets recalled, 1 at least one must-recall miss, 2 a case could not be run (missing request).
Output: company and asset names only (public names), never the request's text.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from navigator import cases, llm, plain  # noqa: E402
from navigator.storage import backend  # noqa: E402
from run_eval import norm  # noqa: E402


def found(name: str, names: list[str]) -> bool:
    """A one-word name only as the whole name ("Monitoring" is not "Sensor Based Monitoring"); a longer one also
    as part of the asset's name ("SPN-005" in "SPN-005 – Pilot study on …") or the other way round."""
    n = norm(name)
    if " " not in n:
        return any(n == x or x.startswith(n + " ") for x in names if x)
    return any(n in x or x in n for x in names if x)


def run_request(analysis: plain.RequestAnalysis) -> tuple[list[str], list[str]]:
    """(names of the matches kept, names of the assets the offer cites)."""
    kept, _ = cases.find_matches(analysis)
    picked = cases.pick_assets([m for m in kept if not cases._weak(m)])
    return [m.name for m in kept], [m.name for m in picked]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle", default=str(Path(__file__).parent / "company_oracle.yaml"))
    ap.add_argument("--case", default="", help="run only this case id")
    ap.add_argument("--json", default="", help="also write the report here")
    ap.add_argument("--analyses", default="", help="JSON {request id: analysis} instead of the case store")
    a = ap.parse_args()
    exported = json.loads(Path(a.analyses).read_text(encoding="utf-8")) if a.analyses else None
    spec = yaml.safe_load(Path(a.oracle).read_text(encoding="utf-8"))["cases"]
    report: dict = {"backend": backend(), "llm_reachable": llm.available(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "cases": []}
    misses = errors = 0
    for c in spec:
        if a.case and c["id"] != a.case:
            continue
        runs: list[tuple[str, plain.RequestAnalysis | None]] = []
        if c.get("analysis"):
            runs.append(("inline", plain.RequestAnalysis(**c["analysis"])))
        for cid in map(str, c.get("case_ids", [])):   # YAML reads an all-digit id as a number
            if exported is not None:
                runs.append((cid, plain.RequestAnalysis(**exported[cid]) if cid in exported else None))
                continue
            stored = cases.get(cid)
            runs.append((cid, stored.analysis if stored else None))
        out = {"id": c["id"], "company": c.get("company", ""), "status": c.get("status", "draft"), "requests": []}
        for rid, analysis in runs:
            if analysis is None:
                errors += 1
                out["requests"].append({"request": rid, "error": "request not found"})
                print(f"  {c['id']:14} {rid:10} ERROR: request not found")
                continue
            kept, offer = run_request(analysis)
            low_offer = [norm(x) for x in offer]
            missing = [m for m in c.get("must", []) if not found(m, low_offer)]
            traps = [t for t in c.get("traps", []) if found(t, low_offer)]
            in_matches = [m for m in missing if found(m, [norm(x) for x in kept])]
            n_must, n_trap = len(c.get("must", [])), len(c.get("traps", []))
            row = {"request": rid, "must_recall": round((n_must - len(missing)) / n_must, 3) if n_must else None,
                   "missing": missing, "missing_but_matched": in_matches,
                   "trap_rate": round(len(traps) / n_trap, 3) if n_trap else None, "traps_in_offer": traps,
                   "offer": offer, "matches": len(kept)}
            out["requests"].append(row)
            misses += len(missing)
            print(f"  {c['id']:14} {rid:10} must {n_must - len(missing)}/{n_must}  traps {len(traps)}/{n_trap}"
                  + (f"  MISSING: {', '.join(missing)}" if missing else "")
                  + (f"  TRAPS: {', '.join(traps)}" if traps else ""))
        ok = [r for r in out["requests"] if "error" not in r]
        out["must_recall_min"] = min((r["must_recall"] for r in ok if r["must_recall"] is not None), default=None)
        out["trap_rate_mean"] = round(sum(r["trap_rate"] or 0 for r in ok) / len(ok), 3) if ok else None
        report["cases"].append(out)
    report["must_misses"], report["errors"] = misses, errors
    print(json.dumps({"backend": report["backend"], "llm_reachable": report["llm_reachable"], "must_misses": misses,
                      "errors": errors, "cases": [{k: x[k] for k in ("id", "status", "must_recall_min", "trap_rate_mean")}
                                                  for x in report["cases"]]}, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 2 if errors else 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
