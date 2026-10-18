"""Stage 6 — academic papers of the indexed people (OpenAlex), open-access full text, embedding-derived graph.

    collect  people -> OpenAlex author candidates (Bern-affiliated) -> author match (LLM with whitelist,
             conservative rules if the LLM is down) -> recent works + works linked on their pages
             (paper_ref) -> OA PDFs (data/papers/pdf/) and their text (data/papers/text/) -> JSONL
    embed    abstract + full-text chunks -> pgvector (Postgres only)
    link     kNN SIMILAR_TO (Person<->Person, Paper<->Paper), paper topics -> ABOUT existing Topics (LLM
             with whitelist), CITES between known papers, projected into the AGE graph (Postgres only)

Decision tables are explicit below (ENTITY_PAGE_LINK, fallback matcher). No alias dictionaries: the LLM
always chooses among ids it was given, and its answer is validated against that list.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
from pydantic import BaseModel

from . import llm
from .config import DATA_DIR, settings
from .extract import name_key
from .openalex_client import OpenAlexClient, OpenAlexError, candidate_summary, parse_work, short_id, strip_doi
from .schema import AuthorMatch, Entity, EntityLink, Page, Work

PAPERS_DIR = DATA_DIR / "papers"
PDF_DIR = PAPERS_DIR / "pdf"
TEXT_DIR = PAPERS_DIR / "text"
WORKS_PATH = PAPERS_DIR / "works.jsonl"
MATCHES_PATH = PAPERS_DIR / "author_matches.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# =============================================================================
# Author disambiguation: LLM-first with a whitelist, conservative rules as fallback
# =============================================================================
class _AuthorChoice(BaseModel):
    choice: str
    reason: str


def person_card(e: Entity) -> dict:
    return {"name": e.name, "role": e.role, "unit": e.unit, "institute": e.institute,
            "institution": e.source_label, "expertise": e.expertise[:8], "description": e.description[:1]}


def _names(c: dict) -> set[str]:
    return {name_key(n) for n in [c.get("display_name", ""), *c.get("alternatives", [])] if n}


def rules_choice(e: Entity, cands: list[dict]) -> tuple[str | None, str]:
    """Deterministic, conservative: identical normalised name AND Bern affiliation AND exactly one such candidate."""
    key = name_key(e.name)
    hits = [c for c in cands if c.get("bern") and key in _names(c)]
    if len(hits) == 1:
        return hits[0]["id"], f"rules: unique Bern-affiliated candidate with identical normalised name '{key}'"
    if not hits:
        return None, f"rules: no Bern-affiliated candidate named exactly '{key}'"
    return None, f"rules: {len(hits)} Bern-affiliated candidates named '{key}' (ambiguous, not chosen)"


def llm_choice(e: Entity, cands: list[dict]) -> tuple[str | None, str]:
    """Raises llm.LLMError when the endpoint fails (the caller then uses the rules)."""
    ids = [c["id"] for c in cands]
    r = llm.chat_json([
        {"role": "system", "content": "You match researchers to bibliographic author profiles. JSON only."},
        {"role": "user", "content": (
            "PERSON (from a public web page of a Bern research institution):\n"
            f"{json.dumps(person_card(e), ensure_ascii=False)}\n\n"
            "OPENALEX AUTHOR CANDIDATES:\n"
            + "\n".join(json.dumps({k: v for k, v in c.items()}, ensure_ascii=False) for c in cands)
            + "\n\nWhich candidate is the same person? Answer `choice` = exactly one candidate id from this list "
              f"{ids}, or \"none\" if no candidate is clearly the same person. The same name alone is not enough "
              "when names are common or several candidates share it: use affiliation, years, research topics and "
              "role. `reason`: one short sentence citing the evidence you used.")},
    ], _AuthorChoice, max_tokens=200, temperature=0.0)
    choice = r.choice.strip()  # type: ignore[attr-defined]
    reason = r.reason.strip()[:500]  # type: ignore[attr-defined]
    if choice.lower() == "none":
        return None, f"llm: none ({reason})"
    if choice not in ids:  # the whitelist is binding: anything else is discarded, never "fixed up"
        return None, f"llm: invalid choice {choice!r} not among candidates, discarded ({reason})"
    return choice, f"llm: {reason}"


# Decision table for entities that already know their OpenAlex author (no search, no LLM):
#   extractor == "openalex" and exactly one OpenAlex author id in source_urls / evidence -> known_id
#   extractor == "openalex" and zero or several ids                                       -> normal matching
#   any other extractor (web pages may link co-authors' profiles)                         -> normal matching
# The id is a fixed OpenAlex pattern (A + digits), the one place where a pattern is the right tool.
_OPENALEX_AUTHOR = re.compile(r"^(?:https?://(?:api\.)?openalex\.org/(?:authors/)?)?(A\d+)/?$", re.IGNORECASE)


def openalex_author_ids(e: Entity) -> list[str]:
    """Distinct OpenAlex author ids carried by the entity (its URLs, evidence URLs and evidence values)."""
    found: list[str] = []
    for s in [*e.source_urls, *(ev.url for ev in e.evidence), *(ev.value for ev in e.evidence)]:
        m = _OPENALEX_AUTHOR.match((s or "").strip())
        if m and m.group(1).upper() not in found:
            found.append(m.group(1).upper())
    return found


def known_author_id(e: Entity) -> tuple[str | None, str]:
    """(author id or None, why) following the decision table above."""
    if e.extractor != "openalex":
        return None, f"extractor {e.extractor}: matched by search"
    ids = openalex_author_ids(e)
    if len(ids) == 1:
        return ids[0], f"known_id: entity extracted from OpenAlex author {ids[0]}"
    return None, (f"extractor openalex but {len(ids)} author ids {ids[:5]}: matched by search" if ids
                  else "extractor openalex without an author id: matched by search")


def choose_author(e: Entity, cands: list[dict], use_llm: bool) -> AuthorMatch:
    base = dict(entity_id=e.id, entity_name=e.name, candidates=cands)
    if not cands:
        return AuthorMatch(**base, decided_by="rules", reason="no Bern-affiliated OpenAlex candidates")
    if use_llm:
        try:
            chosen, reason = llm_choice(e, cands)
            return AuthorMatch(**base, chosen_author_id=chosen, decided_by="llm", reason=reason,
                               model=settings.llm_model)
        except llm.LLMError as ex:
            chosen, reason = rules_choice(e, cands)
            return AuthorMatch(**base, chosen_author_id=chosen, decided_by="rules",
                               reason=f"LLM unavailable ({str(ex)[:120]}); {reason}")
    chosen, reason = rules_choice(e, cands)
    return AuthorMatch(**base, chosen_author_id=chosen, decided_by="rules", reason=reason)


# =============================================================================
# Links from the entity's own pages (paper_ref recorded by the crawler)
# =============================================================================
# Decision table: a paper linked on a page is attributed to an entity only when the page is that entity's own
# page: page_type equals the entity type AND the page is the source of exactly one entity of that type
# (a directory page listing many people attributes nothing).
def page_paper_links(entities: list[Entity], pages: list[Page]) -> dict[str, list[tuple[str, str, str]]]:
    """{entity_id: [(scheme, id, page_url)]}"""
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entities:
        for u in e.source_urls:
            owners[(u, e.entity_type)].append(e.id)
    out: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for p in pages:
        refs = [l.paper_ref for l in p.links if l.kind == "paper" and l.paper_ref]
        if not refs or not p.page_type or p.page_type == "other":
            continue
        own = owners.get((p.url, p.page_type), [])
        if len(own) != 1:
            continue
        for r in refs:
            if (r.scheme, r.id, p.url) not in out[own[0]]:
                out[own[0]].append((r.scheme, r.id, p.url))
    return out


# =============================================================================
# Open-access PDF download (bounded) and text extraction (pypdf)
# =============================================================================
@dataclass
class PdfResult:
    status: str               # ok / robots_disallowed / http_<code> / bad_content_type / not_pdf / too_large / timeout / ...
    path: Path | None = None
    sha1: str | None = None
    bytes: int = 0


_PDF_TYPES = ("application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream")


class PdfFetcher:
    """Downloads only what it is given (OA pdf_urls), within size/time limits, honouring robots.txt per host."""

    def __init__(self, dest: Path = PDF_DIR, *, client: httpx.Client | None = None, user_agent: str | None = None,
                 max_bytes: int | None = None, timeout: float | None = None, delay: float | None = None,
                 sleep=time.sleep):
        from .crawl import _Robots
        ua = user_agent or "HackApertus-ExpertiseNavigator/0.1 (+public research; papers)"
        self.client = client or httpx.Client(headers={"User-Agent": ua}, follow_redirects=True,
                                             timeout=timeout or settings.papers_pdf_timeout)
        self.robots = _Robots(ua, self.client)
        self.dest = dest
        self.max_bytes = max_bytes or int(settings.papers_pdf_max_mb * 1024 * 1024)
        self.timeout = timeout or settings.papers_pdf_timeout
        self.delay = settings.papers_pdf_delay if delay is None else delay
        self.sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _polite(self, host: str) -> None:
        with self._lock:
            wait = self._last.get(host, 0.0) + self.delay - time.monotonic()
            self._last[host] = max(time.monotonic(), self._last.get(host, 0.0) + self.delay)
        if wait > 0:
            self.sleep(wait)

    def fetch(self, url: str) -> PdfResult:
        sha = hashlib.sha1(url.encode()).hexdigest()
        path = self.dest / f"{sha}.pdf"
        if path.exists() and path.stat().st_size:
            return PdfResult("ok", path, sha, path.stat().st_size)
        if not self.robots.ok(url):
            return PdfResult("robots_disallowed")
        self._polite(urlparse(url).hostname or "")
        deadline = time.monotonic() + self.timeout
        try:
            with self.client.stream("GET", url, timeout=self.timeout) as r:
                if str(r.url) != url and not self.robots.ok(str(r.url)):
                    return PdfResult("robots_disallowed")
                if r.status_code != 200:
                    return PdfResult(f"http_{r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in _PDF_TYPES:
                    return PdfResult("bad_content_type")
                if int(r.headers.get("content-length") or 0) > self.max_bytes:
                    return PdfResult("too_large")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > self.max_bytes:
                        return PdfResult("too_large")
                    if time.monotonic() > deadline:
                        return PdfResult("timeout")
        except httpx.TimeoutException:
            return PdfResult("timeout")
        except httpx.HTTPError as e:
            return PdfResult(f"transport_{type(e).__name__}")
        if not bytes(buf[:1024]).lstrip().startswith(b"%PDF-"):
            return PdfResult("not_pdf")
        self.dest.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(bytes(buf))
        tmp.replace(path)
        return PdfResult("ok", path, sha, len(buf))


def pdf_text(path: Path, max_pages: int | None = None) -> str:
    """Plain text of the first `max_pages` pages (pypdf: pure Python, BSD licence). Raises on unreadable PDFs."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = reader.pages[: max_pages or settings.papers_pdf_max_pages]
    text = "\n".join((p.extract_text() or "") for p in pages)
    text = re.sub(r"-\n(?=[a-z])", "", text)        # re-join words hyphenated at line ends
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


# =============================================================================
# Chunking for embeddings
# =============================================================================
def chunk_words(text: str, size: int | None = None, overlap: int | None = None,
                max_chunks: int | None = None) -> list[str]:
    """Word windows of `size` words with `overlap` words. Measured on a real OA paper with the e5 tokenizer:
    200 words -> median 357 tokens (p90 567: tables and numbers tokenise densely; e5 truncates at 512).
    Only the first `max_chunks` windows are kept: introduction/methods, and the references at the end of long
    papers are left out."""
    size = size or settings.papers_chunk_words
    overlap = settings.papers_chunk_overlap if overlap is None else overlap
    max_chunks = max_chunks or settings.papers_max_chunks
    if overlap >= size:
        raise ValueError("chunk overlap must be smaller than the chunk size")
    words = text.split()
    out: list[str] = []
    step = size - overlap
    for start in range(0, len(words), step):
        win = words[start:start + size]
        if not win or (out and len(win) <= overlap):
            break
        out.append(" ".join(win))
        if len(out) >= max_chunks or start + size >= len(words):
            break
    return out


def paper_chunks(w: Work, text_dir: Path = TEXT_DIR) -> list[tuple[str, int, str]]:
    """[(kind, chunk_no, text)]: the abstract (title + abstract) and the full-text windows."""
    out: list[tuple[str, int, str]] = []
    if w.abstract or w.title:
        out.append(("abstract", 0, f"{w.title}. {w.abstract or ''}".strip()))
    if w.pdf_sha1 and (text_dir / f"{w.pdf_sha1}.txt").exists():
        full = (text_dir / f"{w.pdf_sha1}.txt").read_text(encoding="utf-8")
        out += [("fulltext", i, c) for i, c in enumerate(chunk_words(full))]
    return out


# =============================================================================
# Collection
# =============================================================================
@dataclass
class CollectResult:
    works: dict[str, Work]
    matches: list[AuthorMatch]
    stats: dict = field(default_factory=dict)


# =============================================================================
# Duplicate OpenAlex records of one DOI
# =============================================================================
# OpenAlex sometimes keeps two work records (two W ids) for the same DOI; nav.paper.doi is UNIQUE and the
# graph wants one Paper per publication. Decision rule for the canonical record of a DOI, first criterion wins:
#   1. more authorships            (the richer record carries the author links)
#   2. has an abstract             (embeddable text)
#   3. full text already extracted (fulltext_status == "ok": no second download)
#   4. has an OA pdf_url
#   5. lowest numeric OpenAlex id  (tie-break, deterministic: the older record)
# cited_by_count is deliberately not a criterion: it moves between runs and would flip the choice.
# Everything that refers to a dropped id is moved to the canonical one: entity links (authorships and
# page links), entity ids on authorships, referenced_works of every work (CITES), and the full-text fields
# (the chunks/text files are keyed by the work and its pdf_sha1). Topics stay those of the canonical record
# (the dropped record's only when the canonical one has none).
def doi_key(doi: str | None) -> str | None:
    return strip_doi(doi)


def _canonical_order(w: Work) -> tuple:
    return (-len(w.authors), not w.abstract, w.fulltext_status != "ok", not w.pdf_urls,
            int(w.id[1:]) if w.id[1:].isdigit() else float("inf"), w.id)


def rename_works(works, alias: dict[str, str]) -> list[Work]:
    """Copies of `works` with ids and referenced_works mapped through `alias` (old id -> new id);
    a reference to the work itself or a repeated one is dropped."""
    out = []
    for w in works:
        new_id = alias.get(w.id, w.id)
        refs = [r for r in dict.fromkeys(alias.get(r, r) for r in w.referenced_works) if r != new_id]
        out.append(w.model_copy(deep=True, update={"id": new_id, "referenced_works": refs}))
    return out


def _absorb(keep: Work, drop: Work) -> None:
    for l in drop.links:
        if any(x.entity_id == l.entity_id and x.relation == l.relation for x in keep.links):
            continue
        if l.relation == "author":  # position is an index into the canonical authorships
            pos = next((a.position for a in keep.authors if l.author_id and a.author_id == l.author_id), None)
            l = l.model_copy(update={"position": pos})
        keep.links.append(l)
    matched = {a.author_id: a.entity_id for a in drop.authors if a.author_id and a.entity_id}
    for a in keep.authors:
        if not a.entity_id and a.author_id in matched:
            a.entity_id = matched[a.author_id]
    keep.referenced_works = list(dict.fromkeys([*keep.referenced_works, *drop.referenced_works]))
    for f in ("abstract", "venue", "year", "landing_url", "pmid", "pmcid"):
        if not getattr(keep, f) and getattr(drop, f):
            setattr(keep, f, getattr(drop, f))
    if not keep.topics:
        keep.topics = drop.topics
    if not keep.is_oa and drop.is_oa:
        keep.is_oa, keep.oa_status = True, drop.oa_status
    if not keep.pdf_urls:
        keep.pdf_urls = drop.pdf_urls
    if keep.fulltext_status != "ok" and drop.fulltext_status == "ok":
        keep.pdf_url, keep.pdf_sha1 = drop.pdf_url, drop.pdf_sha1
        keep.fulltext_chars, keep.fulltext_status = drop.fulltext_chars, drop.fulltext_status
    keep.cited_by_count = max(keep.cited_by_count, drop.cited_by_count)


def dedupe_by_doi(works) -> tuple[dict[str, Work], dict[str, str]]:
    """One work per normalised DOI (rule above). Returns (works by id, {dropped id: canonical id}).
    Pure: the input works are not modified; works without a DOI pass through unchanged."""
    groups: dict[str, list[Work]] = defaultdict(list)
    for w in works:
        if doi_key(w.doi):
            groups[doi_key(w.doi)].append(w)
    alias: dict[str, str] = {}
    for ws in groups.values():
        if len({w.id for w in ws}) > 1:
            keep = min(ws, key=_canonical_order)
            alias.update({w.id: keep.id for w in ws if w.id != keep.id})
    if not alias:
        return {w.id: w for w in works}, {}
    copies = rename_works(works, {})  # deep copies
    kept: dict[str, Work] = {w.id: w for w in copies if w.id not in alias}
    for w in sorted((w for w in copies if w.id in alias), key=_canonical_order):
        _absorb(kept[alias[w.id]], w)
    return {w.id: w for w in rename_works(kept.values(), alias)}, alias


def _log_duplicates(step: str, alias: dict[str, str]) -> None:
    if alias:
        print(f"[papers] {step}: merged {len(alias)} duplicate OpenAlex work(s) sharing a DOI: "
              + ", ".join(f"{d}->{k}" for d, k in sorted(alias.items())))


def resolve_bern(client: OpenAlexClient, rors: list[str]) -> list[dict]:
    """ROR ids -> OpenAlex institutions. A ROR that does not resolve is reported, never silently dropped."""
    found = client.institutions_by_ror(rors)
    got = {(i.get("ror") or "").lower() for i in found}
    missing = [r for r in rors if r.lower() not in got]
    if missing:
        print(f"[papers] WARNING: ROR ids not found in OpenAlex: {missing}")
    if not found:
        raise OpenAlexError("no_institutions", f"none of {rors} resolves to an OpenAlex institution")
    return found


def _since_year() -> int:
    return datetime.now(timezone.utc).year - settings.papers_years


PEOPLE_FILTERS = ("all", "known", "search")


def select_people(entities: list[Entity], types: tuple[str, ...], limit: int = 0,
                  skip_ids: set[str] | frozenset[str] = frozenset(), people_filter: str = "all") -> list[Entity]:
    """The people this run processes: the given types, minus those already decided, narrowed by `people_filter`
    (all | known = OpenAlex author id already known | search = needs an author search), then at most `limit`
    (the filter comes first, so `known` + limit N yields N known-id people wherever they sit in the list)."""
    if people_filter not in PEOPLE_FILTERS:
        raise ValueError(f"people_filter {people_filter!r} not in {PEOPLE_FILTERS}")
    people = [e for e in entities if e.entity_type in types and e.id not in skip_ids]
    if people_filter != "all":
        people = [e for e in people if bool(known_author_id(e)[0]) == (people_filter == "known")]
    return people[:limit] if limit else people


def decided_ids(matches: list[AuthorMatch]) -> set[str]:
    """People a previous run already decided. A rules decision taken only because the LLM was down is not final:
    it is retried on the next run."""
    return {m.entity_id for m in matches if not m.reason.startswith("LLM unavailable")}


OPENALEX_SEARCH_USD, OPENALEX_LIST_USD = 0.001, 0.0001


def estimate(entities: list[Entity], pages: list[Page], *, types: tuple[str, ...] = ("person",), limit: int = 0,
             skip_ids: set[str] | frozenset[str] = frozenset(), previous_works: dict[str, Work] | None = None,
             use_llm: bool = True, pdf: bool = True, max_pdfs: int = 0, people_filter: str = "all") -> dict:
    """What `papers collect` (then embed/link) would do, without any network call: upper bounds of OpenAlex
    requests, LLM calls, PDF downloads and chunks, computed from the same selection and settings the run uses.
    The OpenAlex disk cache (OPENALEX_CACHE_DAYS) can only lower the request count."""
    people = select_people(entities, types, limit, skip_ids, people_filter)
    known = [e for e in people if known_author_id(e)[0]]
    search = len(people) - len(known)
    refs = page_paper_links(entities, pages)
    by_scheme: dict[str, set[str]] = defaultdict(set)
    for rs in refs.values():
        for scheme, rid, _ in rs:
            by_scheme[scheme].add(rid)

    def batched(ids: set[str]) -> int:
        safe = [i for i in ids if "|" not in i and "," not in i]
        return -(-len(safe) // 50) + (len(ids) - len(safe))

    page_calls = batched(by_scheme.get("doi", set())) + batched(by_scheme.get("pubmed", set()))
    page_works = len(by_scheme.get("doi", set())) + len(by_scheme.get("pubmed", set()))
    works_max = len(people) * settings.papers_max_works + page_works
    prev = previous_works or {}
    reused_pdf = sum(1 for w in prev.values() if not _retry_fulltext(w.fulltext_status))
    pdf_max = 0 if not (pdf and settings.papers_pdf) else (min(max_pdfs, works_max) if max_pdfs else works_max)
    oa_calls = 1 + search + len(people) + page_calls
    return {
        "people": {"selected": len(people), "known_openalex_id": len(known), "to_search": search,
                   "already_decided_skipped": sum(1 for e in entities if e.entity_type in types and e.id in skip_ids),
                   "types": list(types), "limit": limit, "filter": people_filter},
        "openalex_requests_max": {"total": oa_calls, "institutions": 1, "author_search": search,
                                  "works_by_author": len(people), "page_linked_batches": page_calls,
                                  "seconds_at_rps_min": round(oa_calls / max(settings.openalex_rps, 0.01), 1),
                                  # OpenAlex list prices (README): author search $0.001, list/filter call $0.0001
                                  "cost_usd_max": round(search * OPENALEX_SEARCH_USD
                                                        + (oa_calls - search) * OPENALEX_LIST_USD, 4)},
        "llm_calls_max": {"author_match": search if use_llm else 0,
                          "topic_labels": (3 * (works_max + len(prev))) if use_llm else 0,
                          "note": "author_match only for people with candidates; topics are decided once per "
                                  "OpenAlex topic (cached in nav.topic_map), so the real count is far lower"},
        "works_max": works_max, "page_linked_refs": {k: len(v) for k, v in by_scheme.items()},
        "pdf_downloads_max": pdf_max, "pdf_kept_from_previous_runs": reused_pdf,
        "chunks_max": {"abstract": works_max, "fulltext": pdf_max * settings.papers_max_chunks,
                       "total": works_max + pdf_max * settings.papers_max_chunks},
        "settings": {"PAPERS_MAX_WORKS": settings.papers_max_works, "PAPERS_YEARS": settings.papers_years,
                     "PAPERS_MAX_CANDIDATES": settings.papers_max_candidates,
                     "PAPERS_MAX_CHUNKS": settings.papers_max_chunks, "PAPERS_PDF": settings.papers_pdf,
                     "OPENALEX_RPS": settings.openalex_rps, "max_pdfs": max_pdfs},
    }


def collect(entities: list[Entity], pages: list[Page], client: OpenAlexClient, *,
            fetcher: PdfFetcher | None = None, use_llm: bool | None = None, types: tuple[str, ...] = ("person",),
            limit: int = 0, max_pdfs: int = 0, workers: int = 4, text_dir: Path = TEXT_DIR,
            skip_ids: set[str] | frozenset[str] = frozenset(), previous_works: dict[str, Work] | None = None,
            previous_matches: list[AuthorMatch] | None = None, people_filter: str = "all") -> CollectResult:
    """People -> author match -> works (+ page-linked works) -> OA PDFs. Never raises for one person.

    Resume: `skip_ids` (people already decided) are not searched again; `previous_matches` still map their
    authors to co-authorship links; `previous_works` keep their full-text outcome (no second download)."""
    if use_llm is None:
        use_llm = llm.available()
    insts = resolve_bern(client, list(settings.papers_rors))
    bern_ids = {short_id(i["id"]) for i in insts}
    people = select_people(entities, types, limit, skip_ids, people_filter)
    stats: dict = {"institutions": [{"id": short_id(i["id"]), "ror": i.get("ror"), "name": i.get("display_name")}
                                    for i in insts], "people": len(people),
                   "skipped_done": sum(1 for e in entities if e.entity_type in types and e.id in skip_ids),
                   "candidates": 0,
                   "matched": 0, "decided_by": defaultdict(int), "errors": 0}
    raw_works: dict[str, dict] = {}
    entity_works: dict[str, list[tuple[str, EntityLink]]] = defaultdict(list)
    matches: list[AuthorMatch] = []
    lock = threading.Lock()

    def one(e: Entity):
        try:
            known, why = known_author_id(e)
            if known:
                cands: list[dict] = []
                m = AuthorMatch(entity_id=e.id, entity_name=e.name, candidates=[], chosen_author_id=known,
                                decided_by="known_id", reason=why)
            else:
                raw = client.search_authors(name_key(e.name), sorted(bern_ids),
                                            per_page=settings.papers_max_candidates)
                cands = [candidate_summary(a, bern_ids) for a in raw]
                cands = [c for c in cands if c["id"]][: settings.papers_max_candidates]
                m = choose_author(e, cands, use_llm)
            works = client.works_by_author(m.chosen_author_id, since_year=_since_year(),
                                           limit=settings.papers_max_works) if m.chosen_author_id else []
        except OpenAlexError as ex:
            with lock:
                stats["errors"] += 1
            print(f"  ! {e.name}: {ex}")
            return
        with lock:
            matches.append(m)
            stats["candidates"] += len(cands)
            stats["decided_by"][m.decided_by] += 1
            if m.chosen_author_id:
                stats["matched"] += 1
            for w in works:
                wid = short_id(w["id"])
                raw_works.setdefault(wid, w)
                entity_works[e.id].append((wid, EntityLink(entity_id=e.id, relation="author",
                                                           author_id=m.chosen_author_id)))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, people))

    # works linked on the entities' own pages (DOI / PubMed), any entity type
    links = page_paper_links(entities, pages)
    by_scheme: dict[str, set[str]] = defaultdict(set)
    for refs in links.values():
        for scheme, rid, _ in refs:
            by_scheme[scheme].add(rid)
    resolved: dict[tuple[str, str], str] = {}
    unsupported = 0
    for scheme, field_name in (("doi", "doi"), ("pubmed", "pmid")):
        ids = sorted(by_scheme.get(scheme, ()))
        safe = [i for i in ids if "|" not in i and "," not in i]  # the filter syntax cannot carry these
        try:
            got = client.works_by_ids(field_name, safe)
        except OpenAlexError as ex:
            print(f"  ! page-linked {scheme}: {ex}")
            stats["errors"] += 1
            got = []
        for w in got:
            pw = parse_work(w, _now())
            key = pw.doi if scheme == "doi" else pw.pmid
            if key:
                resolved[(scheme, key.lower())] = pw.id
                raw_works.setdefault(pw.id, w)
        for i in ids:
            if i not in safe:
                try:
                    w = client.work(f"doi:{i}" if scheme == "doi" else f"pmid:{i}")
                    resolved[(scheme, i)] = short_id(w["id"])
                    raw_works.setdefault(short_id(w["id"]), w)
                except OpenAlexError:
                    pass
    for scheme, s in by_scheme.items():
        if scheme not in ("doi", "pubmed"):
            unsupported += len(s)
    n_page = 0
    for eid, refs in links.items():
        for scheme, rid, url in refs:
            wid = resolved.get((scheme, rid.lower()))
            if wid:
                n_page += 1
                entity_works[eid].append((wid, EntityLink(entity_id=eid, relation="page_link", page_url=url)))
    stats["page_links"] = {"refs": sum(len(v) for v in links.values()), "resolved": n_page,
                           "unsupported_scheme": unsupported}

    # assemble works: authorship positions and the person each matched author stands for
    fetched = _now()
    works: dict[str, Work] = {wid: parse_work(raw, fetched) for wid, raw in raw_works.items()}
    author_entity = {m.chosen_author_id: m.entity_id for m in [*(previous_matches or []), *matches]
                     if m.chosen_author_id}
    for eid, items in entity_works.items():
        for wid, link in items:
            w = works[wid]
            if link.relation == "author":
                pos = next((a.position for a in w.authors if a.author_id == link.author_id), None)
                link = link.model_copy(update={"position": pos})
            if not any(l.entity_id == eid and l.relation == link.relation for l in w.links):
                w.links.append(link)
    # co-authors matched to other people: one link each, from the authorship list
    link_coauthors(works.values(), author_entity)
    # one work per DOI before any download, embedding or graph step (rule at dedupe_by_doi)
    works, alias = dedupe_by_doi(works.values())
    _log_duplicates("collect", alias)
    stats["works_duplicate_doi_merged"] = len(alias)
    stats["works"] = len(works)
    stats["oa_works"] = sum(w.is_oa for w in works.values())
    stats["oa_with_pdf_url"] = sum(bool(w.pdf_urls) for w in works.values())
    if fetcher is not None and settings.papers_pdf:
        stats["pdf"] = fetch_fulltexts(list(works.values()), fetcher, max_pdfs=max_pdfs, text_dir=text_dir,
                                       previous=previous_works)
    else:
        for w in works.values():
            w.fulltext_status = w.fulltext_status or ("pdf_disabled" if w.pdf_urls else
                                                      "not_oa" if not w.is_oa else "no_pdf_url")
    stats["decided_by"] = dict(stats["decided_by"])
    stats["openalex"] = dict(client.usage)
    stats["llm_usage"] = dict(llm.usage)
    return CollectResult(works=works, matches=matches, stats=stats)


def link_coauthors(works, author_entity: dict[str, str]) -> None:
    """Authorships whose OpenAlex author is matched to a person: set entity_id and add one author link each."""
    for w in works:
        for a in w.authors:
            if a.author_id in author_entity:
                a.entity_id = author_entity[a.author_id]
            if a.entity_id and not any(l.entity_id == a.entity_id and l.relation == "author" for l in w.links):
                w.links.append(EntityLink(entity_id=a.entity_id, relation="author", position=a.position,
                                          author_id=a.author_id))


# Full-text outcomes worth trying again on a later run; every other outcome of a previous run is kept as is.
def _retry_fulltext(status: str | None) -> bool:
    return (not status or status in ("skipped_limit", "pdf_disabled", "timeout")
            or status.startswith(("transport_", "http_5", "http_429", "extract_failed")))


def fetch_fulltexts(works: list[Work], fetcher: PdfFetcher, *, max_pdfs: int = 0,
                    text_dir: Path = TEXT_DIR, previous: dict[str, Work] | None = None) -> dict:
    """Only OA works with an OA pdf_url are ever fetched; the first URL that yields a readable PDF wins.
    A work whose previous outcome is final (ok, not_oa, robots_disallowed, http_404, ...) is not fetched again."""
    counts: dict[str, int] = defaultdict(int)
    tried = 0
    for w in sorted(works, key=lambda x: (-(x.year or 0), x.id)):
        old = (previous or {}).get(w.id)
        if old is not None and not _retry_fulltext(old.fulltext_status) and \
                (old.fulltext_status != "ok" or (old.pdf_sha1 and (text_dir / f"{old.pdf_sha1}.txt").exists())):
            w.pdf_url, w.pdf_sha1 = old.pdf_url, old.pdf_sha1
            w.fulltext_chars, w.fulltext_status = old.fulltext_chars, old.fulltext_status
            counts["kept_" + (w.fulltext_status or "none")] += 1
            continue
        if not w.is_oa:
            w.fulltext_status = "not_oa"
        elif not w.pdf_urls:
            w.fulltext_status = "no_pdf_url"
        elif max_pdfs and tried >= max_pdfs:
            w.fulltext_status = "skipped_limit"
        else:
            tried += 1
            for url in w.pdf_urls[:2]:
                res = fetcher.fetch(url)
                w.fulltext_status = res.status
                if res.status != "ok":
                    continue
                try:
                    txt_path = text_dir / f"{res.sha1}.txt"
                    if not txt_path.exists():
                        text = pdf_text(res.path)
                        text_dir.mkdir(parents=True, exist_ok=True)
                        txt_path.write_text(text, encoding="utf-8")
                    w.pdf_url, w.pdf_sha1 = url, res.sha1
                    w.fulltext_chars = len(txt_path.read_text(encoding="utf-8"))
                    w.fulltext_status = "ok" if w.fulltext_chars else "empty_text"
                except Exception as ex:  # malformed PDFs are common; keep going
                    w.fulltext_status = f"extract_failed:{type(ex).__name__}"
                break
        counts[w.fulltext_status] += 1
    return dict(counts)


def save_jsonl(res: CollectResult, works_path: Path = WORKS_PATH, matches_path: Path = MATCHES_PATH) -> None:
    works_path.parent.mkdir(parents=True, exist_ok=True)
    with works_path.open("w", encoding="utf-8") as fh:
        for w in sorted(res.works.values(), key=lambda x: x.id):
            fh.write(w.model_dump_json() + "\n")
    with matches_path.open("w", encoding="utf-8") as fh:
        for m in sorted(res.matches, key=lambda x: x.entity_id):
            fh.write(m.model_dump_json() + "\n")


def merge_results(prev_works: list[Work], prev_matches: list[AuthorMatch], res: CollectResult) -> CollectResult:
    """Previous JSONL + this run = the new JSONL. Works are keyed by id (this run's metadata wins, entity links
    are united), matches by entity (this run's decision wins), so running again never duplicates anything."""
    works: dict[str, Work] = {w.id: w.model_copy(deep=True) for w in prev_works}
    for wid, w in res.works.items():
        old = works.get(wid)
        w = w.model_copy(deep=True)
        if old is not None:
            for l in old.links:
                if not any(x.entity_id == l.entity_id and x.relation == l.relation for x in w.links):
                    w.links.append(l)
        works[wid] = w
    by_entity = {m.entity_id: m for m in prev_matches}
    by_entity.update({m.entity_id: m for m in res.matches})
    matches = list(by_entity.values())
    # a previous JSONL may hold the other record of a DOI (or both): one work per DOI again
    works, alias = dedupe_by_doi(works.values())
    _log_duplicates("merge", alias)
    link_coauthors(works.values(), {m.chosen_author_id: m.entity_id for m in matches if m.chosen_author_id})
    return CollectResult(works=works, matches=matches,
                         stats={**res.stats, "total_works_duplicate_doi_merged": len(alias)})


def load_jsonl(works_path: Path = WORKS_PATH, matches_path: Path = MATCHES_PATH) -> tuple[list[Work], list[AuthorMatch]]:
    works = [Work.model_validate_json(l) for l in works_path.open(encoding="utf-8") if l.strip()] \
        if works_path.exists() else []
    matches = [AuthorMatch.model_validate_json(l) for l in matches_path.open(encoding="utf-8") if l.strip()] \
        if matches_path.exists() else []
    return works, matches


# =============================================================================
# Embedding-derived edges: threshold calibration and degree-capped selection (pure)
# =============================================================================
def calibrate_threshold(scores: list[float], quantile: float | None = None, floor: float | None = None) -> float:
    """Threshold = the `quantile` of the kNN cosine distribution, never below `floor`."""
    quantile = settings.similar_quantile if quantile is None else quantile
    floor = settings.similar_min if floor is None else floor
    if not scores:
        return floor
    return max(floor, float(np.quantile(np.asarray(scores, dtype=np.float64), quantile)))


def distribution(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0}
    a = np.asarray(scores, dtype=np.float64)
    return {"n": int(a.size), "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
            **{f"p{q}": round(float(np.quantile(a, q / 100)), 4) for q in (10, 25, 50, 75, 90, 95, 99)}}


def select_edges(pairs: list[tuple[str, str, float]], k: int, threshold: float) -> list[tuple[str, str, float]]:
    """Undirected edges from directed kNN candidates: cosine >= threshold, at most k edges per node,
    strongest first (ties by id, deterministic). Returns (a, b, score) with a < b."""
    best: dict[tuple[str, str], float] = {}
    for a, b, s in pairs:
        if a == b or s < threshold:
            continue
        key = (a, b) if a < b else (b, a)
        best[key] = max(best.get(key, -1.0), s)
    deg: dict[str, int] = defaultdict(int)
    out = []
    for (a, b), s in sorted(best.items(), key=lambda x: (-x[1], x[0])):
        if deg[a] < k and deg[b] < k:
            deg[a] += 1
            deg[b] += 1
            out.append((a, b, round(float(s), 4)))
    return out


def knn_pairs(ids: list[str], vecs: np.ndarray, k: int) -> list[tuple[str, str, float]]:
    """Exact kNN on normalised vectors (the file-free reference of the pgvector LATERAL query; used in tests)."""
    if len(ids) < 2:
        return []
    sims = vecs @ vecs.T
    np.fill_diagonal(sims, -np.inf)
    out = []
    for i, a in enumerate(ids):
        for j in np.argsort(-sims[i])[:k]:
            out.append((a, ids[j], float(sims[i, j])))
    return out


# =============================================================================
# Paper topics -> existing Topic vertices (LLM chooses from a whitelist; new Topic only if none fits)
#
# Decision table, one OpenAlex topic at a time (first matching row wins):
#   topic_key(label) is already a Topic key        -> reuse it        rules  (identity: Topic vertices are keyed so)
#   LLM on and a shortlist of candidates            -> ask the LLM, then resolve its `choice` (resolve_topic_choice):
#       exactly one candidate by key / label / number -> reuse it    llm
#       "NEW" (or "none")                           -> new Topic       llm
#       anything else (outside the shortlist, ambiguous) -> new Topic  llm, reason "invalid choice ... discarded"
#   no LLM, or the LLM failed                       -> new Topic       rules
# Matching an answer is exact after normalisation (accents, case, punctuation, spaces) and only ever against
# the shortlist that was in the prompt: no alias dictionary, no fuzzy or semantic matching in code.
# =============================================================================
class _TopicChoice(BaseModel):
    choice: str
    reason: str


TOPIC_NEW = "NEW"
_NEW_SENTINELS = ("new", "none")  # the prompt asks for NEW; "none" is the same "no candidate" answer


def _norm_choice(s: str) -> str:
    """Accent-free, lowercase, punctuation as spaces, single spaces (tokenisation, not matching logic)."""
    from .extract import strip_accents
    return " ".join(re.sub(r"[\W_]+", " ", strip_accents(s or "").lower()).split())


def resolve_topic_choice(choice: str, whitelist: list[tuple[str, str]]) -> tuple[str | None, str]:
    """LLM answer -> (candidate key or None, how), how in key | normalised key | label | number | new | invalid |
    ambiguous.

    The candidates are numbered 1..n in the prompt; the answer may be a candidate's key, its label or its
    number. Nothing outside `whitelist` can ever be returned."""
    raw = (choice or "").strip()
    keys = [k for k, _ in whitelist]
    if raw in keys:
        return raw, "key"
    n = _norm_choice(raw)
    if not n:
        return None, "invalid"
    if n in _NEW_SENTINELS:
        return None, "new"
    by_key = {k for k, _ in whitelist if _norm_choice(k) == n}
    by_label = {k for k, l in whitelist if _norm_choice(l) == n}
    hits = by_key or by_label
    if len(hits) == 1:
        return next(iter(hits)), "normalised key" if by_key else "label"
    if len(hits) > 1:
        return None, "ambiguous"
    if n.isdigit() and 1 <= int(n) <= len(whitelist):
        return whitelist[int(n) - 1][0], "number"
    return None, "invalid"


def topic_messages(label: str, context: str, whitelist: list[tuple[str, str]]) -> list[dict]:
    """The prompt: the OpenAlex topic (first quoted string) with its hierarchy, numbered candidates, JSON answer."""
    return [
        {"role": "system", "content": "You curate the research topic vocabulary of an expertise graph. JSON only."},
        {"role": "user", "content": (
            f"A paper is tagged with the bibliographic (OpenAlex) topic \"{label}\" ({context}).\n\n"
            "Candidate topics already in our expertise graph, preselected by text similarity:\n"
            + "\n".join(f"{i}. key: {k} | label: {l}" for i, (k, l) in enumerate(whitelist, 1))
            + "\n\nReuse a candidate ONLY if it names the same research concept as the bibliographic topic: a "
              "synonym, a translation, a spelling or word-order variant, or a near-identical formulation. A "
              "broader or narrower area, a neighbouring field, a related method or disease, or a topic that "
              f"merely shares words is NOT the same concept: answer {TOPIC_NEW}. When in doubt, answer {TOPIC_NEW}.\n"
              "Answer with a JSON object {\"choice\": ..., \"reason\": ...}: `choice` = the candidate key copied "
              f"exactly as written after \"key:\", or \"{TOPIC_NEW}\"; `reason` = one short sentence.")},
    ]


def map_topic(label: str, context: str, whitelist: list[tuple[str, str]], use_llm: bool,
              existing: set[str] | None = None) -> tuple[str | None, str, str]:
    """-> (existing topic key or None for 'create a new Topic', decided_by, reason). See the decision table above.

    `whitelist` = [(key, label)] of existing Topics preselected by embedding similarity; `existing` = every
    existing Topic key (identity check; defaults to the whitelist keys)."""
    from .graph import topic_key
    own = topic_key(label)
    if own in (existing if existing is not None else {k for k, _ in whitelist}):
        return own, "rules", "identical normalised label (existing Topic)"
    prefix = ""
    if use_llm and whitelist:
        try:
            r = llm.chat_json(topic_messages(label, context, whitelist), _TopicChoice, max_tokens=120,
                              temperature=0.0)
        except llm.LLMError as ex:
            prefix = f"LLM unavailable ({str(ex)[:80]}); "
        else:
            choice, reason = r.choice.strip(), r.reason.strip()[:300]  # type: ignore[attr-defined]
            key, how = resolve_topic_choice(choice, whitelist)
            if key is not None:
                return key, "llm", reason if how == "key" else f"choice by {how} {choice!r}: {reason}"
            if how == "new":
                return None, "llm", reason
            return None, "llm", f"invalid choice {choice!r} ({how}) discarded, new topic ({reason})"
    return None, "rules", prefix + "no existing topic with the identical normalised label"


# =============================================================================
# Store steps (Postgres): write, embed, link
# =============================================================================
def _require_papers(store) -> None:
    if not getattr(store, "supports_papers", False):
        from .storage import StorageError
        raise StorageError("unsupported", "papers embed/link need the Postgres backend (set DATABASE_URL); "
                           "`papers collect` still writes data/papers/*.jsonl", backend=store.name)


def write_to_store(store, works: list[Work], matches: list[AuthorMatch], text_dir: Path = TEXT_DIR) -> dict:
    _require_papers(store)
    deduped, alias = dedupe_by_doi(works)
    _log_duplicates("store", alias)
    works = list(deduped.values())
    return {"duplicate_doi_merged": len(alias),
            **store.write_papers(works, matches, {w.id: paper_chunks(w, text_dir) for w in works})}


def embed_pending(store, batch: int = 256) -> dict:
    """Embed every chunk without a vector for the current model (e5 'passage: ' prefix), then refresh
    the paper vectors and the people's research profiles."""
    from . import index
    _require_papers(store)
    n, t0 = 0, time.time()
    while True:
        rows = store.chunks_to_embed(settings.embed_model, batch)
        if not rows:
            break
        vecs = index.embed([t for _, t in rows]).astype(np.float32)
        store.write_chunk_embeddings([(i, v) for (i, _), v in zip(rows, vecs)], settings.embed_model)
        n += len(rows)
    out = {"chunks_embedded": n, "seconds": round(time.time() - t0, 1)}
    out.update(store.refresh_vectors(settings.embed_model))
    return out


def _threshold(setting: str, scores: list[float]) -> float:
    return calibrate_threshold(scores) if setting.strip().lower() == "auto" else float(setting)


def link_similar(store) -> dict:
    """kNN on pgvector -> calibrated threshold -> degree-capped SIMILAR_TO edges (person and paper)."""
    _require_papers(store)
    out: dict = {}
    k = settings.similar_k
    for kind, setting in (("person", settings.similar_person_threshold), ("paper", settings.similar_paper_threshold)):
        pairs = store.knn_candidates(kind, k)
        scores = [s for _, _, s in pairs]
        thr = _threshold(setting, scores)
        edges = select_edges(pairs, k, thr)
        method = f"knn{k}-cos-{'research-mean' if kind == 'person' else 'paper-vector'}"
        store.write_similarity(kind, method, thr, edges)
        out[kind] = {"candidates": len(pairs), "distribution": distribution(scores),
                     "threshold": round(thr, 4), "threshold_mode": setting, "edges": len(edges)}
    out["graph"] = store.write_paper_graph().get("paper_graph", {})
    return out


def link_topics(store, use_llm: bool | None = None, shortlist: int | None = None, remap: bool = False) -> dict:
    """OpenAlex topics of the papers -> Topic vertices (decision table above): identical key = reuse, else the LLM
    picks among the `shortlist` existing Topics most similar to the label (embedding preselection = grounding)
    or asks for a new Topic. Decisions are cached in nav.topic_map: each OpenAlex topic is decided once.

    remap=True decides every OpenAlex topic of the papers again against the base vocabulary only (Topics of the
    indexed entities, not the ones earlier paper runs created), then rewrites topic_map, paper_topic and the
    ABOUT edges. No collect, no paper embedding; running it twice gives the same graph."""
    from . import index
    from .graph import topic_key
    _require_papers(store)
    if use_llm is None:
        use_llm = llm.available()
    shortlist = settings.topic_shortlist if shortlist is None else shortlist
    decided = {} if remap else store.topic_map()
    papers = store.paper_topics()
    labels: dict[str, dict] = {}
    for _, topics in papers:
        for t in topics or []:
            if t.get("id") and t["id"] not in decided:
                labels.setdefault(t["id"], t)
    existing = [(k, l) for k, l in store.existing_topics(base_only=remap) if k]
    existing_keys = {k for k, _ in existing}
    existing_label = dict(existing)
    calls0 = llm.usage["calls"]
    decisions: list[dict] = []
    if labels and existing:
        tvecs = index.embed([l for _, l in existing]).astype(np.float32)
        qvecs = index.embed([t["display_name"] for t in labels.values()], query=True).astype(np.float32)
        sims = qvecs @ tvecs.T
    for j, (tid, t) in enumerate(labels.items()):
        wl = [existing[i] for i in np.argsort(-sims[j])[:shortlist]] if existing else []
        ctx = "; ".join(f"{n}: {t[n]}" for n in ("subfield", "field") if t.get(n)) or "no subfield/field"
        key, by, reason = map_topic(t["display_name"], ctx, wl, use_llm, existing=existing_keys)
        decisions.append({"id": tid, "label": t["display_name"], "key": key or topic_key(t["display_name"]),
                          "topic_label": existing_label.get(key, t["display_name"]) if key else t["display_name"],
                          "is_new": key is None, "by": by, "reason": reason, "cands": [k for k, _ in wl]})
        decided[tid] = key or topic_key(t["display_name"])
    rows = sorted({(pid, decided[t["id"]], t.get("score")) for pid, topics in papers for t in topics or []
                   if t.get("id") in decided and decided[t["id"]]}, key=lambda r: (r[0], r[1]))
    # one row per (paper, topic_key): keep the best score when two OpenAlex topics map to the same Topic
    best: dict[tuple[str, str], float | None] = {}
    for pid, k, s in rows:
        if (pid, k) not in best or (s or 0) > (best[(pid, k)] or 0):
            best[(pid, k)] = s
    stats = store.write_topics(decisions, [(p, k, s) for (p, k), s in sorted(best.items())])
    return {"mode": "remap" if remap else "pending", "topics_decided": len(decisions),
            "reused": sum(not d["is_new"] for d in decisions), "new": sum(d["is_new"] for d in decisions),
            "identical_key": sum(d["reason"].startswith("identical normalised label") for d in decisions),
            "invalid_choice": sum(d["reason"].startswith("invalid choice") for d in decisions),
            "llm_calls": llm.usage["calls"] - calls0, "shortlist": shortlist,
            "decided_by": {b: sum(d["by"] == b for d in decisions) for b in ("llm", "rules")}, **stats}
