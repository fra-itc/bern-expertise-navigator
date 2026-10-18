"""Broad search without a company ("glucose company in Milan"): Apertus proposes companies, and only those whose
own website answers and talks about the topic are shown, at most three. The model's knowledge may be outdated or
wrong, so nothing it says is shown as a fact: the description comes from the company's homepage, and the homepage is
the only page read (robots.txt respected, internal addresses refused). The officer picks one; the request is then
created from that website, as with a link.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from pydantic import BaseModel

from . import cases, company as company_web, llm, understand

MAX_PROPOSALS = 6     # asked from the model; some will not be verifiable
MAX_SHOWN = 3
_pool = ThreadPoolExecutor(max_workers=MAX_PROPOSALS)
_SENT = re.compile(r"(?<=[.!?])\s+")


class Candidate(BaseModel):
    name: str
    url: str                       # the website as it answered (after redirects)
    description: str               # the company's own words: meta description or first sentence of the homepage
    topic_found: list[str] = []    # topic words found on the homepage
    place_found: str = ""          # the requested place, when the homepage names it


class Suggestions(BaseModel):
    candidates: list[Candidate] = []
    understood: understand.Understood
    message: str | None = None
    link: str = ""                 # the search was a website link: no suggestions needed, create the request directly


class _Proposal(BaseModel):
    name: str
    website: str


class _Proposals(BaseModel):
    companies: list[_Proposal] = []


def _words(u: understand.Understood) -> list[str]:
    """What the homepage must mention: the searched words and the niche's keywords in every language."""
    rest = [w for w in u.rest.split() if len(w) >= 4]
    return list(dict.fromkeys(rest + (understand.topic_keywords(u.area, u.niche) if u.area else [])))


def _found(words: list[str], text: str) -> list[str]:
    """A single long word by its stem ("glucos" also finds "glucosio"); a phrase or a short word whole."""
    def rx(w: str) -> str:
        if " " not in w and len(w) >= 6:
            return rf"(?<!\w){re.escape(w[:6])}"
        return rf"(?<!\w){re.escape(w)}(?!\w)"
    return [w for w in words if re.search(rx(w), text)]


def _description(site: company_web.CompanyWebsite) -> str:
    if site.description:
        return site.description[:300]
    first = next((s for s in _SENT.split(" ".join(site.text.split())) if 40 <= len(s) <= 300), "")
    return first


def _verify(p: _Proposal, words: list[str], places: list[str], place: str) -> Candidate | None:
    try:
        site = company_web.read(p.website, max_extra=0)
    except (company_web.FetchError, ValueError):
        return None
    except Exception:  # noqa: BLE001 - one unreachable suggestion must not sink the others
        return None
    text = understand.norm(f"{site.name} {site.description} {site.text}")
    topic = _found(words, text)
    if words and not topic:
        return None                                     # the site does not talk about what was searched
    on_site = next((n for n in places if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text)), "")
    return Candidate(name=p.name.strip()[:120] or site.name, url=site.url, description=_description(site),
                     topic_found=topic[:5], place_found=place if on_site else "")


def suggest(text: str, lang: str = "en") -> Suggestions:
    link, _ = cases.split_link(text)
    u = understand.understand(text)
    if link:
        return Suggestions(understood=u, link=link)
    if not llm.available():
        return Suggestions(understood=u, message="Apertus is not reachable, so no companies can be suggested. "
                                                 "Enter the company's website, or continue with the search only.")
    place = u.city or u.canton or u.country
    topic = f"{u.area}{' / ' + u.niche if u.niche else ''}" if u.area else ""
    try:
        r: _Proposals = llm.chat_json([  # type: ignore[assignment]
            {"role": "system", "content": "You help the business-development team of the Canton of Bern find companies. "
                                          "Name only real companies you are confident exist, with their official "
                                          "website. JSON only."},
            {"role": "user", "content": (
                f"Search: {text}\n" + (f"Topic: {topic}\n" if topic else "") + (f"Place: {place}\n" if place else "")
                + f"\nList up to {MAX_PROPOSALS} companies that match this search, best match first. If the search names "
                "a company, list that company first. For each: name, website (the official domain, e.g. example.com). "
                'Return {"companies": [{"name": "...", "website": "..."}]}.')},
        ], _Proposals, mode="none", max_tokens=400)
    except llm.LLMError:
        return Suggestions(understood=u, message="Apertus did not answer. Try again, or enter the company's website.")
    seen, props = set(), []
    for p in r.companies:
        host = (urlparse(company_web.normalise(p.website)).hostname or "").removeprefix("www.")
        if host and host not in seen:
            seen.add(host)
            props.append(p)
    words = _words(u)
    places = understand.place_names(place) if place else []
    checked = list(_pool.map(lambda p: _verify(p, words, places, place), props[:MAX_PROPOSALS]))
    # model order is kept, but a homepage that names the place comes first
    found = [c for c in checked if c]
    found.sort(key=lambda c: not c.place_found)
    if not found:
        return Suggestions(understood=u, message="None of the companies Apertus suggested could be verified on its own "
                                                 "website. Enter the company's website, or continue with the search only.")
    return Suggestions(understood=u, candidates=found[:MAX_SHOWN])
