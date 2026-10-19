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

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from .knowledge_access import require_case_representative
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (archetypes, brief, cases, crawl, dashboard, documents, index, llm, plain, reply, search as search_mod, showcase,
               suggest, understand)
from .config import DATA_DIR, load_sources, settings
from .schema import EntityDetail, RelatedRef, SearchResponse
from .storage import StorageError

STATIC = Path(__file__).parent / "static"


def _warm_up():
    """Load the embedding model and the index before the first user query (cold start ~15 s on CPU)."""
    try:
        if not index.load_entities():
            return
        index.embed(["warm up"], query=True)
        showcase.build()
    except Exception as e:  # noqa: BLE001 - warm-up must never crash the server
        print(f"[api] warm-up skipped: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="Research & Expertise Navigator", version="0.3.0", lifespan=lifespan)
from .knowledge_api import router as knowledge_router
app.include_router(knowledge_router)
from .delivery_api import router as delivery_router
app.include_router(delivery_router)
from .speech import router as speech_router
app.include_router(speech_router)
from .discovery_api import router as discovery_router
from .vault_api import router as vault_router
app.include_router(discovery_router)
app.include_router(vault_router)
from .knowledge_workflow import router as knowledge_workflow_router
app.include_router(knowledge_workflow_router)


@app.middleware('http')
async def staff_workspace_boundary(request: Request, call_next):
    if request.url.path == '/cases' or request.url.path.startswith('/cases/'):
        from .knowledge_access import require_case_member
        try:
            require_case_member(request)
        except HTTPException as error:
            return JSONResponse({'detail': error.detail}, status_code=error.status_code)
    return await call_next(request)


@app.exception_handler(StorageError)
def _storage_error(_req: Request, e: StorageError):
    """Storage down / schema outdated: structured 503 instead of an opaque 500."""
    return JSONResponse(status_code=503, content={"error": e.code, "detail": e.detail, "backend": e.backend})

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def _meter_apertus(request: Request, call_next):
    """Tokens and latency of every request that calls Apertus go to the usage log (cost on the dashboard)."""
    t0 = time.monotonic()
    with llm.metered() as m:
        response = await call_next(request)
    if m.calls:
        route = request.scope.get("route")
        m.case_id = m.case_id or request.path_params.get("cid", "")
        dashboard.record(f"{request.method} {getattr(route, 'path', request.url.path)}", m, time.monotonic() - t0)
    return response


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
        "eval": {k: v for k, v in ev.items() if k not in ("per_query", "twins")} if (ev := _json("eval_report.json")) else None,
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


class SuggestReq(BaseModel):
    text: str = Field(..., min_length=2, max_length=500)
    lang: Literal["en", "de", "fr"] = "en"


@app.post("/companies/suggest", response_model=suggest.Suggestions)
def suggest_companies(body: SuggestReq):
    """Broad search without a company: up to three companies suggested by Apertus, each checked on its own
    homepage. A search that is a website link comes back as `link` (create the request from it directly)."""
    return suggest.suggest(body.text, body.lang)


@app.get("/medtech-areas")
def get_medtech_areas():
    """Medtech areas and niches offered as filters on a new request (config/medtech_areas.yaml)."""
    return [{"id": a["id"], "label": a["label"], "niches": [{"id": n["id"], "label": n["label"]} for n in a.get("niches", [])]}
            for a in cases.medtech_areas()]


@app.get("/dashboard")
def get_dashboard():
    """Staff only (Caddy): Apertus cost per request and per route, recall of the saved eval runs, re-extraction cost."""
    try:
        names = {c.id: cases.guess_company(c) for c in cases.list_cases()}
    except StorageError:
        names = None                       # the cost figures do not depend on the case store
    return dashboard.build(names)


@app.get("/cases")
def list_cases():
    return [{"id": c.id, "company": cases.guess_company(c), "status": c.status, "country": c.country, "canton": c.canton,
             "area": c.area, "niche": c.niche,
             "updated_at": c.updated_at, "created_at": c.created_at, "summary": c.analysis.summary[:220],
             "selected": sum(m.selected for m in c.matches), "has_brief": bool((c.outreach or {}).get("brief")),
             "matched": bool(c.matches), "views": ((c.outreach or {}).get("brief") or {}).get("views", 0),
             "replies": len((c.outreach or {}).get("replies", []))}
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
    from . import vault
    try:
        vault.validate_references(req.documents)
        return cases.create(req)
    except cases.company_web.FetchError as e:
        raise HTTPException(422, str(e)) from None
    except vault.VaultError as e:
        raise HTTPException(422, str(e)) from None


@app.get("/cases/{cid}", response_model=cases.Case)
def get_case(cid: str):
    c = _case_or_404(cid)
    if c.offer is None and c.matches and c.status == "new":   # requests created before the paragraph existed
        c.offer = cases.summarize_offer(c)
        cases.save(c)
    if not c.company and cases.guess_company(c):              # requests created before the name was read
        c.company = cases.guess_company(c)
        cases.save(c)
    return c


@app.delete("/cases/{cid}")
def delete_case(cid: str):
    _case_or_404(cid)
    cases.delete(cid)
    from . import published_pitch
    published_pitch.withdraw(cid)
    return {"ok": True}


class Details(StaffAction):
    company: str = Field(..., min_length=1, max_length=200)
    contact_name: str = Field("", max_length=200)
    contact_email: str = Field("", max_length=200)


@app.post("/cases/{cid}/details", response_model=cases.Case)
def set_details(cid: str, body: Details):
    """Company and contact person — optional corrections; the pitch does not wait for them."""
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
def draft(cid: str, body: DraftReq, user=Depends(require_case_representative)):
    c = _case_or_404(cid)
    if not any(m.selected for m in c.matches) and not c.outreach.get("brief"):
        raise HTTPException(400, "Choose at least one partner first")
    return cases.draft_email(c, body.lang, body.slots, body.sender, body.team, body.link)


class BriefReq(StaffAction):
    knowledge_sources: list[dict[str, str]] | None = Field(default=None, max_length=20)
    lang: Literal["en", "de", "fr"] | None = None      # the CEO's pitch; None: from where the company is
    ui_lang: Literal["en", "de", "fr"] | None = None   # the officer's preface; None: same as the pitch
    email: str = ""
    team: str = ""
    primary_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    company_logo: str | None = Field(None, max_length=400000)


@app.post("/cases/{cid}/brief")
def prepare_brief(cid: str, body: BriefReq, request: Request, user=Depends(require_case_representative)):
    """"Generate pitch": Output 1 (strategic pitch for the CEO, published under a private link) + Output 2
    (simplified preface for the officer). Nothing has to be entered: name and language come from the request.
    Approved Knowledge Base companies can be added to the partners."""
    c = _case_or_404(cid)
    from . import knowledge_workflow, knowledge_access
    approved = []
    selections = body.knowledge_sources
    if selections is None:
        selections = (c.outreach.get("brief") or {}).get("knowledge_sources", [])
    if selections:
        knowledge_access.require_member(request)
        try:
            approved = knowledge_workflow.resolve(c, selections)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
    if not any(m.selected for m in c.matches) and not approved:
        raise HTTPException(400, "Choose at least one supported research or company source first")
    lang = body.lang or brief.pitch_lang(c)
    c.company = cases.guess_company(c)
    out = brief.build(c, lang, {"name": body.actor, "email": body.email, "team": body.team}, body.ui_lang)
    knowledge_workflow.enrich(out, c, approved)
    from .pitch_branding import validate_logo
    old = c.outreach.get("brief") or {}
    branding = dict((old.get("data") or {}).get("branding", {}))
    if body.primary_color is not None:
        branding["primary_color"] = body.primary_color.lower()
    if body.company_logo is not None:
        try:
            branding["company_logo"] = validate_logo(body.company_logo)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    out["brief"]["branding"] = branding
    # the same link stays valid for another BRIEF_LINK_DAYS; a disabled link is never switched back on
    token = old.get("token") if old.get("token") and not old.get("revoked_at") else secrets.token_urlsafe(12)
    seen = {k: old[k] for k in ("views", "first_view", "last_view") if k in old and token == old.get("token")}
    if old.get("token") and token != old["token"]:   # the disabled link keeps answering "no longer active", not 404
        c.outreach = {**c.outreach, "retired_links": [*c.outreach.get("retired_links", []), old["token"]]}
    c.outreach = {**c.outreach, "brief": {"token": token, "lang": lang, "at": cases._now(), "data": out["brief"],
                                          "explainer": out["explainer"], "summary": out["summary"], "stats": out["stats"],
                                          "knowledge_sources": [{key: source[key] for key in ("id", "source_id", "revision")}
                                                                for source in (selections or [])],
                                          "expires_at": reply.new_expiry(), **seen}}
    cases.log(c, body.actor, "brief_prepared",
              f"Pitch generated ({lang.upper()}): {out['stats']['claims']} sourced statements, "
              f"{out['stats']['publications']} publications")
    cases.save(c)
    from . import published_pitch
    published_pitch.save(token, c.id, out['brief'], c.outreach['brief']['at'])
    from . import discovery
    for source in approved:
        if source.get('candidate_id'):
            discovery.mark_used(source['candidate_id'])
    return {"token": token, **out}


def _brief_case(token: str) -> cases.Case:
    """The request behind a private link; 410 (with whom to ask) once the link is disabled or expired."""
    key = token.encode()
    for c in cases.list_cases():
        b = (c.outreach or {}).get("brief")
        if not b:
            continue
        current = secrets.compare_digest(b["token"].encode(), key)
        retired = any(secrets.compare_digest(t.encode(), key) for t in c.outreach.get("retired_links", []))
        if current or retired:
            if (st := "revoked" if retired else reply.state(b)) != "ok":
                contact = b["data"].get("contact") or {}
                raise HTTPException(410, {"state": st, "labels": reply.labels(b["lang"]), "email": contact.get("email", "")})
            return c
    raise HTTPException(404, "unknown brief")


@app.get("/briefs/{token}")
def get_brief(token: str, preview: bool = False):
    """Public, read-only executive brief (the private link is the only key). Each opening by the company is
    counted (time only, nothing about the reader); the officer's preview is not."""
    c = _brief_case(token)
    b = c.outreach["brief"]
    if not preview:
        reply.record_view(c)
    return {**b["data"], "prepared_at": b["at"], "expires_at": reply.expires(b),
            "reply": reply.labels(b["lang"], (b["data"].get("contact") or {}).get("name", ""))}


@app.post("/briefs/{token}/reply", status_code=201)
def reply_to_brief(token: str, body: reply.Reply):
    """The company answers the pitch: visit, call or question. The request moves to "interested"."""
    c = _brief_case(token)
    if reply.too_many(c):
        raise HTTPException(429, "This pitch has already received several replies; please write to us by email.")
    reply.record_reply(c, body)
    return {"ok": True}


@app.post("/cases/{cid}/brief/revoke", response_model=cases.Case)
def revoke_brief(cid: str, body: StaffAction):
    """Disable the private link now. Preparing the pitch again creates a new link."""
    c = _case_or_404(cid)
    b = c.outreach.get("brief")
    if not b:
        raise HTTPException(404, "No pitch prepared yet")
    if not b.get("revoked_at"):
        b["revoked_at"] = cases._now()
        cases.log(c, body.actor, "brief_revoked", "Disabled the pitch link")
        cases.save(c)
    return c


class Outcome(StaffAction):
    kind: Literal["email", "call", "closed"]
    detail: str = ""
    subject: str = ""
    body: str = ""


@app.post("/cases/{cid}/outcome", response_model=cases.Case)
def outcome(cid: str, body: Outcome, user=Depends(require_case_representative)):
    c = _case_or_404(cid)
    if not any(m.selected for m in c.matches) and not c.outreach.get("brief"):
        raise HTTPException(409, "Choose at least one partner first")
    if body.kind == "email":
        c.status = "contacted"
        # merged, not replaced: the brief (and its link in this very email) and the company's replies stay
        c.outreach = {**c.outreach, "subject": body.subject, "body": body.body, "sent_at": cases._now()}
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
def invite(cid: str, start: str, minutes: int = Query(30, ge=10, le=240), organizer: str = "", organizer_email: str = "", user=Depends(require_case_representative)):
    c = _case_or_404(cid)
    try:
        body = cases.ics(c, start, minutes, organizer, organizer_email)
    except ValueError:
        raise HTTPException(400, "start must be an ISO date-time, e.g. 2026-10-22T14:00") from None
    return Response(body, media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="bern-call-{c.id}.ics"'})
