"""Company requests ("cases"): company link or info -> plain summary -> partners in Bern -> pitch & invite.

Stored through storage.case_store(): SQLite (data/cases.db, one JSON document per case plus its
activity log) when DATABASE_URL is empty, nav."case"/case_match/case_event when it is set.
Nothing is sent anywhere by the server: emails open in the officer's own mail client (mailto)
and calls are offered as a calendar file (.ics).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

import yaml

from . import archetypes, company as company_web, documents as docs, index, llm, needs, plain, search, showcase, understand
from .config import CONFIG_DIR, DATA_DIR
from .storage import case_store

DB = DATA_DIR / "cases.db"
_lock = threading.Lock()

Status = Literal["new", "contacted", "call_scheduled", "interested", "closed"]   # interested: the company replied
# statuses from the former technical-review step, mapped when old requests are read
_LEGACY_STATUS = {"in_review": "new", "changes_requested": "new", "approved": "new"}


class Match(BaseModel):
    id: str
    name: str
    entity_type: str
    role: str | None = None
    unit: str | None = None
    institution: str = ""
    why: str = ""
    plain: str | None = None           # first descriptive sentence, for non-specialists
    url: str = ""
    contact: str | None = None
    confidence: float = 0.0
    via: str | None = None
    selected: bool = False
    archetype: str = ""                # see archetypes.py; filled in for older requests too

    @model_validator(mode="after")
    def _archetype(self):
        if not self.archetype:
            self.archetype = archetypes.classify(self.entity_type, self.name, self.role, self.contact, self.plain)
        return self


class OfferSource(BaseModel):
    """One cited asset, as a structured and traceable result."""
    n: int
    id: str
    name: str
    kind: str                          # type in the entity model, e.g. "People", "Facilities"
    entity_type: str = ""
    role: str = ""                     # function
    unit: str = ""                     # department / institute / research group
    institute: str = ""
    institution: str = ""
    contact: str = ""
    expertise: list[str] = []
    projects: list[str] = []
    infrastructure: list[str] = []
    about: str = ""
    why: str = ""                      # why it matches this company
    url: str = ""
    links: list[str] = []              # further source pages


class Offer(BaseModel):
    """What Bern offers the company, in one paragraph; every asset cited as [n] with its public source."""
    text: str
    sources: list[OfferSource] = []
    lang: str = "en"
    generated_by: str = "rules"


class Event(BaseModel):
    at: str
    actor: str
    kind: str
    text: str = ""


class Case(BaseModel):
    match_scope: Literal["bern", "north"] = "bern"
    id: str
    created_at: str
    updated_at: str
    status: Status = "new"
    company: str = ""                # may be filled in later (needed before pitching)
    contact_name: str = ""
    contact_email: str = ""
    country: str = ""
    canton: str = ""                 # when the company is in Switzerland
    city: str = ""                   # from a broad search ("glucose company in Milan")
    understood: list[dict] = []      # what the broad search recognised, with the words that triggered it
    area: str = ""                   # medtech area id   (config/medtech_areas.yaml)
    niche: str = ""                  # niche id within the area
    company_url: str = ""
    need: str = ""                   # what the company is looking for, if the officer knows
    website: company_web.CompanyWebsite | None = None   # what was read from company_url
    documents: list[docs.Document] = []                  # text read from files the company shared
    request_text: str = ""           # the officer's pasted information about the company
    analysis: plain.RequestAnalysis
    matches: list[Match] = []
    no_match_message: str | None = None
    offer: Offer | None = None
    outreach: dict = Field(default_factory=dict)
    events: list[Event] = []

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        if isinstance(data, dict) and data.get("status") in _LEGACY_STATUS:
            data = {**data, "status": _LEGACY_STATUS[data["status"]]}
        return data

    def source_text(self) -> str:
        """Everything known about the company, for finding the topics it shares with Bern."""
        return "\n".join(x for x in [self.need, *(d.text for d in self.documents), self.request_text,
                                      self.website.text if self.website else ""] if x)


class NewCase(BaseModel):
    match_scope: Literal["bern", "north"] = "bern"
    """The company's website link, shared documents (already read by POST /documents) and/or pasted
    information, an optional need, optional filters. Contact details can come later."""
    company_url: str = Field("", max_length=500)
    documents: list[docs.Document] = Field([], max_length=5)
    request_text: str = Field("", max_length=12000)
    need: str = Field("", max_length=500)
    company: str = Field("", max_length=200)
    contact_name: str = Field("", max_length=200)
    contact_email: str = Field("", max_length=200)
    country: str = Field("", max_length=100)
    canton: str = Field("", max_length=60)
    area: str = Field("", max_length=40)
    niche: str = Field("", max_length=40)
    lang: str = "en"
    actor: str = Field(..., min_length=1, max_length=120)
    broad: bool = False   # request_text is a one-line search ("glucose company in Milan"): read place and topic from it

    @model_validator(mode="after")
    def _something(self):
        if not self.company_url.strip() and not self.documents and len(self.request_text.strip()) < 3:
            raise ValueError("Give the company's website link, upload a document or paste some information.")
        return self


# "Dexcom is a U.S.-based ...", "FEMTOPRINT develops ...": the name that opens a profile sentence
_NAMED = re.compile(r"^(?!(?:the|this|that|our|we|it|its|they|he|she|their|company|firm|start-?up|die|das|der|diese|"
                    r"unsere|wir|sie|er|es|firma|unternehmen|le|la|les|l'|cette|notre|nous|ils|elles|il|elle|on|"
                    r"entreprise|société|looking|seeking|searching)\b)"
                    r"([A-Z0-9][\w&.,'’+\-]*(?:\s[\w&.,'’+\-]+){0,3}?)(?:'s)?\s+(?:is|are|was|ist|sind|est|sont|develops|entwickelt|développe|"
                    r"specialises|specializes|makes|builds|produces|offers|provides|designs|was founded|wurde)\b", re.I)


def guess_company(case: Case) -> str:
    """The company's name when the officer did not type it: as entered, the website's own name, the name the
    analysis read in the text, the name that opens the profile, or the website's domain ("" if none)."""
    if case.company:
        return case.company
    if case.website and case.website.name:
        return case.website.name.strip()
    a = case.analysis
    if a.company_name:
        return a.company_name.strip()
    for text in (a.summary, a.company_does):
        m = _NAMED.match((text or "").strip())
        if m and not m.group(1).lower().startswith(("a ", "an ", "un ", "une ", "ein ")):
            return m.group(1).strip(" ,")
    host = (re.sub(r"^[a-z][a-z0-9+.-]*://", "", case.company_url, flags=re.I).split("/")[0]).removeprefix("www.")
    return host.split(".")[0].capitalize() if host else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, updated_at TEXT, data TEXT NOT NULL)")
    return c


class SqliteCaseStore:
    """File backend (DATABASE_URL empty): the historical SQLite JSON-blob store."""
    name = "sqlite"

    def save(self, case: Case) -> None:
        with _lock, _conn() as c:
            c.execute("INSERT OR REPLACE INTO cases VALUES (?, ?, ?)", (case.id, case.updated_at, case.model_dump_json()))

    def get(self, cid: str) -> Case | None:
        with _conn() as c:
            row = c.execute("SELECT data FROM cases WHERE id = ?", (cid,)).fetchone()
        return Case.model_validate_json(row[0]) if row else None

    def list(self) -> list[Case]:
        with _conn() as c:
            rows = c.execute("SELECT data FROM cases ORDER BY updated_at DESC").fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    def delete(self, cid: str) -> None:
        with _lock, _conn() as c:
            c.execute("DELETE FROM cases WHERE id = ?", (cid,))


def save(case: Case) -> Case:
    case.updated_at = _now()
    case_store().save(case)
    return case


def get(cid: str) -> Case | None:
    return case_store().get(cid)


def list_cases() -> list[Case]:
    return case_store().list()


def delete(cid: str) -> None:
    case_store().delete(cid)


def log(case: Case, actor: str, kind: str, text: str = "") -> None:
    case.events.append(Event(at=_now(), actor=actor or "—", kind=kind, text=text))


# ---------------- matching ---------------------------------------------------
_ORDER = {"person": 0, "unit": 1, "infrastructure": 2, "project": 3}


def medtech_areas() -> list[dict]:
    p = CONFIG_DIR / "medtech_areas.yaml"
    return (yaml.safe_load(p.read_text()) or {}).get("areas", []) if p.exists() else []


def niche_query(area: str, niche: str) -> str:
    """Search terms for the chosen medtech niche (or, with only an area, one key term per niche)."""
    for a in medtech_areas():
        if a["id"] == area:
            if niche:
                return next((n["query"] for n in a.get("niches", []) if n["id"] == niche), "")
            return " ".join(n["query"].split()[0] for n in a.get("niches", []))
    return ""


PER_ARCHETYPE = 8


# ---- relevance gate: a company only meets partners with a specific, stated link to its topic ------------
# Semantic similarity cannot tell them apart (every medical profile scores 0.81-0.84 against any medical query);
# a specific word of the company's topic in the partner's own text can. These words say nothing about a topic.
_GENERIC = set("""clinical clinic medical medicine medtech health healthcare patient patients treatment treatments therapy
care research researchers development developing develop technology technologies technical innovation innovative
expertise expert experts partner partners partnership collaboration collaborations swiss switzerland bern international
global solution solutions service services application applications system systems product products device devices
digital manufacturing management platform advanced novel new based enabled access support market data quality
company companies business industry www com http https org""".split())
GENERIC_DF = 0.30          # a word in more than 30% of the indexed profiles is not specific either
NO_STRONG_MSG = ("No partner in Bern has a clear, specific link to this company's topics on its public pages. "
                 "Add what the company is looking for, or search with more specific terms.")
_df_cache: dict[int, tuple[int, dict[str, int]]] = {}


def _doc_freq() -> tuple[int, dict[str, int]]:
    """Document frequency of each token over the indexed profiles (the same text BM25 indexes), on any backend."""
    ents = index.load_entities()
    if id(ents) not in _df_cache:   # the file store returns the same object until the index is rebuilt
        df: dict[str, int] = {}
        for e in ents.values():
            for t in set(index.tokenize(e.search_text())):
                df[t] = df.get(t, 0) + 1
        _df_cache.clear()
        _df_cache[id(ents)] = (len(ents), df)
    return _df_cache[id(ents)]


def topic_words(query: str) -> set[str]:
    """The query's specific words: not generic filler, not in most profiles."""
    n, df = _doc_freq()
    return {t for t in index.tokenize(query) if len(t) > 2 and t not in _GENERIC and df.get(t, 0) <= GENERIC_DF * n}


def topic_support(text: str, words: set[str]) -> set[str]:
    """The topic words a profile contains (singular or plural)."""
    low = text.lower()
    out = set()
    for t in words:
        base = t[:-1] if t.endswith("s") and len(t) > 4 else t
        if re.search(rf"\b{re.escape(base)}(?:s|es)?\b", low):
            out.add(t)
    return out


def central_words(query: str, words: set[str]) -> set[str]:
    """Topic words the company's query repeats ("hearing aid…, hearing loss…"): what the company is about."""
    seen: dict[str, int] = {}
    for t in index.tokenize(query):
        t = t[:-1] if t.endswith("s") and len(t) > 4 and t[:-1] in words else t
        seen[t] = seen.get(t, 0) + 1
    return {t for t in words if seen.get(t, 0) >= 2}


def specific(hits: set[str], central: set[str]) -> bool:
    """Two specific words in common, or one long word that is central to the company ("hearing" for a hearing-aid
    maker). A single other word is a coincidence ("implant": cochlear, dental or hip?), and a short one is
    ambiguous anyway ("hearing aid" is not "AID", "hearing loss" is not "weight loss")."""
    return len(hits) >= 2 or any(len(t) >= 5 and t in central for t in hits)


def find_matches(analysis: plain.RequestAnalysis, k: int = 40) -> tuple[list[Match], str | None]:
    """Everything Bern can offer this company, classified into the entity model (agents, offering,
    activities, capital, concepts). Up to MAX_PER_TYPE per type, in relevance order; among people the leads come first, so a
    company meets the professor or group head before an intern."""
    ents = index.load_entities()
    r = search.search(analysis.search_query, k=k, llm_explain=False)
    if r.abstained:
        return [], r.message
    out = []
    for x in r.results:
        e = ents.get(x.id)
        desc = " ".join(e.description) if e and e.description else ""
        out.append(Match(
            id=x.id, name=x.person_or_unit, entity_type=x.entity_type, role=x.role, unit=x.affiliation.unit,
            institution=x.institution, why=x.why_match, url=(x.sources[0].url if x.sources else ""),
            plain=(e.description[0] if e and e.description else None), contact=x.contact,
            confidence=x.confidence, via=x.via,
            archetype=archetypes.classify(x.entity_type, x.person_or_unit, x.role, e.email if e else x.contact, desc)))

    # only partners whose own public text names the company's topic; a person found through a lab, when the lab does
    words = topic_words(analysis.search_query)
    central = central_words(analysis.search_query, words)
    groups = {e.name: e for e in ents.values() if e.entity_type != "person"}

    def strong(m: Match) -> bool:
        e, parent = ents.get(m.id), groups.get(m.via or "")
        return bool(e and specific(topic_support(e.search_text(), words), central)) or \
            bool(parent and specific(topic_support(parent.search_text(), words), central))
    out = [m for m in out if strong(m)]
    if not out:
        return [], NO_STRONG_MSG

    def band(m: Match) -> int:  # stable sort keeps relevance order within each band
        e = ents.get(m.id)
        sen = search.seniority(e) if e and m.entity_type == "person" else 1.0
        return 0 if sen >= 1.2 else 1 if sen >= 0.8 else 2
    out.sort(key=lambda m: (archetypes.ORDER.get(m.archetype, 99), band(m)))
    per: dict[str, int] = {}
    kept = []
    for m in out:  # a limit per type of the entity model (people, organizations, facilities…)
        kind = archetypes.TYPE_OF.get(m.archetype, m.archetype)
        per[kind] = per.get(kind, 0) + 1
        if per[kind] <= archetypes.MAX_PER_TYPE.get(kind, PER_ARCHETYPE):
            kept.append(m)
    # Apertus explains only the assets that will be cited (~10 instead of 40 calls)
    picked = [m for m in pick_assets(kept) if not m.via and m.id in ents]
    if picked and llm.available():
        terms = r.expanded_terms
        whys = list(search._pool.map(llm.bound(lambda m: search.explain(analysis.search_query, ents[m.id], terms)[0]), picked))
        for m, why in zip(picked, whys):
            m.why = why or m.why
    return kept, None


# a website in the broad search: "https://www.amplifon.com/", "www.bracco.com", or the whole text being "bracco.com"
_URL = re.compile(r"(?<!\S)(?:https?://\S+|www\.[\w-]+(?:\.[\w-]+)+\S*)", re.I)
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?:/\S*)?$", re.I)


def split_link(text: str) -> tuple[str, str]:
    """(website link, the rest of the text) from a broad search; ("", text) when it names no website."""
    t = text.strip()
    if _DOMAIN.match(t):
        return t, ""
    m = _URL.search(t)
    if not m:
        return "", text
    return m.group(0).rstrip(".,;)"), " ".join((t[:m.start()] + " " + t[m.end():]).split())


def create(req: NewCase) -> Case:
    """Raises company_web.FetchError when the link cannot be read (the officer can paste the text instead)."""
    if req.broad and not req.company_url.strip():
        # a link typed into the broad search is the company's website, not a topic: read it instead of
        # searching Bern for "bracco com"
        req.company_url, req.request_text = split_link(req.request_text)
        req.broad = bool(req.request_text.strip())
    site = company_web.read(req.company_url) if req.company_url.strip() else None
    name = req.company.strip() or (site.name if site else "")
    # the company's own pitch says most about what they do, then the officer's notes, then the website
    text = "\n\n".join(x for x in [*(d.text for d in req.documents), req.request_text.strip(),
                                    site.text if site else ""] if x)
    u = understand.understand(req.request_text) if req.broad else None
    if u:
        # broad search: place and topic come from the sentence; explicit filters still win
        req.country, req.canton = req.country or u.country, req.canton or u.canton
        if not req.area:
            req.area, req.niche = u.area, u.niche
    if site or req.documents or req.need.strip():
        analysis = plain.analyze_company(name, site.description if site else "", text, req.need, req.lang,
                                         page_titles=[p.title for p in site.pages] if site else None)
    elif u:
        # search with what is left once the place and filler words are removed ("glucose", not "Milan")
        analysis = plain.analyze_request(u.rest or req.request_text, req.lang)
        analysis.search_query = u.rest or analysis.search_query
    else:
        analysis = plain.analyze_request(req.request_text, req.lang)   # an email from the company: the old path
    # the chosen medtech niche sharpens the search; the company's own words stay in the query
    extra = niche_query(req.area, req.niche)
    if extra:
        analysis.search_query = f"{extra} {analysis.search_query}".strip()
    matches, msg = find_matches(analysis)
    now = _now()
    swiss = req.country.strip().lower() in ("switzerland", "schweiz", "suisse", "svizzera", "ch")
    case = Case(id=uuid.uuid4().hex[:10], created_at=now, updated_at=now, company=name, match_scope=req.match_scope,
                company_url=site.url if site else "", need=req.need.strip(), website=site, documents=req.documents,
                contact_name=req.contact_name.strip(), contact_email=req.contact_email.strip(),
                country=req.country.strip(), canton=req.canton.strip() if swiss else "", area=req.area, niche=req.niche,
                city=u.city if u else "", understood=[d.model_dump() for d in u.detections] if u else [],
                request_text=req.request_text.strip(), analysis=analysis, matches=matches, no_match_message=msg)
    case.company = guess_company(case)
    if m := llm.current_meter():
        m.case_id = case.id          # the Apertus calls of this request count towards its cost
    log(case, req.actor, "created", f"Request received{' from ' + case.company if case.company else ''}")
    for d in req.documents:
        log(case, "Navigator", "document", f"Read {d.kind} document {d.name}")
    if site:
        log(case, "Navigator", "website", f"Read {len(site.pages)} page(s) of {site.url}")
    case.offer = summarize_offer(case, req.lang)
    log(case, "Navigator", "analysed",
        f"Company profile by {'Apertus' if analysis.generated_by == 'apertus' else 'rules'}; "
        f"{len(case.offer.sources)} Bern assets cited")
    return save(case)


def rematch(case: Case, query: str, actor: str) -> Case:
    keep = {m.id: m for m in case.matches if m.selected}
    case.analysis.search_query = query
    found, msg = find_matches(case.analysis)
    case.matches = list(keep.values()) + [m for m in found if m.id not in keep]
    case.no_match_message = msg if not case.matches else None
    log(case, actor, "rematched", f"Searched again for: {query}")
    return save(case)


# ---------------- what Bern offers (one sourced paragraph) ---------------------
# How many assets of each type of the entity model go into the paragraph (and the pitch)
OFFER_QUOTA = {"person": 4, "organization": 2, "company": 1, "facility": 2, "instrument": 1, "service": 1,
               "digital": 1, "study": 1, "project": 2, "technology": 1, "programme": 1, "funding": 1, "proof": 1}


def _kind(m: Match) -> str:
    return archetypes.TYPE_OF.get(m.archetype, m.entity_type)


def _label(kind: str, lang: str) -> str:
    for g in archetypes.GROUPS:
        for t in g["types"]:
            if t["id"] == kind:
                return t["label"].get(lang) or t["label"]["en"]
    return kind


def pick_assets(matches: list[Match]) -> list[Match]:
    """The strongest assets per type, in relevance order (people: leads first, as find_matches sorts)."""
    used: dict[str, int] = {}
    out = []
    for m in matches:
        k = _kind(m)
        if used.get(k, 0) < OFFER_QUOTA.get(k, 1):
            used[k] = used.get(k, 0) + 1
            out.append(m)
    order = list(OFFER_QUOTA)
    return sorted(out, key=lambda m: order.index(_kind(m)) if _kind(m) in order else 99)


_NUM = {"en": ["one", "two", "three", "four", "five"], "de": ["eine", "zwei", "drei", "vier", "fünf"],
        "fr": ["un", "deux", "trois", "quatre", "cinq"]}
_OT = {
    "en": {"intro": "For {company}, Bern offers", "people1": "one matching expert: {xs}.", "people": "{n} matching experts: {xs}.",
           "orgs": "Matching research units are {xs}.", "orgs1": "The matching research unit is {xs}.",
           "offer": "Relevant infrastructure and services include {xs}.", "act": "Related research activities include {xs}.",
           "and": "and", "company": "this company", "units": "the following research units: {xs}.", "need": "On “{need}”: {xs}."},
    "de": {"intro": "Für {company} bietet Bern", "people1": "eine passende Fachperson: {xs}.", "people": "{n} passende Fachpersonen: {xs}.",
           "orgs": "Passende Forschungseinheiten sind {xs}.", "orgs1": "Die passende Forschungseinheit ist {xs}.",
           "offer": "Relevante Infrastruktur und Dienstleistungen umfassen {xs}.", "act": "Verwandte Forschungsaktivitäten sind {xs}.",
           "and": "und", "company": "diese Firma", "units": "folgende Forschungseinheiten: {xs}.", "need": "Zu «{need}»: {xs}."},
    "fr": {"intro": "Pour {company}, Berne offre", "people1": "un expert correspondant : {xs}.", "people": "{n} experts correspondants : {xs}.",
           "orgs": "Les unités de recherche correspondantes sont {xs}.", "orgs1": "L'unité de recherche correspondante est {xs}.",
           "offer": "Les infrastructures et services pertinents comprennent {xs}.", "act": "Les activités de recherche liées comprennent {xs}.",
           "and": "et", "company": "cette entreprise", "units": "les unités de recherche suivantes : {xs}.", "need": "Pour « {need} » : {xs}."},
}


def _join(xs: list[str], word: str) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + f" {word} " + xs[-1]


def _who(m: Match) -> str:
    """Role and unit, short: long page-copied roles keep their first two parts; no unit named twice."""
    role = ", ".join(x.strip() for x in (m.role or "").split(",")[:2] if x.strip())
    unit = m.unit if m.unit and m.unit.lower() not in role.lower() else ""
    return ", ".join(x for x in [role, unit] if x)


def _template(case: Case, picked: list[Match], lang: str, paired: dict[str, list[int]] | None = None) -> str:
    """Only indexed facts (name, role, unit, institution), each followed by its source number; then, for each
    stated need, the assets whose own pages show it."""
    t = _OT.get(lang, _OT["en"])
    n = {m.id: i for i, m in enumerate(picked, 1)}
    people = [m for m in picked if _kind(m) == "person"]
    orgs = [m for m in picked if _kind(m) in ("organization", "company")]
    offer = [m for m in picked if _kind(m) in ("facility", "instrument", "service", "digital")]
    act = [m for m in picked if m not in people + orgs + offer]
    cite = lambda m, extra="": f"{m.name}{' (' + extra + ')' if extra else ''} [{n[m.id]}]"  # noqa: E731
    out = [t["intro"].format(company=case.company or t["company"])]
    org_xs = _join([cite(m, m.institution) for m in orgs], t["and"]) if orgs else ""
    if people:
        xs = _join([cite(m, _who(m)) for m in people], t["and"])
        k = len(people)
        out[0] += " " + (t["people1"].format(xs=xs) if k == 1 else
                         t["people"].format(n=_NUM.get(lang, _NUM["en"])[k - 1] if k <= 5 else k, xs=xs))
        if orgs:
            out.append((t["orgs1"] if len(orgs) == 1 else t["orgs"]).format(xs=org_xs))
    elif orgs:
        out[0] += " " + t["units"].format(xs=org_xs)
    if offer:
        out.append(t["offer"].format(xs=_join([cite(m) for m in offer], t["and"])))
    if act:
        out.append(t["act"].format(xs=_join([cite(m) for m in act], t["and"])))
    for need, ns in (paired or {}).items():
        if ns:
            out.append(t["need"].format(need=need, xs=_join([f"{picked[k - 1].name} [{k}]" for k in ns], t["and"])))
    return " ".join(out)


def _source(i: int, m: Match, ents: dict, lang: str) -> OfferSource:
    e = ents.get(m.id)
    urls = list(dict.fromkeys([m.url, *(e.source_urls if e else [])]))
    clip = lambda xs, k: [x for x in dict.fromkeys(xs or []) if x and x != m.name][:k]  # noqa: E731
    return OfferSource(
        n=i, id=m.id, name=m.name, kind=_label(_kind(m), lang), entity_type=m.entity_type,
        role=m.role or "", unit=m.unit or "", institute=(e.institute if e else "") or "", institution=m.institution,
        contact=m.contact or (e.email if e else "") or "", expertise=clip(e.expertise if e else [], 5),
        projects=clip(e.projects if e else [], 3), infrastructure=clip(e.infrastructure if e else [], 3),
        about=(m.plain or (e.description[0] if e and e.description else ""))[:300], why=m.why,
        url=urls[0] if urls else "", links=urls[1:4])


# promotional adjectives: removed from the model's prose ("a unique ecosystem" -> "an ecosystem")
_ADJ = re.compile(r"\b(unique|world[- ]class|renowned|excellent|outstanding|cutting[- ]edge|state[- ]of[- ]the[- ]art|"
                  r"comprehensive|robust|innovative|deep|advanced|extensive|einzigartig|weltklasse|renommiert|exzellent|innovativ|"
                  r"unique|renommé|exceptionnel|innovant)e?[ns]?\s+", re.I)
# what cannot be cleaned up: superlative claims about quality or rank
_HYPE = re.compile(r"\b(best|leading (expert|experts|institution|centre|center|hub|research|university)|world[- ]leading|"
                   r"führend|meilleur)", re.I)


def _clean(text: str) -> str:
    t = _ADJ.sub("", text)
    t = re.sub(r"\b([Aa]) ([aeiouAEIOU])", r"\1n \2", t)       # "a ecosystem" -> "an ecosystem"
    return " ".join(t.split())
_TITLE = re.compile(r"^(prof|dr|med|phil|pd|em|sc|ing|msc|phd|the|and|for|of|der|die|das|und|des|du|de|la|le|et)$", re.I)


def _name_keys(src: OfferSource) -> list[str]:
    words = [w for w in re.findall(r"[\w-]{3,}", src.name) if not _TITLE.match(w.strip("."))]
    if src.entity_type == "person":
        return words[-1:]                                   # the surname
    return words[:4]


def _check(text: str, sources: list[OfferSource]) -> bool:
    """Precise or nothing: every asset cited, each citation right after that asset's name, nothing extra."""
    cites = [(int(m.group(1)), m.start()) for m in re.finditer(r"\[(\d+)\]", text)]
    by_n = {s.n: s for s in sources}
    if {n for n, _ in cites} != set(by_n) or _HYPE.search(text) or len(text.split()) > 190:
        return False
    for n, pos in cites:
        window = text[max(0, pos - 160):pos].lower()
        if not any(k.lower() in window for k in _name_keys(by_n[n])):
            return False                                    # citation attached to the wrong asset
    return all(sum(1 for x, _ in cites if x == n) <= 2 for n in by_n)


_ALSO = {"en": "Also relevant:", "de": "Ebenfalls relevant:", "fr": "Également pertinent :"}


def _zones(text: str, sources: list[OfferSource]) -> list[tuple[int, int, str]]:
    """Where other names sit in the text: units, institutes and institutions of the assets ("Sensing & Monitoring
    Lab" holds "Monitoring", which is another asset). An asset's name found inside one of these is not that asset."""
    names = {x for s in sources for x in (s.unit, s.institute, s.institution) if x and len(x.split()) > 1}
    return [(m.start(), m.end(), n) for n in names
            for m in re.finditer(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text, re.I)]


def _cite_keys(x: OfferSource) -> list[str]:
    if x.entity_type == "person":
        return _name_keys(x)                                  # surname
    # full name, the part before ":" or " – ", then shorter word prefixes (min. 3 words) of long names, and an
    # identifier the prose may use alone ("SPN-005 – Pilot study on …" -> "SPN-005")
    head = re.split(r":| [–-] ", x.name)[0].strip()
    words = re.sub(r"^(a|an|the)\s+", "", head, flags=re.I).split()
    ident = [words[0]] if words and re.search(r"\d", words[0]) and len(words[0]) >= 4 else []
    return list(dict.fromkeys([x.name, head, *(" ".join(words[:k]) for k in range(len(words), 2, -1)), *ident]))


def _key_flags(k: str) -> int:
    """A one-word name is matched as written ("Monitoring", the service, not "glucose monitoring"); longer names
    in any case."""
    return re.I if " " in k.strip() else 0


def _cite(text: str, sources: list[OfferSource], lang: str = "en") -> str | None:
    """Insert [n] after the first mention of each asset's name. The model writes names only: given numbers,
    it attached them to the wrong assets. Longer names are placed first, and a name inside another asset's name
    or unit does not count ("Monitoring" in "Sensing & Monitoring Lab"). None when an asset is not mentioned
    recognisably."""
    text = re.sub(r"\s*\[\d+\]", "", text)
    zones = _zones(text, sources)
    spots, missing = [], []
    for x in sorted(sources, key=lambda s: -len(s.name)):
        hit = None
        for k in _cite_keys(x):
            for m in re.finditer(rf"(?<![\w-]){re.escape(k)}(?![\w-])", text, _key_flags(k)):
                taken = any(a <= m.start() < b for a, b, _ in spots)
                inside = any(a <= m.start() and m.end() <= b and n.lower() != x.name.lower() for a, b, n in zones)
                if not taken and not inside:
                    hit = (m.start(), m.end(), x.n)
                    break
            if hit:
                break
        if hit:
            spots.append(hit)
        else:
            missing.append(x)
    if len(missing) * 3 > len(sources):
        return None
    for a, b, n in sorted(spots, key=lambda z: -z[1]):
        text = f"{text[:b]} [{n}]{text[b:]}"
    if missing:   # the few assets the prose left out, in one closing sentence
        missing.sort(key=lambda x: x.n)
        lead = _ALSO.get(lang, _ALSO["en"])
        text = f"{text.rstrip()} {lead} " + _join([f"{x.name}{' (' + x.role + ')' if x.role else ''} [{x.n}]"
                                                   for x in missing], _OT.get(lang, _OT["en"])["and"]) + "."
    return text


# ---- claim check: every word of the paragraph that says something must come from the sources ------------------
# Words that connect or frame, in the three languages; everything else (a role, a topic, "experience",
# "conducted", "manufacturing") has to be found in the text of the asset it is said about.
_GLUE = set("""about across additional additionally along alongside also another available based between brings bring
both called could contribute contributes contributing could engage engaged especially focus focused focuses focusing
further their there these those through together where which while whose within would should other others offer offers
offering provide provides providing relevant support supports supported related include includes including including
works working company research particularly various several helps study studies project projects group groups team
teams center centre university institute department laboratory field areas topics topic theme themes involved involve
welche welcher welches sowie bietet bieten arbeitet arbeiten können könnte unterstützt ausserdem außerdem zudem darüber
hinaus insbesondere bereich bereichen zusammenarbeit dabei deren dessen unter andere anderen weitere weiteren durch
zwischen beschäftigt befasst forschung gruppe projekt projekte zentrum firma unternehmen
using specialized specialised dedicated knowledge areas benefit pursue pursued available
cover covers covering concern concerns deals addresses explore explores describes described located umfasst umfassen couvre portent
offre offrent propose proposent travaille travaillent notamment également ainsi autour entre dont leurs pourrait
peuvent peut domaine domaines grâce comme celle celui aussi plusieurs recherche groupe projet projets centre entreprise
societe société""".split())
def _supported(word: str, low: str) -> bool:
    """`word` in the lowercased source text, as the word, its plural, or (long words) its stem: "develops" ~
    "develop", "sensors" ~ "sensor"."""
    if needs.has(low, word):
        return True
    return len(word) >= 7 and re.search(rf"(?<![\w-]){re.escape(word[:6])}", low) is not None


def _chunks(sentence: str) -> list[tuple[str, set[int], bool]]:
    """A sentence cut into (text, the assets it is said about, whether it is the framing before any citation).
    Before the first citation: all cited assets ("For clinical validation, Dexcom can engage A [1] and B [2]").
    After a citation: that asset, and its apposition ("A [1], group head of …,"). Assets joined by "and" share
    what follows the last of them ("A [1] and B [2], …, bring machine learning": both must show it)."""
    bits = re.split(r"\[(\d+)\]", sentence)
    out = [(bits[0], {int(n) for n in bits[1::2]}, True)]
    group: list[int] = []
    for i in range(1, len(bits), 2):
        n, seg = int(bits[i]), bits[i + 1]
        group.append(n)
        if re.match(r"\s*,?\s*(which|who|whose|where|that|welche|welcher|welches|der|die|das|deren|dessen|qui|dont|où)\b",
                    seg, re.I) and not re.search(r",\s*(and|und|et)\s+[^\[]{0,80}$", seg):
            out.append((seg, {n}, False))          # ", which …": said about this asset only
            group = []
            continue
        ap = re.match(r"\s*,([^,\[]{0,140}),", seg)
        if ap:
            out.append((ap.group(1), {n}, False))
            seg = seg[ap.end():]
        if i + 2 < len(bits) and re.fullmatch(r"\s*,?\s*(and|und|et|as well as|sowie|ainsi que)\b[^\[]{0,80}", seg, re.I):
            out.append((seg, set(group), False))   # "and Prof. B": names; what follows B is said about both
            continue
        out.append((seg, set(group), False))
        group = []
    return out


def _faithful(text: str, sources: list[OfferSource], case: Case, texts: dict[int, str],
              paired: dict[str, list[int]]) -> str | None:
    """The first claim the sources do not support, as feedback for the model; None when every claim is supported."""
    return next(_unsupported(text, sources, case, texts, paired), None)


def _unsupported(text: str, sources: list[OfferSource], case: Case, texts: dict[int, str],
                 paired: dict[str, list[int]]):
    """Every claim the sources do not support:
    - a company need is named only next to assets whose own text shows it (`needs.pairs`);
    - every other word that says something is in the text of the asset(s) it is said about, or in what the
      company itself told us."""
    tw = needs.topic(case.analysis)
    own = " ".join([case.company, case.analysis.summary, case.analysis.company_does, *case.analysis.offerings,
                    *case.analysis.keywords, case.analysis.search_query]).lower()
    kinds = {w: n for n in case.analysis.company_needs for w in needs.parts(n, tw)[0]}
    names = {t for s in sources for t in index.tokenize(s.name)}
    for sentence in _sentences(_mark_all(text, sources)):
        if re.match(r"^\s*(Also relevant|Ebenfalls relevant|Également pertinent)", sentence):
            continue
        for chunk, who, framing in _chunks(sentence):
            if not who:
                continue
            for need in case.analysis.company_needs:   # the chunk names this need: its assets must show it
                kind, runs = needs.parts(need, tw)
                low = chunk.lower()
                said = [w for w in kind if needs.has(low, w)]
                if len(said) >= 2 or said and any(all(needs.has(low, w) for w in r) for r in runs):
                    bad = [n for n in sorted(who) if n not in paired.get(need, [])]
                    if bad:
                        yield f'the need "{need}" is linked to asset {bad[0]}, whose sources do not show it'
            for w in dict.fromkeys(t for t in index.tokenize(chunk) if len(t) >= 5 and t.isalpha()):
                if w in names or w in _GLUE or w in needs.FILLER:
                    continue
                need = kinds.get(w) or kinds.get(needs.base(w))
                if need:   # a need's own word: only for the assets paired with that need, or that show the word
                    bad = [n for n in who if n not in paired.get(need, []) and not needs.has(texts.get(n, ""), w)]
                    if bad:
                        yield f'"{w}" (the need "{need}") is linked to asset {bad[0]}, whose sources do not show it'
                    continue
                if framing and needs.has(own, w):    # the company's own words, framing the sentence
                    continue
                bad = [n for n in who if not _supported(w, texts.get(n, ""))]
                if bad:
                    yield f'"{w}" is said about asset {bad[0]}, but its sources do not contain it'


_ABBR = re.compile(r"(?:\b(?:prof|dr|med|phil|nat|habil|pd|em|dipl|ing|sc|st|mr|ms|mrs|nr|no|vol|ca|bzw|etc|"
                   r"e\.g|i\.e|z\.b|d\.h|u\.a|ph\.d)|\b[A-Z])\.$", re.I)


def _sentences(text: str) -> list[str]:
    """Sentences, not broken after titles and abbreviations ("Prof. Dr. med. A. Muster")."""
    out: list[str] = []
    for piece in re.split(r"(?<=[.!?])\s+", text):
        if out and _ABBR.search(out[-1]):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def _mark_all(text: str, sources: list[OfferSource]) -> str:
    """[n] after EVERY mention of each asset (the paragraph cites only the first), so that what is said after a
    later mention ("…, while the Medical Sensing Laboratory provides …") is checked against that asset."""
    text = re.sub(r"\s*\[\d+\]", "", text)
    zones = _zones(text, sources)
    spots: list[tuple[int, int, int]] = []
    for x in sorted(sources, key=lambda s: -len(s.name)):
        for k in _cite_keys(x):
            for m in re.finditer(rf"(?<![\w-]){re.escape(k)}(?![\w-])", text, _key_flags(k)):
                if not any(a <= m.start() < b or a < m.end() <= b for a, b, _ in spots) and \
                        not any(a <= m.start() and m.end() <= b and n.lower() != x.name.lower() for a, b, n in zones):
                    spots.append((m.start(), m.end(), x.n))
    for a, b, n in sorted(spots, key=lambda z: -z[1]):
        text = f"{text[:b]} [{n}]{text[b:]}"
    return text


class _Para(BaseModel):
    paragraph: str


_NOT_FOUND = {"en": "Not shown on the public pages of a Bern partner: {xs}.",
              "de": "Auf den öffentlichen Seiten keines Berner Partners belegt: {xs}.",
              "fr": "Non attesté sur les pages publiques d'un partenaire bernois : {xs}."}


def _need_lines(case: Case, sources: list[OfferSource], paired: dict[str, list[int]], lang: str) -> str:
    """The needs no asset shows, said plainly instead of being attached to someone."""
    open_ = [n for n, ns in paired.items() if not ns]
    return _NOT_FOUND.get(lang, _NOT_FOUND["en"]).format(xs="; ".join(open_)) if open_ else ""


def _discursive(case: Case, sources: list[OfferSource], lang: str, texts: dict[int, str],
                paired: dict[str, list[int]]) -> str | None:
    """Apertus writes the paragraph from the listed facts only; accepted only if the citations (`_check`) and
    every claim (`_faithful`) hold. One retry with the problem found; else None (the template is used)."""
    language = {"de": "German", "fr": "French"}.get(lang, "English")
    by_n = {s.n: s for s in sources}
    facts = "\n".join(
        f"[{x.n}] {x.kind}: {x.name}"
        + "".join(f"; {k}: {v}" for k, v in [("function", x.role), ("unit", x.unit), ("institution", x.institution),
                                               ("expertise", ", ".join(x.expertise[:3])), ("about", x.about[:200])] if v)
        + "".join(f"; shows the company need: {need}" for need, ns in paired.items() if x.n in ns)
        for x in sources)
    msgs = [
        {"role": "system", "content": (
            "You write for the business-development team of the Canton of Bern. Write natural, flowing prose that a "
            "non-specialist reads easily, in a sober, factual tone. Use ONLY the facts listed for each numbered asset. "
            "Do not add facts, do not promise results or benefits, do not say what anyone has agreed to, and do not "
            "say what an asset has done unless its facts say so. Never use the words unique, world-class, leading "
            "expert, renowned, excellent, innovative, comprehensive, robust. JSON only.")},
        {"role": "user", "content": (
            f"Company: {case.company or 'the company'}\nProfile: {case.analysis.summary}\n\nBern assets:\n{facts}\n\n"
            f"Write ONE paragraph of 90-150 words in {language} on what Bern offers this company, not as a list. "
            "Mention ALL assets, each once, by its exact name as listed. Describe each asset in its own clause with "
            "its own facts only; never give two assets one shared description (no \"both\", no \"together\"). "
            "Name a company need ONLY for the assets whose line says \"shows the company need\", and in that "
            "sentence say nothing else about them. Do not mention any other need. Give each person's function "
            "exactly as listed (do not combine it with another unit or institution). "
            "Do NOT write any numbers or citations; they are added afterwards.\n"
            "Style example (other assets): \"For clinical validation, the company could work with Prof. Anna Muster. "
            "Prof. Muster is group head of the Sensing Lab; her expertise covers wearable sensors. Mechanical "
            "Production is a workshop certified to ISO 13485, and the Clinical Research Database supports study "
            "data management.\"\n"
            'Return {"paragraph": "..."}.')},
    ]
    for _ in range(2):
        try:
            r: _Para = llm.chat_json(msgs, _Para, mode="none", max_tokens=450)  # type: ignore[assignment]
        except llm.LLMError:
            return None
        text = _cite(_clean(r.paragraph), sources, lang)
        if not text or not _check(text, sources):
            problem = "Mention every asset once by its exact name, without superlatives, in at most 150 words."
        else:
            problem = _faithful(text, sources, case, texts, paired)
            if not problem:
                return text
        msgs += [{"role": "assistant", "content": json.dumps({"paragraph": r.paragraph}, ensure_ascii=False)},
                 {"role": "user", "content": f"Not accepted: {problem}. Rewrite the paragraph using only the listed "
                                             "facts. Return the JSON only."}]
    return None


def _weak(m: Match) -> bool:
    """The match's own explanation says the evidence does not support it."""
    return m.why.strip().lower().startswith(("weak match", "schwache", "correspondance faible"))


def summarize_offer(case: Case, lang: str = "en") -> Offer:
    """Selects the cited assets as the pitch partners (never one whose explanation says "Weak match"). The
    paragraph is readable prose by Apertus, accepted only when every citation sits right after the asset it
    names and every claim is in that asset's sources; else a template built from the indexed fields. A stated
    need no asset shows is said to be not found, never attached to someone."""
    picked = pick_assets([m for m in case.matches if not _weak(m)])
    if not picked:
        return Offer(text=case.no_match_message or "", lang=lang)
    for m in case.matches:
        m.selected = m in picked
    ents = index.load_entities()
    sources = [_source(i, m, ents, lang) for i, m in enumerate(picked, 1)]
    texts = {s.n: " ".join([ents[s.id].search_text() if s.id in ents else "", s.name, s.role, s.unit, s.institute,
                            s.institution, s.about, *s.expertise]).lower() for s in sources}
    paired = {need: [int(n) for n in ns] for need, ns in
              needs.pairs(case.analysis, {str(n): t for n, t in texts.items()}).items()}
    text = _discursive(case, sources, lang, texts, paired) if llm.available() else None
    by = "apertus" if text else "rules"
    text = text or _template(case, picked, lang, paired)
    tail = _need_lines(case, sources, paired, lang)
    return Offer(text=f"{text} {tail}".strip(), sources=sources, lang=lang, generated_by=by)


# ---------------- outreach ---------------------------------------------------
_T = {
    "en": {
        "subject": "Research partners in Bern for {company}",
        "hello": "Dear {name},",
        "intro": "Thank you for your interest in the Canton of Bern. Based on your request{need}, we have identified "
                 "the following research partners here in Bern:",
        "brief": "We have put together a short overview for you — every statement in it is linked to its public source:",
        "gains": "Based on what you shared with us, this is what Bern could concretely improve for {company}:",
        "you": "your company",
        "est": "These figures are our estimates; the overview shows how we calculated each of them.",
        "brief2": "The overview presents the people and places behind each point, with their public sources:",
        "why": "Why Bern",
        "call": "We would be glad to introduce you personally and to set up a short call with the experts. "
                "Would one of these times suit you?",
        "nocall": "We would be glad to introduce you personally. Just reply to this email and we will arrange the next steps.",
        "bye": "Kind regards,",
        "src": "source",
    },
    "de": {
        "subject": "Forschungspartner in Bern für {company}",
        "hello": "Guten Tag {name}",
        "intro": "Vielen Dank für Ihr Interesse am Kanton Bern. Aufgrund Ihrer Anfrage{need} haben wir folgende "
                 "Forschungspartner in Bern gefunden:",
        "brief": "Wir haben für Sie eine kurze Übersicht zusammengestellt — jede Aussage darin ist mit ihrer öffentlichen Quelle verlinkt:",
        "gains": "Aufgrund Ihrer Angaben könnte Bern für {company} konkret Folgendes verbessern:",
        "you": "Ihr Unternehmen",
        "est": "Diese Zahlen sind unsere Schätzungen; die Übersicht zeigt, wie wir jede davon berechnet haben.",
        "brief2": "Die Übersicht stellt die Menschen und Orte hinter jedem Punkt vor, mit ihren öffentlichen Quellen:",
        "why": "Warum Bern",
        "call": "Gerne stellen wir Sie persönlich vor und organisieren ein kurzes Gespräch mit den Fachleuten. "
                "Passt Ihnen einer dieser Termine?",
        "nocall": "Gerne stellen wir Sie persönlich vor. Antworten Sie einfach auf diese E-Mail, wir organisieren die nächsten Schritte.",
        "bye": "Freundliche Grüsse",
        "src": "Quelle",
    },
    "fr": {
        "subject": "Partenaires de recherche à Berne pour {company}",
        "hello": "Bonjour {name},",
        "intro": "Merci de votre intérêt pour le canton de Berne. Suite à votre demande{need}, nous avons identifié "
                 "les partenaires de recherche suivants à Berne :",
        "brief": "Nous avons préparé pour vous un bref aperçu — chaque affirmation y est liée à sa source publique :",
        "gains": "D'après ce que vous nous avez transmis, voici ce que Berne pourrait concrètement améliorer pour {company} :",
        "you": "votre entreprise",
        "est": "Ces chiffres sont nos estimations ; l'aperçu montre comment nous avons calculé chacun d'eux.",
        "brief2": "L'aperçu présente les personnes et les lieux derrière chaque point, avec leurs sources publiques :",
        "why": "Pourquoi Berne",
        "call": "Nous serions heureux de vous présenter personnellement et d'organiser un bref appel avec les experts. "
                "L'un de ces créneaux vous conviendrait-il ?",
        "nocall": "Nous serions heureux de vous présenter personnellement. Répondez simplement à cet e-mail et nous organiserons la suite.",
        "bye": "Meilleures salutations,",
        "src": "source",
    },
}


def draft_email(case: Case, lang: str, slots: list[str], sender: str, team: str, link: str = "") -> dict:
    """Deterministic template: only the selected partners and verified proof points, each with its link.
    With a published executive brief the email stays short and points to it."""
    t = _T.get(lang, _T["en"])
    data = (case.outreach.get("brief") or {}).get("data") or {}
    gains = [n["mail"] for n in data.get("needs", []) if n.get("mail")]
    if link and gains:
        # the improvements Bern could bring, in prose; the overview carries the partners, sources and calculations.
        # Companies the officer added from the Knowledge Base are named too: no need sentence mentions them.
        kb = [i for i in data.get("items", []) if i.get("basis") == "knowledge_base"]
        lines = [t["hello"].format(name=case.contact_name or case.company), "",
                 t["gains"].format(company=guess_company(case) or t["you"]), " ".join(gains), "",
                 *[x for i in kb for x in ("• " + i["name"], "  " + i.get("benefit", ""))], *([""] if kb else []),
                 t["est"], "", t["brief2"], link, "", t["call"] if slots else t["nocall"]]
        lines += [f"  – {s}" for s in slots]
        lines += ["", t["bye"], sender or "", team or ""]
        return {"subject": t["subject"].format(company=case.company), "body": "\n".join(lines).strip() + "\n",
                "to": case.contact_email, "matches": [m.id for m in case.matches if m.selected]}
    published = (case.outreach.get("brief") or {}).get("data")
    if published:   # a published pitch without needs: its partners and benefits
        # The email summarizes the same approved version as the shared page and PDF.
        items = published.get("items", [])
        lines = [t["hello"].format(name=case.contact_name or case.company), "", published.get("hook", ""), ""]
        for item in items[:3]:
            lines += ["• " + item["name"], "  " + item.get("benefit", "")]
            if not link:
                lines.append("  " + item.get("page", ""))
        if link:
            lines += ["", t["brief"], link]
        lines += ["", t["call"] if slots else t["nocall"], *["  – " + s for s in slots], "", t["bye"], sender or "", team or ""]
        return {"subject": t["subject"].format(company=case.company), "body": "\n".join(lines).strip() + "\n",
                "to": case.contact_email, "matches": [item["id"] for item in items]}
    if link:
        approved = [m for m in case.matches if m.selected]
        lines = [t["hello"].format(name=case.contact_name or case.company), "", t["intro"].format(need=""), ""]
        lines += [f"• {m.name}{' – ' + m.unit if m.unit else ''} ({m.institution})" for m in approved]
        lines += ["", t["brief"], link, "", t["call"] if slots else t["nocall"]]
        lines += [f"  – {s}" for s in slots]
        lines += ["", t["bye"], sender or "", team or ""]
        return {"subject": t["subject"].format(company=case.company), "body": "\n".join(lines).strip() + "\n",
                "to": case.contact_email, "matches": [m.id for m in approved]}
    approved = [m for m in case.matches if m.selected]
    lines = [t["hello"].format(name=case.contact_name or case.company), "", t["intro"].format(need=""), ""]
    for m in approved:
        who = ", ".join(x for x in [m.role, m.unit] if x)
        lines.append(f"• {m.name}{' – ' + who if who else ''} ({m.institution})")
        if m.plain:
            lines.append(f"  {m.plain}")
        lines.append(f"  {m.url}")
    hl = showcase.build().get("highlights", [])[:2]
    if hl:
        lines += ["", f"{t['why']}:"]
        for h in hl:
            lines.append(f"• “{h['quote'].strip()}” ({t['src']}: {h['url']})")
    lines += ["", t["call"] if slots else t["nocall"]]
    lines += [f"  – {s}" for s in slots]
    lines += ["", t["bye"], sender or "", team or ""]
    return {"subject": t["subject"].format(company=case.company), "body": "\n".join(lines).strip() + "\n",
            "to": case.contact_email, "matches": [m.id for m in approved]}


def ics(case: Case, start_iso: str, minutes: int, organizer: str, organizer_email: str) -> str:
    start = datetime.fromisoformat(start_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone(timedelta(hours=2)))  # assume Swiss local time if not given
    start = start.astimezone(timezone.utc)
    end = start + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%SZ"
    experts = ", ".join(m.name for m in case.matches if m.selected)
    desc = (f"Introduction call: {case.company} and research partners in Bern ({experts}). "
            f"Prepared with the Bern Expertise Navigator.").replace("\n", " ")
    attendees = [a for a in [case.contact_email, organizer_email] if a]
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bern Expertise Navigator//EN", "METHOD:REQUEST", "BEGIN:VEVENT",
        f"UID:{case.id}-{start.strftime(fmt)}@expertise-navigator", f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{case.company} × Bern research partners",
        f"DESCRIPTION:{desc}",
        *(f"ORGANIZER;CN={organizer}:mailto:{organizer_email}" for _ in [0] if organizer_email),
        *(f"ATTENDEE;RSVP=TRUE:mailto:{a}" for a in attendees),
        "END:VEVENT", "END:VCALENDAR", ""])
