"""OpenAlex client (https://api.openalex.org) and pure parsers for its JSON.

Politeness and failure handling, in one place:
  - rate limit: at most `rps` requests per second (shared by all threads);
  - retry with exponential backoff on 429 / 5xx / transport errors (honours Retry-After);
  - circuit breaker: after `breaker_threshold` consecutive failures every call fails fast with
    OpenAlexError("circuit_open") for `breaker_cooldown` seconds;
  - disk cache (data/cache/openalex/<sha1>.json, TTL in days): a re-run costs nothing.

Credentials: OPENALEX_API_KEY goes in the Authorization header (never in the URL, never in the
cache key, never logged); OPENALEX_MAILTO is sent as `mailto=` when set.
Cost accounting: OpenAlex reports the price of every call in meta.cost_usd; `usage` sums it.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .config import DATA_DIR, settings
from .schema import PaperAuthor, Work

CACHE_DIR = DATA_DIR / "cache" / "openalex"


class OpenAlexError(RuntimeError):
    """Structured failure: `code` is stable (http_4xx, rate_limited, circuit_open, transport, bad_json)."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"[openalex:{code}] {detail}")


def short_id(url_or_id: str | None) -> str | None:
    """'https://openalex.org/W123' -> 'W123' (ids are URLs in OpenAlex JSON)."""
    if not url_or_id:
        return None
    return url_or_id.rstrip("/").rsplit("/", 1)[-1]


def strip_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip()
    for p in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.lower().startswith(p):
            d = d[len(p):]
    return d.lower() or None


def reconstruct_abstract(inv: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; put every word back at its positions."""
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, places in inv.items():
        for p in places:
            pos[p] = word
    if not pos:
        return None
    return " ".join(pos[i] for i in sorted(pos)).strip() or None


def parse_work(raw: dict, fetched_at: str) -> Work:
    """OpenAlex work JSON -> Work. Only what the navigator uses; unknown/missing fields are tolerated."""
    loc = raw.get("primary_location") or {}
    src = loc.get("source") or {}
    oa = raw.get("open_access") or {}
    best = raw.get("best_oa_location") or {}
    pdfs: list[str] = []
    if oa.get("is_oa"):
        for l in [best, *(raw.get("locations") or [])]:
            if l and l.get("is_oa") and l.get("pdf_url"):
                pdfs.append(l["pdf_url"])
    authors = []
    for i, a in enumerate(raw.get("authorships") or []):
        au = a.get("author") or {}
        authors.append(PaperAuthor(
            position=i, author_position=a.get("author_position"), author_id=short_id(au.get("id")),
            name=au.get("display_name") or a.get("raw_author_name") or "",
            institutions=[x for x in (short_id(inst.get("id")) for inst in a.get("institutions") or []) if x]))
    ids = raw.get("ids") or {}
    return Work(
        id=short_id(raw["id"]), doi=strip_doi(raw.get("doi")),
        title=(raw.get("title") or raw.get("display_name") or "").strip(),
        year=raw.get("publication_year"), venue=src.get("display_name"),
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
        authors=authors,
        topics=[{"id": short_id(t.get("id")), "display_name": t.get("display_name", ""), "score": t.get("score"),
                 "subfield": (t.get("subfield") or {}).get("display_name"),
                 "field": (t.get("field") or {}).get("display_name")} for t in raw.get("topics") or []],
        concepts=[{"id": short_id(c.get("id")), "display_name": c.get("display_name", ""), "score": c.get("score")}
                  for c in (raw.get("concepts") or []) if (c.get("score") or 0) >= 0.3][:10],
        cited_by_count=raw.get("cited_by_count") or 0,
        referenced_works=[x for x in (short_id(r) for r in raw.get("referenced_works") or []) if x],
        is_oa=bool(oa.get("is_oa")), oa_status=oa.get("oa_status"),
        pdf_urls=list(dict.fromkeys(pdfs)),
        landing_url=best.get("landing_page_url") or loc.get("landing_page_url"),
        pmid=short_id(ids.get("pmid")), pmcid=short_id(ids.get("pmcid")),
        fetched_at=fetched_at)


def candidate_summary(raw: dict, bern_ids: set[str]) -> dict:
    """OpenAlex author JSON -> the compact card the matcher (LLM or rules) sees."""
    insts = []
    bern = False
    for a in raw.get("affiliations") or []:
        inst = a.get("institution") or {}
        lineage = {short_id(x) for x in inst.get("lineage") or []} | {short_id(inst.get("id"))}
        is_bern = bool(lineage & bern_ids)
        bern = bern or is_bern
        years = a.get("years") or []
        insts.append({"name": inst.get("display_name", ""), "country": inst.get("country_code"),
                      "years": f"{min(years)}-{max(years)}" if years else "", "bern": is_bern})
    last = []
    for inst in raw.get("last_known_institutions") or []:
        lineage = {short_id(x) for x in inst.get("lineage") or []} | {short_id(inst.get("id"))}
        bern = bern or bool(lineage & bern_ids)
        last.append(inst.get("display_name", ""))
    return {
        "id": short_id(raw.get("id")), "display_name": raw.get("display_name", ""),
        "alternatives": (raw.get("display_name_alternatives") or [])[:6],
        "orcid": raw.get("orcid"), "works_count": raw.get("works_count", 0),
        "cited_by_count": raw.get("cited_by_count", 0),
        "last_known_institutions": last, "affiliations": insts[:6],
        "topics": [t.get("display_name", "") for t in (raw.get("topics") or [])[:6]],
        "bern": bern,
    }


WORK_SELECT = ("id,doi,title,display_name,publication_year,primary_location,abstract_inverted_index,authorships,"
               "topics,concepts,cited_by_count,referenced_works,open_access,best_oa_location,locations,ids,type")
AUTHOR_SELECT = ("id,display_name,display_name_alternatives,orcid,works_count,cited_by_count,"
                 "last_known_institutions,affiliations,topics")


class OpenAlexClient:
    def __init__(self, *, base_url: str | None = None, mailto: str | None = None, api_key: str | None = None,
                 rps: float | None = None, cache_dir: Path | None = CACHE_DIR, cache_days: float | None = None,
                 transport: httpx.BaseTransport | None = None, max_retries: int = 4, backoff: float = 1.0,
                 breaker_threshold: int = 5, breaker_cooldown: float = 60.0, sleep=time.sleep):
        self.base = (base_url or settings.openalex_base_url).rstrip("/")
        self.mailto = settings.openalex_mailto if mailto is None else mailto
        key = settings.openalex_api_key if api_key is None else api_key
        headers = {"User-Agent": "BernExpertiseNavigator/1.0 (papers; +https://github.com/swiss-ai)"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.Client(headers=headers, timeout=30, transport=transport, follow_redirects=True)
        self.min_interval = 1.0 / max(0.1, rps or settings.openalex_rps)
        self.cache_dir = cache_dir
        self.cache_ttl = 86400 * (settings.openalex_cache_days if cache_days is None else cache_days)
        self.max_retries, self.backoff, self.sleep = max_retries, backoff, sleep
        self.breaker_threshold, self.breaker_cooldown = breaker_threshold, breaker_cooldown
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._fails = 0
        self._open_until = 0.0
        self.usage = {"requests": 0, "cache_hits": 0, "retries": 0, "cost_usd": 0.0}

    # ---------------- transport ---------------------------------------------------
    def _cache_path(self, path: str, params: dict) -> Path | None:
        if self.cache_dir is None:
            return None
        key = path + "?" + urlencode(sorted(params.items()))
        return self.cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + self.min_interval
        if wait > 0:
            self.sleep(wait)

    def _breaker_check(self) -> None:
        with self._lock:
            if time.monotonic() < self._open_until:
                raise OpenAlexError("circuit_open", f"{self._fails} consecutive failures; retry in "
                                    f"{self._open_until - time.monotonic():.0f}s")

    def _record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                return
            self._fails += 1
            if self._fails >= self.breaker_threshold:
                self._open_until = time.monotonic() + self.breaker_cooldown

    def get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        cp = self._cache_path(path, params)
        if cp is not None and cp.exists() and time.time() - cp.stat().st_mtime < self.cache_ttl:
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                with self._lock:
                    self.usage["cache_hits"] += 1
                return data
            except ValueError:
                pass  # corrupt cache entry: fetch again
        if self.mailto:
            params["mailto"] = self.mailto
        last: OpenAlexError | None = None
        for attempt in range(self.max_retries + 1):
            self._breaker_check()
            self._throttle()
            try:
                r = self.http.get(self.base + path, params=params)
            except httpx.HTTPError as e:
                last = OpenAlexError("transport", f"{type(e).__name__}: {e}")
                self._record(False)
            else:
                with self._lock:
                    self.usage["requests"] += 1
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError as e:
                        self._record(False)
                        raise OpenAlexError("bad_json", f"{path}: {e}") from e
                    self._record(True)
                    with self._lock:
                        self.usage["cost_usd"] += float((data.get("meta") or {}).get("cost_usd") or 0)
                    if cp is not None:
                        cp.parent.mkdir(parents=True, exist_ok=True)
                        tmp = cp.with_suffix(f".{threading.get_ident()}.tmp")
                        tmp.write_text(json.dumps(data), encoding="utf-8")
                        tmp.replace(cp)
                    return data
                if r.status_code == 404:
                    self._record(True)  # a missing record is an answer, not an outage
                    raise OpenAlexError("not_found", path)
                if r.status_code == 429 or r.status_code >= 500:
                    last = OpenAlexError("rate_limited" if r.status_code == 429 else f"http_{r.status_code}",
                                         f"{path}: {r.text[:200]}")
                    self._record(False)
                    retry_after = r.headers.get("Retry-After")
                    if attempt < self.max_retries:
                        with self._lock:
                            self.usage["retries"] += 1
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else \
                            self.backoff * (2 ** attempt)
                        self.sleep(min(delay, 60.0))
                    continue
                self._record(True)
                raise OpenAlexError(f"http_{r.status_code}", f"{path}: {r.text[:200]}")
            if attempt < self.max_retries:
                with self._lock:
                    self.usage["retries"] += 1
                self.sleep(min(self.backoff * (2 ** attempt), 60.0))
        raise last or OpenAlexError("transport", path)

    # ---------------- endpoints ---------------------------------------------------
    def institutions_by_ror(self, rors: list[str]) -> list[dict]:
        if not rors:
            return []
        d = self.get("/institutions", {"filter": "ror:" + "|".join(rors), "per-page": 50,
                                       "select": "id,ror,display_name,country_code,type"})
        return d.get("results") or []

    def search_authors(self, name: str, institution_ids: list[str], per_page: int = 8) -> list[dict]:
        params = {"search": name, "per-page": per_page, "select": AUTHOR_SELECT}
        if institution_ids:
            params["filter"] = "affiliations.institution.id:" + "|".join(institution_ids)
        return self.get("/authors", params).get("results") or []

    def works_by_author(self, author_id: str, *, since_year: int, limit: int) -> list[dict]:
        d = self.get("/works", {"filter": f"author.id:{author_id},from_publication_date:{since_year}-01-01,"
                                          "is_paratext:false",
                                "sort": "publication_date:desc", "per-page": max(1, min(limit, 100)),
                                "select": WORK_SELECT})
        return (d.get("results") or [])[:limit]

    def works_by_ids(self, field: str, values: list[str]) -> list[dict]:
        """Batch lookup by an external id filter (doi / pmid), 50 per call."""
        out: list[dict] = []
        for i in range(0, len(values), 50):
            chunk = values[i:i + 50]
            d = self.get("/works", {"filter": f"{field}:" + "|".join(chunk), "per-page": 50, "select": WORK_SELECT})
            out += d.get("results") or []
        return out

    def work(self, ref: str) -> dict:
        """Single work by id or 'doi:10.x/y' (single-record lookups are free on OpenAlex)."""
        return self.get(f"/works/{ref}", {"select": WORK_SELECT})

    def close(self) -> None:
        self.http.close()
