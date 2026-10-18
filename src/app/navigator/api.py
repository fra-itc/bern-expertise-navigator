"""FastAPI: /search, /entity, /stats, /health and the web UI."""
from __future__ import annotations

import json
import secrets
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import archetypes, brief, cases, crawl, documents, index, llm, plain, search as search_mod, showcase, understand
from .config import DATA_DIR, load_sources, settings
from .schema import EntityDetail, RelatedRef, SearchResponse
from .storage import StorageError

STATIC = Path(__file__).parent / "static"


def _warm_up():
    """Load the embedding model and the index before the first user query (cold start ~15 s on CPU)."""
    try:
        index.load_entities()
        index.embed(["warm up"], query=True)
        showcase.build()
    except Exception as e:  # noqa: BLE001 - warm-up must never crash the server
        print(f"[api] warm-up skipped: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="Research & Expertise Navigator", version="0.3.0", lifespan=lifespan)


@app.exception_handler(StorageError)
def _storage_error(_req: Request, e: StorageError):
    """Storage down / schema outdated: structured 503 instead of an opaque 500."""
    return JSONResponse(status_code=503, content={"error": e.code, "detail": e.detail, "backend": e.backend})

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "entities": len(index.load_entities()), "model": settings.llm_model,
            "llm_available": llm.available()}


@app.get("/search", response_model=SearchResponse)
def do_search(q: str = Query(..., min_length=2, max_length=300), k: int = Query(10, ge=1, le=50),
              source: list[str] | None = Query(None), type: list[str] | None = Query(None)):
    t0 = time.time()
    r = search_mod.search(q, k=k, sources=source, types=type)
    r.took_ms = int((time.time() - t0) * 1000)
    r.llm_used = llm.available() and (settings.use_llm_expansion or settings.use_llm_explain)
    return r


@app.get("/entity/{eid}", response_model=EntityDetail)
def entity(eid: str):
    ents = index.load_entities()
    e = ents.get(eid)
    if not e:
        raise HTTPException(404, "unknown entity")
    nb = [ents[i] for i in search_mod.neighbors([eid]).get(eid, []) if i in ents]
    nb.sort(key=lambda x: (x.entity_type != "person", -search_mod.seniority(x), x.name))
    return EntityDetail(entity=e, related=[RelatedRef(id=x.id, name=x.name, entity_type=x.entity_type, role=x.role)
                                           for x in nb[:40]])


@app.get("/showcase")
def get_showcase():
    """Landing page data: research strengths (live from the index), verified proof points, labs, facilities."""
    return showcase.build()


@lru_cache(maxsize=1)
def _pages_per_source(_mt: tuple) -> Counter:
    return Counter(p.source for p in crawl.load_pages())


def _json(name: str):
    p = DATA_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


@app.get("/stats")
def stats():
    ents = index.load_entities().values()
    page_files = tuple(sorted((f.name, f.stat().st_mtime) for f in (DATA_DIR / "pages").glob("*.jsonl"))) \
        if (DATA_DIR / "pages").exists() else ()
    rej = DATA_DIR / "rejected.jsonl"
    return {
        "sources": [{"name": s.name, "label": s.label} for s in load_sources()],
        "pages_per_source": _pages_per_source(page_files),
        "entities_per_source": Counter(e.source for e in ents),
        "entities_per_type": Counter(e.entity_type for e in ents),
        "evidence_snippets": sum(len(e.evidence) for e in ents),
        "claims_rejected": sum(1 for l in rej.open() if l.strip()) if rej.exists() else 0,
        "model": settings.llm_model,
        "llm_available": llm.available(),
        "extractors": Counter(e.extractor for e in ents),
        "eval": _json("eval_report.json"),
    }


# ---------------- plain language ------------------------------------------------
@app.get("/glossary")
def get_glossary(lang: str = "en"):
    """Reviewed plain-language glossary (for jargon tooltips in the UI)."""
    return [{"term": t["term"], "forms": t["forms"], "plain": t.get(lang) or t["en"]} for t in plain.glossary()]


@app.get("/examples")
def examples():
    """Fictional example requests for the demo form."""
    import yaml
    from .config import CONFIG_DIR
    p = CONFIG_DIR / "example_requests.yaml"
    return yaml.safe_load(p.read_text()).get("examples", []) if p.exists() else []


# ---------------- company requests (cases) ----------------------------------------
# Staff workspace (business development). Every action names the person, for the activity log
# (prototype: identity is self-declared, no passwords).
class StaffAction(BaseModel):
    actor: str = Field(..., min_length=1, max_length=120)
def _case_or_404(cid: str) -> cases.Case:
    c = cases.get(cid)
    if not c:
        raise HTTPException(404, "unknown request")
    return c


@app.get("/archetypes")
def get_archetypes():
    return archetypes.ARCHETYPES


@app.get("/taxonomy")
def get_taxonomy():
    """The entity model: groups → types → archetypes, with labels."""
    return archetypes.GROUPS


@app.get("/understand")
def get_understand(q: str = Query("", max_length=500)):
    """Live preview for the broad search: place (city / canton / country), medtech area / niche and the
    words that remain to search, read from free text in EN/DE/FR/IT/Romansh (config-driven, no AI)."""
    return understand.understand(q)


@app.get("/medtech-areas")
def get_medtech_areas():
    """Medtech areas and niches offered as filters on a new request (config/medtech_areas.yaml)."""
    return [{"id": a["id"], "label": a["label"], "niches": [{"id": n["id"], "label": n["label"]} for n in a.get("niches", [])]}
            for a in cases.medtech_areas()]


@app.get("/cases")
def list_cases():
    return [{"id": c.id, "company": c.company, "status": c.status, "country": c.country, "canton": c.canton,
             "area": c.area, "niche": c.niche,
             "updated_at": c.updated_at, "created_at": c.created_at, "summary": c.analysis.summary[:220],
             "selected": sum(m.selected for m in c.matches), "has_brief": bool((c.outreach or {}).get("brief"))}
            for c in cases.list_cases()]


@app.post("/documents", response_model=documents.Document)
async def read_document(request: Request, name: str = Query(..., min_length=1, max_length=255)):
    """Raw file bytes in the body (no multipart). Returns the extracted text; the file is not stored."""
    if int(request.headers.get("content-length") or 0) > documents.MAX_BYTES:
        raise HTTPException(413, f"The file is larger than {documents.MAX_BYTES // 1_000_000} MB.")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > documents.MAX_BYTES:
            raise HTTPException(413, f"The file is larger than {documents.MAX_BYTES // 1_000_000} MB.")
    try:
        # parsing is CPU-bound; keep the event loop free for other users
        return await run_in_threadpool(documents.read, name, bytes(data))
    except documents.DocumentError as e:
        raise HTTPException(422, str(e)) from None


@app.get("/documents/types")
def document_types():
    return {"accept": documents.ACCEPT, "max_mb": documents.MAX_BYTES // 1_000_000}


@app.post("/cases", response_model=cases.Case)
def create_case(req: cases.NewCase):
    try:
        return cases.create(req)
    except cases.company_web.FetchError as e:
        raise HTTPException(422, str(e)) from None


@app.get("/cases/{cid}", response_model=cases.Case)
def get_case(cid: str):
    c = _case_or_404(cid)
    if c.offer is None and c.matches and c.status == "new":   # requests created before the paragraph existed
        c.offer = cases.summarize_offer(c)
        cases.save(c)
    return c


@app.delete("/cases/{cid}")
def delete_case(cid: str):
    _case_or_404(cid)
    cases.delete(cid)
    return {"ok": True}


class Details(StaffAction):
    company: str = Field(..., min_length=1, max_length=200)
    contact_name: str = Field("", max_length=200)
    contact_email: str = Field("", max_length=200)


@app.post("/cases/{cid}/details", response_model=cases.Case)
def set_details(cid: str, body: Details):
    """Company and contact person — asked only when the officer is ready to pitch."""
    c = _case_or_404(cid)
    c.company, c.contact_name, c.contact_email = body.company.strip(), body.contact_name.strip(), body.contact_email.strip()
    cases.log(c, body.actor, "details", f"Company details: {c.company}")
    return cases.save(c)


class Selection(StaffAction):
    selected: list[str]


@app.post("/cases/{cid}/selection", response_model=cases.Case)
def select_matches(cid: str, body: Selection):
    c = _case_or_404(cid)
    if c.status != "new":
        raise HTTPException(409, "Partners can only be changed before the company is contacted")
    for m in c.matches:
        m.selected = m.id in body.selected
    return cases.save(c)


class AddMatch(StaffAction):
    entity_id: str


@app.post("/cases/{cid}/matches", response_model=cases.Case)
def add_match(cid: str, body: AddMatch):
    """Add a result found in search to the request."""
    c = _case_or_404(cid)
    if c.status != "new":
        raise HTTPException(409, "Partners can only be changed before the company is contacted")
    e = index.load_entities().get(body.entity_id)
    if not e:
        raise HTTPException(404, "unknown entity")
    if not any(m.id == e.id for m in c.matches):
        c.matches.insert(0, cases.Match(id=e.id, name=e.name, entity_type=e.entity_type, role=e.role, unit=e.unit,
                                        institution=e.source_label, why="Added by hand from Explore",
                                        plain=e.description[0] if e.description else None, url=e.source_urls[0],
                                        contact=e.email, selected=True))
        cases.log(c, body.actor, "added", f"Added {e.name}")
        if c.offer:   # a hand-picked asset is a pitch partner too, so it gets its numbered source
            c.offer.sources.append(cases._source(len(c.offer.sources) + 1, c.matches[0], index.load_entities(),
                                                 c.offer.lang))
    return cases.save(c)


class Rematch(StaffAction):
    query: str = Field(..., min_length=2, max_length=300)


@app.post("/cases/{cid}/rematch", response_model=cases.Case)
def rematch(cid: str, body: Rematch):
    return cases.rematch(_case_or_404(cid), body.query, body.actor)


class DraftReq(StaffAction):
    lang: Literal["en", "de", "fr"] = "en"
    slots: list[str] = []
    sender: str = ""
    team: str = ""
    link: str = Field("", max_length=500)


@app.post("/cases/{cid}/draft")
def draft(cid: str, body: DraftReq):
    c = _case_or_404(cid)
    if not any(m.selected for m in c.matches):
        raise HTTPException(400, "Choose at least one partner first")
    return cases.draft_email(c, body.lang, body.slots, body.sender, body.team, body.link)


class BriefReq(StaffAction):
    lang: Literal["en", "de", "fr"] = "en"
    email: str = ""
    team: str = ""


@app.post("/cases/{cid}/brief")
def prepare_brief(cid: str, body: BriefReq):
    """Output 1 (plain explanation for the officer) + Output 2 (executive brief, published under a private link)."""
    c = _case_or_404(cid)
    if not any(m.selected for m in c.matches):
        raise HTTPException(400, "Choose at least one partner first")
    if not c.company:
        raise HTTPException(400, "Add the company name before preparing the pitch")
    out = brief.build(c, body.lang, {"name": body.actor, "email": body.email, "team": body.team})
    token = (c.outreach.get("brief") or {}).get("token") or secrets.token_urlsafe(12)
    c.outreach = {**c.outreach, "brief": {"token": token, "lang": body.lang, "at": cases._now(), "data": out["brief"],
                                          "explainer": out["explainer"], "stats": out["stats"]}}
    cases.log(c, body.actor, "brief_prepared",
              f"Executive brief prepared ({body.lang.upper()}): {out['stats']['claims']} sourced statements, "
              f"{out['stats']['publications']} publications")
    cases.save(c)
    return {"token": token, **out}


@app.get("/briefs/{token}")
def get_brief(token: str):
    """Public, read-only executive brief (the private link is the only key)."""
    for c in cases.list_cases():
        b = (c.outreach or {}).get("brief")
        if b and secrets.compare_digest(b["token"], token):
            return {**b["data"], "prepared_at": b["at"]}
    raise HTTPException(404, "unknown brief")


class Outcome(StaffAction):
    kind: Literal["email", "call", "closed"]
    detail: str = ""
    subject: str = ""
    body: str = ""


@app.post("/cases/{cid}/outcome", response_model=cases.Case)
def outcome(cid: str, body: Outcome):
    c = _case_or_404(cid)
    if not any(m.selected for m in c.matches):
        raise HTTPException(409, "Choose at least one partner first")
    if body.kind == "email":
        c.status = "contacted"
        c.outreach = {"subject": body.subject, "body": body.body, "sent_at": cases._now()}
        cases.log(c, body.actor, "emailed", f"Invitation email to {c.contact_email or c.company}")
    elif body.kind == "call":
        c.status = "call_scheduled"
        c.outreach = {**c.outreach, "call": body.detail}
        cases.log(c, body.actor, "call_scheduled", f"Call planned: {body.detail}")
    else:
        c.status = "closed"
        cases.log(c, body.actor, "closed", body.detail)
    return cases.save(c)


@app.get("/cases/{cid}/invite.ics")
def invite(cid: str, start: str, minutes: int = Query(30, ge=10, le=240), organizer: str = "", organizer_email: str = ""):
    c = _case_or_404(cid)
    try:
        body = cases.ics(c, start, minutes, organizer, organizer_email)
    except ValueError:
        raise HTTPException(400, "start must be an ISO date-time, e.g. 2026-10-22T14:00") from None
    return Response(body, media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="bern-call-{c.id}.ics"'})
