"""Landing-page data: research strengths, verified proof points, labs and facilities directories.

Everything is derived from the index or from config/showcase.yaml, and every quoted statement is
re-checked against the saved page text (same rule as search: no source, no claim).
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

import yaml

from . import crawl, index, search
from .config import CONFIG_DIR, DATA_DIR
from .extract import _norm
from .schema import Entity
from .storage import index_store

SHOWCASE = CONFIG_DIR / "showcase.yaml"


def _first_sentence(e: Entity, limit: int = 220) -> str | None:
    if not e.description:
        return None
    s = e.description[0]
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def _people(e: Entity, ents: dict[str, Entity], nb: dict[str, list[str]]) -> list[Entity]:
    """Linked people, the lab's own contact(s) first, then by seniority."""
    ppl = [ents[i] for i in nb.get(e.id, []) if i in ents and ents[i].entity_type == "person"]
    own = set(e.source_urls)
    on_lab_page = lambda p: any(ev.url in own and ev.field == "name" for ev in p.evidence)  # noqa: E731
    return sorted(ppl, key=lambda p: (not on_lab_page(p), -search.seniority(p), p.name))


def _card(e: Entity, ents: dict[str, Entity], nb: dict[str, list[str]]) -> dict:
    ppl = _people(e, ents, nb)
    own = set(e.source_urls)
    lead = ppl[0] if ppl and (search.seniority(ppl[0]) >= 1.0
                              or any(ev.url in own and ev.field == "name" for ev in ppl[0].evidence)) else None
    return {
        "id": e.id, "name": e.name, "entity_type": e.entity_type, "source": e.source,
        "institution": e.source_label, "summary": _first_sentence(e), "url": e.source_urls[0],
        "people": len(ppl), "projects": len(e.projects),
        "lead": {"id": lead.id, "name": lead.name, "role": lead.role} if lead else None,
        "contact": next((p.email for p in ppl if p.email), None) or e.email,
        "expertise": e.expertise[:3],
    }


def _verified(items: list[dict], pages: dict[str, str]) -> list[dict]:
    out = []
    for it in items or []:
        text = pages.get(it.get("url", ""))
        if text and _norm(it.get("quote", "")) in text:
            out.append(it)
        else:
            print(f"[showcase] dropped unverifiable item: {it.get('quote', '')[:60]!r} @ {it.get('url')}")
    return out


def _theme(t: dict, ents: dict[str, Entity]) -> dict:
    r = search.search(t["query"], k=30)
    found = [ents[x.id] for x in r.results if x.id in ents]
    counts = Counter(e.entity_type for e in found)
    labs = [e for e in found if e.entity_type == "unit"][:3]
    people = [e for e in found if e.entity_type == "person"][:3]
    return {**{k: t[k] for k in ("id", "query", "title", "blurb")},
            "counts": {k: counts.get(k, 0) for k in ("person", "unit", "project", "infrastructure")},
            "institutions": sorted({e.source_label for e in found}),
            "labs": [{"id": e.id, "name": e.name} for e in labs],
            "people": [{"id": e.id, "name": e.name, "role": e.role} for e in people]}


@lru_cache(maxsize=2)
def _build(_key: tuple) -> dict:
    cfg = yaml.safe_load(SHOWCASE.read_text()) if SHOWCASE.exists() else {}
    ents = index.load_entities()
    pages = {p.url: _norm(p.text + " " + p.title) for p in crawl.load_pages()}
    nb = search.neighbors([e.id for e in ents.values() if e.entity_type in ("unit", "infrastructure")])
    labs = sorted((e for e in ents.values() if e.entity_type == "unit"),
                  key=lambda e: (-len(_people(e, ents, nb)), e.name))
    facilities = sorted((e for e in ents.values() if e.entity_type == "infrastructure"), key=lambda e: e.name)
    return {
        "themes": [_theme(t, ents) for t in cfg.get("themes", [])] if ents else [],
        "highlights": _verified(cfg.get("highlights"), pages),
        "engage": _verified(cfg.get("engage"), pages),
        "labs": [_card(e, ents, nb) for e in labs],
        "facilities": [_card(e, ents, nb) for e in facilities],
    }


def build() -> dict:
    key = (index_store().version(), SHOWCASE.stat().st_mtime if SHOWCASE.exists() else 0,
           tuple(sorted(f.stat().st_mtime for f in (DATA_DIR / "pages").glob("*.jsonl"))))
    return _build(key)
