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
from .openalex import OpenAlexClient, OpenAlexError, candidate_summary, parse_work, short_id
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
    """Word windows of `size` words (~1.3 e5 tokens per word: 300 words ~ 400 tokens) with `overlap` words.
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


def collect(entities: list[Entity], pages: list[Page], client: OpenAlexClient, *,
            fetcher: PdfFetcher | None = None, use_llm: bool | None = None, types: tuple[str, ...] = ("person",),
            limit: int = 0, max_pdfs: int = 0, workers: int = 4, text_dir: Path = TEXT_DIR) -> CollectResult:
    """People -> author match -> works (+ page-linked works) -> OA PDFs. Never raises for one person."""
    if use_llm is None:
        use_llm = llm.available()
    insts = resolve_bern(client, list(settings.papers_rors))
    bern_ids = {short_id(i["id"]) for i in insts}
    people = [e for e in entities if e.entity_type in types]
    if limit:
        people = people[:limit]
    stats: dict = {"institutions": [{"id": short_id(i["id"]), "ror": i.get("ror"), "name": i.get("display_name")}
                                    for i in insts], "people": len(people), "candidates": 0,
                   "matched": 0, "decided_by": defaultdict(int), "errors": 0}
    raw_works: dict[str, dict] = {}
    entity_works: dict[str, list[tuple[str, EntityLink]]] = defaultdict(list)
    matches: list[AuthorMatch] = []
    lock = threading.Lock()

    def one(e: Entity):
        try:
            raw = client.search_authors(name_key(e.name), sorted(bern_ids), per_page=settings.papers_max_candidates)
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
    author_entity = {m.chosen_author_id: m.entity_id for m in matches if m.chosen_author_id}
    for w in works.values():
        for a in w.authors:
            if a.author_id in author_entity:
                a.entity_id = author_entity[a.author_id]
    for eid, items in entity_works.items():
        for wid, link in items:
            w = works[wid]
            if link.relation == "author":
                pos = next((a.position for a in w.authors if a.author_id == link.author_id), None)
                link = link.model_copy(update={"position": pos})
            if not any(l.entity_id == eid and l.relation == link.relation for l in w.links):
                w.links.append(link)
    # co-authors matched to other people: one link each, from the authorship list
    for w in works.values():
        for a in w.authors:
            if a.entity_id and not any(l.entity_id == a.entity_id and l.relation == "author" for l in w.links):
                w.links.append(EntityLink(entity_id=a.entity_id, relation="author", position=a.position,
                                          author_id=a.author_id))
    stats["works"] = len(works)
    stats["oa_works"] = sum(w.is_oa for w in works.values())
    stats["oa_with_pdf_url"] = sum(bool(w.pdf_urls) for w in works.values())
    if fetcher is not None and settings.papers_pdf:
        stats["pdf"] = fetch_fulltexts(list(works.values()), fetcher, max_pdfs=max_pdfs, text_dir=text_dir)
    else:
        for w in works.values():
            w.fulltext_status = w.fulltext_status or ("pdf_disabled" if w.pdf_urls else
                                                      "not_oa" if not w.is_oa else "no_pdf_url")
    stats["decided_by"] = dict(stats["decided_by"])
    stats["openalex"] = dict(client.usage)
    stats["llm_usage"] = dict(llm.usage)
    return CollectResult(works=works, matches=matches, stats=stats)


def fetch_fulltexts(works: list[Work], fetcher: PdfFetcher, *, max_pdfs: int = 0,
                    text_dir: Path = TEXT_DIR) -> dict:
    """Only OA works with an OA pdf_url are ever fetched; the first URL that yields a readable PDF wins."""
    counts: dict[str, int] = defaultdict(int)
    tried = 0
    for w in sorted(works, key=lambda x: (-(x.year or 0), x.id)):
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
# =============================================================================
class _TopicChoice(BaseModel):
    choice: str
    reason: str


def map_topic(label: str, context: str, whitelist: list[tuple[str, str]], use_llm: bool) -> tuple[str | None, str, str]:
    """-> (existing topic key or None for 'create a new Topic', decided_by, reason).

    `whitelist` = [(key, label)] of existing Topics preselected by embedding similarity."""
    from .graph import topic_key
    keys = {k for k, _ in whitelist}
    prefix = ""
    if use_llm and whitelist:
        try:
            r = llm.chat_json([
                {"role": "system", "content": "You curate a research topic vocabulary. JSON only."},
                {"role": "user", "content": (
                    f"A paper is tagged with the bibliographic topic: \"{label}\" ({context}).\n"
                    "Existing topics of our expertise graph (key: label):\n"
                    + "\n".join(f"- {k}: {l}" for k, l in whitelist)
                    + "\n\nIf one existing topic names the same research area (a synonym, translation or a "
                      "very close formulation), answer `choice` = its key exactly as listed. If none of them "
                      "fits, answer `choice` = \"new\". `reason`: one short sentence.")},
            ], _TopicChoice, max_tokens=120, temperature=0.0)
        except llm.LLMError as ex:
            prefix = f"LLM unavailable ({str(ex)[:80]}); "
        else:
            choice, reason = r.choice.strip(), r.reason.strip()[:300]  # type: ignore[attr-defined]
            if choice in keys:
                return choice, "llm", reason
            if choice.lower() == "new":
                return None, "llm", reason
            return None, "llm", f"invalid choice {choice!r} discarded, new topic ({reason})"
    k = topic_key(label)
    if k in keys:
        return k, "rules", prefix + "identical normalised label"
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
    return store.write_papers(works, matches, {w.id: paper_chunks(w, text_dir) for w in works})


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


def link_topics(store, use_llm: bool | None = None, shortlist: int = 12) -> dict:
    """OpenAlex topics of the papers -> Topic vertices: the LLM picks among the `shortlist` existing Topics most
    similar to the label (embedding preselection = grounding), or asks for a new Topic. Decisions are cached in
    nav.topic_map: each OpenAlex topic is decided once."""
    from . import index
    from .graph import topic_key
    _require_papers(store)
    if use_llm is None:
        use_llm = llm.available()
    decided = store.topic_map()
    papers = store.paper_topics()
    labels: dict[str, dict] = {}
    for _, topics in papers:
        for t in topics or []:
            if t.get("id") and t["id"] not in decided:
                labels.setdefault(t["id"], t)
    existing = [(k, l) for k, l in store.existing_topics() if k]
    decisions: list[dict] = []
    if labels and existing:
        tvecs = index.embed([l for _, l in existing]).astype(np.float32)
        qvecs = index.embed([t["display_name"] for t in labels.values()], query=True).astype(np.float32)
        sims = qvecs @ tvecs.T
    for j, (tid, t) in enumerate(labels.items()):
        wl = [existing[i] for i in np.argsort(-sims[j])[:shortlist]] if existing else []
        ctx = ", ".join(x for x in (t.get("subfield"), t.get("field")) if x) or "no field"
        key, by, reason = map_topic(t["display_name"], ctx, wl, use_llm)
        label = dict(existing).get(key, t["display_name"]) if key else t["display_name"]
        decisions.append({"id": tid, "label": t["display_name"], "key": key or topic_key(t["display_name"]),
                          "topic_label": label, "is_new": key is None, "by": by, "reason": reason,
                          "cands": [k for k, _ in wl]})
        decided[tid] = key or topic_key(t["display_name"])
    rows = sorted({(pid, decided[t["id"]], t.get("score")) for pid, topics in papers for t in topics or []
                   if t.get("id") in decided and decided[t["id"]]}, key=lambda r: (r[0], r[1]))
    # one row per (paper, topic_key): keep the best score when two OpenAlex topics map to the same Topic
    best: dict[tuple[str, str], float | None] = {}
    for pid, k, s in rows:
        if (pid, k) not in best or (s or 0) > (best[(pid, k)] or 0):
            best[(pid, k)] = s
    stats = store.write_topics(decisions, [(p, k, s) for (p, k), s in sorted(best.items())])
    return {"topics_decided": len(decisions), "reused": sum(not d["is_new"] for d in decisions),
            "new": sum(d["is_new"] for d in decisions),
            "decided_by": {b: sum(d["by"] == b for d in decisions) for b in ("llm", "rules")}, **stats}
