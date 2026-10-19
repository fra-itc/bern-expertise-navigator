"""The manager dashboard: where the company requests stand, how the work progresses over time, and a short
written reading of it by Apertus 8B.

Everything is computed from the case store (status, outreach, activity log); nothing here changes a request.
The written analysis only receives the aggregate figures below (no contact details, no request text), and it is
accepted only if every number it writes is one of those figures; otherwise a rules-based text is shown, and the
page says which of the two it is.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel

from . import cases, llm
from .config import settings

# the request board's columns, in this order everywhere (KPI tiles, stacked chart, legend)
STAGES = ("todo", "ready", "done", "replied", "none")
ATTENTION_DAYS = {"todo": 3, "ready": 2}      # waiting longer than this needs a nudge


def stage(c: cases.Case) -> str:
    """Same rule as the requests board: replied > invited (or beyond) > pitch ready > no match > to do."""
    if c.status == "interested":
        return "replied"
    if c.status != "new":
        return "done"
    if (c.outreach or {}).get("brief"):
        return "ready"
    return "todo" if c.matches else "none"


def _dt(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _first(c: cases.Case, *kinds: str) -> datetime | None:
    ts = [d for e in c.events if e.kind in kinds and (d := _dt(e.at))]
    return min(ts) if ts else None


def _row(c: cases.Case, now: datetime) -> dict:
    b = (c.outreach or {}).get("brief") or {}
    created = _dt(c.created_at) or now
    return {"id": c.id, "company": cases.guess_company(c), "stage": stage(c), "status": c.status,
            "country": c.country, "canton": c.canton, "city": c.city, "area": c.area, "niche": c.niche,
            "created_at": c.created_at, "updated_at": c.updated_at, "age_days": (now - created).days,
            "partners": sum(m.selected for m in c.matches), "views": b.get("views", 0),
            "replies": len((c.outreach or {}).get("replies", [])), "pitch_at": b.get("at", "")}


def _buckets(start: date, end: date) -> tuple[str, list[date]]:
    """Days for up to ~5 weeks, else weeks (starting Monday)."""
    if (end - start).days <= 35:
        return "day", [start + timedelta(days=i) for i in range((end - start).days + 1)]
    first = start - timedelta(days=start.weekday())
    return "week", [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]


def _bucket_of(d: date, unit: str) -> date:
    return d if unit == "day" else d - timedelta(days=d.weekday())


def build(days: int | None = 30, now: datetime | None = None) -> dict:
    """The requests received in the last `days` days (None: all), where they stand and how the work went."""
    now = now or datetime.now(timezone.utc)
    all_cases = cases.list_cases()
    since = now - timedelta(days=days) if days else None
    scoped = [c for c in all_cases if not since or (_dt(c.created_at) or now) >= since]
    rows = [_row(c, now) for c in scoped]
    by_stage = {s: [r for r in rows if r["stage"] == s] for s in STAGES}

    # funnel: how far the requests got (each step counts the requests that reached it)
    reached = {
        "received": len(scoped),
        "matched": sum(1 for c in scoped if c.matches),
        "pitch": sum(1 for c in scoped if (c.outreach or {}).get("brief") or c.status != "new"),
        "invited": sum(1 for c in scoped if c.status != "new" or _first(c, "emailed")),
        "opened": sum(1 for c in scoped if ((c.outreach or {}).get("brief") or {}).get("views") or _first(c, "brief_opened")),
        "replied": sum(1 for c in scoped if (c.outreach or {}).get("replies") or c.status == "interested"),
    }

    # over time: requests received per period, by where they stand now; and the work done per period
    start = (since or min((_dt(c.created_at) or now for c in all_cases), default=now)).date()
    unit, periods = _buckets(start, now.date())
    idx = {p: i for i, p in enumerate(periods)}
    received = {s: [0] * len(periods) for s in STAGES}
    for c, r in zip(scoped, rows):
        if (d := _dt(c.created_at)) and (i := idx.get(_bucket_of(d.date(), unit))) is not None:
            received[r["stage"]][i] += 1
    work = {k: [0] * len(periods) for k in ("received", "pitches", "invitations", "replies")}
    kinds = {"created": "received", "brief_prepared": "pitches", "emailed": "invitations", "replied": "replies"}
    for c in all_cases:
        for e in c.events:
            if (k := kinds.get(e.kind)) and (d := _dt(e.at)) and (not since or d >= since):
                if (i := idx.get(_bucket_of(d.date(), unit))) is not None:
                    work[k][i] += 1

    # speed and appeal
    to_pitch = [(p - c0).total_seconds() / 86400 for c in scoped
                if (c0 := _dt(c.created_at)) and (p := _first(c, "brief_prepared"))]
    invited = reached["invited"]
    kpi = {"days_to_pitch": round(statistics.median(to_pitch), 1) if to_pitch else None,
           "open_rate": round(100 * reached["opened"] / invited) if invited else None,
           "reply_rate": round(100 * reached["replied"] / invited) if invited else None,
           "match_rate": round(100 * reached["matched"] / reached["received"]) if reached["received"] else None}

    # what needs a decision now (the levers): each with the requests concerned
    def ids(xs):
        return [r["id"] for r in sorted(xs, key=lambda r: -r["age_days"])]
    attention = [
        {"kind": "replied", "level": "critical", "ids": ids(by_stage["replied"])},
        {"kind": "ready_waiting", "level": "warning",
         "ids": ids(r for r in by_stage["ready"] if (now - (_dt(r["pitch_at"]) or now)).days >= ATTENTION_DAYS["ready"])},
        {"kind": "todo_waiting", "level": "warning",
         "ids": ids(r for r in by_stage["todo"] if r["age_days"] >= ATTENTION_DAYS["todo"])},
        {"kind": "no_match", "level": "serious", "ids": ids(by_stage["none"])},
    ]
    attention = [a for a in attention if a["ids"]]

    return {"generated_at": now.isoformat(timespec="seconds"), "days": days, "unit": unit,
            "periods": [p.isoformat() for p in periods], "total": len(rows), "all_total": len(all_cases),
            "stages": {s: len(by_stage[s]) for s in STAGES}, "requests": rows, "funnel": reached,
            "received": received, "work": work, "kpi": kpi, "attention": attention,
            "by_area": Counter(r["area"] or "" for r in rows).most_common(8),
            "by_country": Counter(r["country"] or "" for r in rows).most_common(8)}


# ---------------- the written analysis (Apertus 8B) -------------------------------------------------------------
_LANG = {"en": "English", "de": "German", "fr": "French"}
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


class _Text(BaseModel):
    text: str


def facts(o: dict) -> dict:
    """The aggregate figures the model may use: no names, no contact details, no request text."""
    f = o["funnel"]
    return {"period": f"last {o['days']} days" if o["days"] else "all time", "requests_received": o["total"],
            "now_to_do": o["stages"]["todo"], "now_pitch_ready_not_sent": o["stages"]["ready"],
            "now_invited": o["stages"]["done"], "now_company_replied": o["stages"]["replied"],
            "now_no_partner_found": o["stages"]["none"], "reached_partners_found": f["matched"],
            "reached_pitch_prepared": f["pitch"], "reached_invited": f["invited"], "reached_pitch_opened": f["opened"],
            "reached_replied": f["replied"], "median_days_to_pitch": o["kpi"]["days_to_pitch"],
            "open_rate_percent": o["kpi"]["open_rate"], "reply_rate_percent": o["kpi"]["reply_rate"],
            "partner_found_rate_percent": o["kpi"]["match_rate"],
            "waiting_too_long": {a["kind"]: len(a["ids"]) for a in o["attention"]},
            "top_countries": [[c or "unknown", n] for c, n in o["by_country"][:3]],
            "top_medtech_areas": [[a or "unspecified", n] for a, n in o["by_area"][:3]]}


def _numbers(x) -> set[str]:
    if isinstance(x, dict):
        return set().union(*(_numbers(v) for v in x.values())) if x else set()
    if isinstance(x, (list, tuple)):
        return set().union(*(_numbers(v) for v in x)) if x else set()
    if isinstance(x, bool) or x is None:
        return set()
    if isinstance(x, (int, float)):
        return {f"{x:g}"}
    return set(re.findall(r"\d+(?:\.\d+)?", str(x)))


def _numbers_ok(text: str, allowed: set[str]) -> bool:
    """Every number in the text is one of the figures (small counting words are fine)."""
    found = re.findall(r"\d+(?:[.,]\d+)?", text)
    return all(n.replace(",", ".") in allowed for n in found)


_RULES = {
    "en": {"lead": "{period}, {n} company requests came in.", "none": "{period}, no company requests came in.",
           "replied": "{k} companies have replied and are waiting for an answer: this is the first thing to do.",
           "ready": "{k} pitches are ready but not yet sent.", "todo": "{k} requests still need their partners checked.",
           "nomatch": "For {k} requests no partner was found in Bern; consider searching again with other words.",
           "rates": "Of the invited companies, {o}% opened the pitch and {r}% replied.",
           "periods": {True: "In the last {d} days", False: "So far"}},
    "de": {"lead": "{period} sind {n} Firmenanfragen eingegangen.", "none": "{period} sind keine Firmenanfragen eingegangen.",
           "replied": "{k} Firmen haben geantwortet und warten auf eine Antwort: Das ist zuerst zu tun.",
           "ready": "{k} Pitches sind bereit, aber noch nicht versandt.", "todo": "Bei {k} Anfragen müssen die Partner noch geprüft werden.",
           "nomatch": "Für {k} Anfragen wurde in Bern kein Partner gefunden; eine neue Suche mit anderen Begriffen lohnt sich.",
           "rates": "Von den eingeladenen Firmen haben {o}% den Pitch geöffnet und {r}% geantwortet.",
           "periods": {True: "In den letzten {d} Tagen", False: "Bisher"}},
    "fr": {"lead": "{period}, {n} demandes d'entreprises sont arrivées.", "none": "{period}, aucune demande d'entreprise n'est arrivée.",
           "replied": "{k} entreprises ont répondu et attendent une réponse : c'est la première chose à faire.",
           "ready": "{k} pitchs sont prêts mais pas encore envoyés.", "todo": "Pour {k} demandes, les partenaires restent à vérifier.",
           "nomatch": "Pour {k} demandes, aucun partenaire n'a été trouvé à Berne ; une nouvelle recherche avec d'autres mots peut aider.",
           "rates": "Parmi les entreprises invitées, {o} % ont ouvert le pitch et {r} % ont répondu.",
           "periods": {True: "Sur les {d} derniers jours", False: "Jusqu'ici"}},
}


def rules_text(o: dict, lang: str) -> str:
    t = _RULES.get(lang, _RULES["en"])
    period = t["periods"][bool(o["days"])].format(d=o["days"])
    if not o["total"]:
        return t["none"].format(period=period)
    s = o["stages"]
    out = [t["lead"].format(period=period, n=o["total"])]
    for key, k in (("replied", s["replied"]), ("ready", s["ready"]), ("todo", s["todo"]), ("nomatch", s["none"])):
        if k:
            out.append(t[key].format(k=k))
    if o["kpi"]["open_rate"] is not None:
        out.append(t["rates"].format(o=o["kpi"]["open_rate"], r=o["kpi"]["reply_rate"]))
    return " ".join(out)


def analysis(o: dict, lang: str = "en") -> dict:
    """A few plain sentences on the situation for a manager, by Apertus 8B; the rules text when the model is not
    reachable or writes a number that is not among the figures. Cached per figures and language."""
    f = facts(o)
    key = hashlib.sha256(json.dumps([f, lang], sort_keys=True).encode()).hexdigest()
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    out = {"text": rules_text(o, lang), "by": "rules", "model": "", "reason": "unavailable"}
    if o["total"] and llm.available():
        language = _LANG.get(lang, "English")
        msgs = [
            {"role": "system", "content": (
                "You brief a manager of the Canton of Bern's business development team on company requests. Write "
                "in simple, direct words for a non-technical reader: short sentences, no jargon, no bullet points. "
                "Use ONLY the figures given; do not invent numbers, causes or names. JSON only.")},
            {"role": "user", "content": (
                f"Figures:\n{json.dumps(f, ensure_ascii=False)}\n\nIn {language}, write 4 to 6 sentences: how many "
                "requests came in and where they stand, what is going well, what needs attention first, and one or "
                "two concrete next steps. Companies that replied come first. Return {\"text\": \"...\"}.")},
        ]
        allowed = _numbers(f)
        for _ in range(2):
            try:
                r: _Text = llm.chat_json(msgs, _Text, mode="none", max_tokens=400, model=settings.insight_model)  # type: ignore[assignment]
            except llm.LLMError:
                out["reason"] = "error"
                break
            text = " ".join(r.text.split())
            if 40 <= len(text) <= 1200 and _numbers_ok(text, allowed):
                out = {"text": text, "by": "apertus", "model": settings.insight_model, "reason": ""}
                break
            out["reason"] = "unchecked_numbers"
            msgs += [{"role": "assistant", "content": json.dumps({"text": r.text}, ensure_ascii=False)},
                     {"role": "user", "content": "Use only numbers that appear in the figures. Rewrite. JSON only."}]
    out["generated_at"] = o["generated_at"]
    with _cache_lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = out
    return out
