"""OpenAlex as a source (https://openalex.org, open scholarly database, CC0 data, public API).

Who is included: authors who published under a University of Bern affiliation, in medtech-relevant
fields, since `from_date`. OpenAlex's own "last known institution" is sometimes wrong (homonyms), so we
do not trust it: a person counts only through papers where *their own* authorship lists the institution
(at least `min_works` of them).

What we keep, per researcher, as one record page (data/pages/<source>.jsonl, url = their openalex.org page):
    <Name>
    ORCID: https://orcid.org/...
    University of Bern: 7 publications since 2023
    Department: <the affiliation text they used most often on those papers>
    Research topic: <topic>                     (most frequent topics of those papers)
    Publication: <title> (2024) doi:10.xxxx/... (most recent first)
Each line is copied from the OpenAlex records, so the usual snippet verifier applies unchanged.

Fetching is explicit only (`make crawl SOURCE=unibe`), bounded, and paced (OpenAlex allows ~10 req/s).
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx

from .config import DATA_DIR, Source
from .schema import Cited, Entity, Evidence, ExtractedEntity, Page

API = "https://api.openalex.org"
_UNIT_HINT = re.compile(r"\b(department|departement|institut|institute|clinic|klinik|clinique|center|centre|zentrum|"
                        r"division|abteilung|laborator|lab\b|unit|group|gruppe|school|faculty|fakultät)", re.I)
# affiliation parts that only name the university, the hospital, the city or the country
_GENERIC_PART = re.compile(r"^(the )?(university of bern|universit[äa]t bern|universit[ée] de berne|bern university hospital|"
                           r"inselspital( bern)?|insel gruppe|bern|berne|3010 bern|ch-3010 bern|switzerland|schweiz|"
                           r"suisse|svizzera)$", re.I)
_ORG = r"(the )?(university of bern|universit[äa]t bern|inselspital|bern university hospital)\b"


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    key, mailto = os.getenv("OPENALEX_API_KEY", ""), os.getenv("OPENALEX_MAILTO", "")
    if key:
        params = {**params, "api_key": key}         # free key from openalex.org/settings/api: own daily budget
    elif mailto:
        params = {**params, "mailto": mailto}       # optional team contact address
    for attempt in range(4):
        r = client.get(f"{API}{path}", params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        time.sleep(0.15)                            # stay well below the API's rate limit
        return r.json()
    r.raise_for_status()
    return {}


def _unit(affiliation: str) -> str:
    """'Department of Diabetes, Endocrinology and Metabolism, Inselspital, Bern University Hospital, University
    of Bern, Bern, Switzerland' -> 'Department of Diabetes, Endocrinology and Metabolism'."""
    # some affiliations have no commas: "Department of Periodontology University of Bern Bern Switzerland"
    affiliation = re.sub(rf"\s+(?={_ORG})", ", ", affiliation, flags=re.I)
    parts = [p.strip() for p in affiliation.split(",") if p.strip()]
    keep = []
    for p in parts:
        if _GENERIC_PART.match(p) or re.match(_ORG, p, re.I) or re.match(r"^\d{4}\b|^ch-\d{4}", p, re.I):
            break
        keep.append(p)
    unit = ", ".join(keep)
    return unit if _UNIT_HINT.search(unit) and len(unit) <= 160 else ""


def fetch(src: Source) -> list[Page]:
    o = src.options
    inst = o["institution"]
    since = str(o.get("from_date", "2023-01-01"))
    subfields = "|".join(str(x) for x in o.get("subfields", []))
    min_works, max_authors, max_pubs = int(o.get("min_works", 3)), int(o.get("max_authors", 600)), int(o.get("max_publications", 6))
    inst_url = f"https://openalex.org/{inst}"
    flt = f"institutions.id:{inst},from_publication_date:{since}" + (f",primary_topic.subfield.id:{subfields}" if subfields else "")

    works_by: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    affil: dict[str, Counter] = defaultdict(Counter)
    topics: dict[str, Counter] = defaultdict(Counter)
    # Without an API key OpenAlex only allows plain page numbers (first 10,000 results); with one, cursor paging.
    use_cursor = bool(os.getenv("OPENALEX_API_KEY"))
    cursor, page_no, n_works = "*", 1, 0
    with httpx.Client(headers={"User-Agent": src.user_agent}) as client:
        while cursor:
            paging = {"cursor": cursor} if use_cursor else {"page": page_no}
            d = _get(client, "/works", {"filter": flt, "per-page": 200, **paging,
                                        "select": "id,doi,title,publication_year,authorships,primary_topic,topics"})
            for w in d.get("results", []):
                n_works += 1
                wtopics = [t["display_name"] for t in ([w.get("primary_topic")] + (w.get("topics") or [])) if t][:3]
                for a in w.get("authorships", []):
                    if not any(i.get("id") == inst_url for i in a.get("institutions", [])):
                        continue            # this author did not sign this paper as University of Bern
                    aid = ((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1]   # some authorships have no author id
                    if not aid:
                        continue
                    names[aid] = a["author"].get("display_name") or names.get(aid, "") or aid
                    works_by[aid].append({"title": (w.get("title") or "").strip(), "year": w.get("publication_year"),
                                          "doi": (w.get("doi") or "").removeprefix("https://doi.org/")})
                    for s in a.get("raw_affiliation_strings") or []:
                        if re.search(r"\bbern", s, re.I):
                            affil[aid][s.strip()] += 1
                    topics[aid].update(wtopics)
            if use_cursor:
                cursor = d.get("meta", {}).get("next_cursor")
            else:
                page_no += 1
                total = d.get("meta", {}).get("count", 0)
                cursor = "" if not d.get("results") or (page_no - 1) * 200 >= min(total, 10000) else "more"
                if total > 10000 and not cursor:
                    print(f"[openalex] {total} works match, only the first 10,000 are readable without OPENALEX_API_KEY")
            print(f"[openalex] {n_works} works read, {len(works_by)} University of Bern authors so far")

        chosen = sorted((a for a, ws in works_by.items() if len(ws) >= min_works), key=lambda a: -len(works_by[a]))[:max_authors]
        orcid: dict[str, str] = {}
        for i in range(0, len(chosen), 50):       # author records: ORCID and the canonical display name
            batch = chosen[i:i + 50]
            d = _get(client, "/authors", {"filter": "openalex:" + "|".join(batch), "per-page": 50,
                                          "select": "id,display_name,orcid"})
            for a in d.get("results", []):
                aid = (a.get("id") or "").rsplit("/", 1)[-1]
                names[aid] = a.get("display_name") or names.get(aid, "")
                orcid[aid] = a.get("orcid") or ""

    now = datetime.now(timezone.utc).isoformat()
    pages = []
    for aid in chosen:
        ws = sorted(works_by[aid], key=lambda w: -(w["year"] or 0))
        lines = [names[aid]]
        if orcid.get(aid):
            lines.append(f"ORCID: {orcid[aid]}")
        lines.append(f"{src.label}: {len(ws)} publications since {since[:4]}")
        if affil[aid]:
            lines.append(f"Department: {affil[aid].most_common(1)[0][0]}")
        lines += [f"Research topic: {t}" for t, _ in topics[aid].most_common(6)]
        seen = set()
        for w in ws:
            if w["title"] and w["title"] not in seen and len(seen) < max_pubs:
                seen.add(w["title"])
                lines.append(f"Publication: {w['title']} ({w['year']})" + (f" doi:{w['doi']}" if w["doi"] else ""))
        pages.append(Page(url=f"https://openalex.org/{aid}", source=src.name, title=names[aid],
                          text="\n".join(lines), fetched_at=now, page_type="person"))
    out = DATA_DIR / "pages" / f"{src.name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for p in pages:
            fh.write(p.model_dump_json() + "\n")
    print(f"[openalex] {src.name}: {len(pages)} researchers from {n_works} publications -> {out}")
    return pages


def to_extracted(page: Page) -> tuple[ExtractedEntity, list[str]]:
    """A record page -> one person (name, department, institution, research topics) + its publication lines."""
    lines = [ln for ln in page.text.splitlines() if ln.strip()]
    name = lines[0]
    ent = ExtractedEntity(entity_type="person", name=Cited(value=name, snippet=name))
    pubs = []
    for ln in lines[1:]:
        if ln.startswith("Department: "):
            unit = _unit(ln.removeprefix("Department: "))
            if unit:
                ent.unit = Cited(value=unit, snippet=ln)
        elif ln.startswith("Research topic: "):
            ent.expertise.append(Cited(value=ln.removeprefix("Research topic: "), snippet=ln))
        elif ln.startswith("Publication: "):
            pubs.append(ln)
        elif " publications since " in ln:
            ent.institute = Cited(value=ln.split(":", 1)[0], snippet=ln)
    return ent, pubs


def publication_evidence(page: Page, pubs: list[str]) -> list[Evidence]:
    return [Evidence(field="publication", value=re.sub(r"^Publication: | \(\d{4}\).*$", "", ln), snippet=ln, url=page.url)
            for ln in pubs]


def attach_to_web_profiles(entities: list[Entity], openalex_sources: set[str]) -> list[Entity]:
    """A researcher found both on a website (e.g. ARTORG) and in OpenAlex becomes ONE entity: the website
    profile keeps its role and lab and gains the OpenAlex topics and publications (with their own links)."""
    web_people = [e for e in entities if e.entity_type == "person" and e.source not in openalex_sources]
    by_surname: dict[str, list[Entity]] = defaultdict(list)
    for e in web_people:
        toks = _name_tokens(e.name)
        if toks:
            by_surname[toks[-1]].append(e)

    def match(e: Entity) -> Entity | None:
        """Same surname and compatible first name ("L. Witthauer" ~ "Prof. Dr. phil. Lilian Witthauer",
        "Stavroula Georgia Mougiakakou" ~ "Stavroula Mougiakakou"); ambiguous -> no merge."""
        toks = _name_tokens(e.name)
        if not toks:
            return None
        hits = [w for w in by_surname.get(toks[-1], []) if _first_compatible(toks[0], _name_tokens(w.name)[0])]
        return hits[0] if len({h.id for h in hits}) == 1 else None

    out = []
    for e in entities:
        target = match(e) if e.source in openalex_sources and e.entity_type == "person" else None
        if target is None:
            out.append(e)
            continue
        have = {(ev.field, ev.snippet) for ev in target.evidence}   # OpenAlex sometimes splits one person in two records
        target.evidence += [ev for ev in e.evidence if ev.field != "name" and (ev.field, ev.snippet) not in have]
        target.expertise = list(dict.fromkeys(target.expertise + e.expertise))
        target.source_urls = list(dict.fromkeys(target.source_urls + e.source_urls))
        target.institute = target.institute or e.institute
    return out


def _name_tokens(name: str) -> list[str]:
    from .extract import name_key
    return [t for t in name_key(name).split() if t]


def _first_compatible(a: str, b: str) -> bool:
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return a == b
