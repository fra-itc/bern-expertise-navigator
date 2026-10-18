"""Plain language for non-specialists: jargon explanations and company-request summaries.

* Glossary (config/plain_glossary.yaml): reviewed, deterministic, EN/DE.
* Apertus (when reachable): summarises a company request in plain words and explains terms the
  glossary does not cover. It only sees the request text; every AI-written item is labelled.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml
from pydantic import BaseModel, Field

from . import llm
from .config import CONFIG_DIR

GLOSSARY = CONFIG_DIR / "plain_glossary.yaml"


@lru_cache(maxsize=2)
def _glossary(_mt: float) -> list[dict]:
    if not GLOSSARY.exists():
        return []
    out = []
    for t in (yaml.safe_load(GLOSSARY.read_text()) or {}).get("terms", []):
        forms = sorted({t["term"].lower(), *(a.lower() for a in t.get("aka", []))}, key=len, reverse=True)
        out.append({**t, "forms": forms})
    return out


def glossary() -> list[dict]:
    return _glossary(GLOSSARY.stat().st_mtime if GLOSSARY.exists() else 0.0)


def find_terms(text: str, lang: str = "en") -> list[dict]:
    """Glossary terms occurring in `text`, with the exact form found and its plain explanation."""
    low = text.lower()
    found = []
    for t in glossary():
        for f in t["forms"]:
            if re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", low):
                found.append({"term": t["term"], "found_as": f, "plain": t.get(lang) or t["en"], "source": "glossary"})
                break
    return found


class RequestAnalysis(BaseModel):
    summary: str = Field(description="2-3 sentence company profile in clear, professional business language")
    company_does: str = Field("", description="One sentence: the company's business activity")
    company_needs: list[str] = Field([], description="Business needs the canton can address, as short phrases")
    offerings: list[str] = Field([], description="The company's solutions, products or services")
    keywords: list[str] = Field([], description="Main keywords of the company's business")
    sector: str = Field("", description="e.g. medtech / diabetes technology")
    search_query: str = Field("", description="Short technical search query to find matching researchers")
    terms: list[dict] = Field([], description="[{term, plain}] glossary terms found (used internally)")
    generated_by: str = "rules"


class _LLMAnalysis(BaseModel):
    summary: str
    company_does: str
    company_needs: list[str]
    offerings: list[str]
    keywords: list[str]
    sector: str
    search_query: str


_NEED = re.compile(r"\b(looking for|look for|seek|seeking|need|needs|want|wish|interested in|would like|plan to|"
                   r"partner|collaborat|access to|find|suchen|benötigen|interessiert|cherchons|besoin)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def _rules_analysis(text: str, lang: str) -> RequestAnalysis:
    sents = [s.strip() for s in _SENT.split(" ".join(text.split())) if len(s.strip()) > 15]
    needs = [s for s in sents if _NEED.search(s)][:4]
    does = next((s for s in sents if s not in needs), sents[0] if sents else "")
    terms = find_terms(text, lang)
    query = " ".join(dict.fromkeys(t["term"] for t in terms)) or " ".join(needs)[:200] or text[:200]
    summary = " ".join(sents[:2])
    return RequestAnalysis(summary=summary, company_does=does, company_needs=needs, sector="",
                           search_query=query, terms=terms, generated_by="rules")


def analyze_request(text: str, lang: str = "en") -> RequestAnalysis:
    """A pasted email or note from the company: same profile; without Apertus, the sentences that state a
    need ("we are looking for…") become the business needs."""
    a = analyze_company("", "", text, "", lang)
    if not a.company_needs:
        a.company_needs = _rules_analysis(text, lang).company_needs
    return a


_STOP = set("""the and for with that this from your our their they have has are was were will can into more than about
which while where when what also such other each over most many some only very just them these those using used based
www http https com html page pages home menu cookie cookies privacy contact read learn click here news
der die das und mit für von den dem des ein eine einer eines ist sind wir ihr sie auf aus bei nach oder auch wie
les des une pour avec dans sur par est sont nous vous qui que aux plus
show hide view more less download specifications specification details filter select open close back next
previous search login register subscribe newsletter follow share""".split())
_GENERIC_PAGE = re.compile(r"^(home|start|about( us)?|über uns|a propos|contact|kontakt|products?|produkte|solutions?|"
                           r"lösungen|technology|technologie|company|unternehmen|product finder|find your solution)$", re.I)


def _keywords(text: str, terms: list[dict], k: int = 10) -> list[str]:
    """Glossary terms first (reviewed vocabulary), then the phrases the company repeats most."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{3,}", text.lower()) if w not in _STOP]
    pairs = [f"{a} {b}" for a, b in zip(words, words[1:])]
    counts: dict[str, int] = {}
    for x in pairs:
        counts[x] = counts.get(x, 0) + 1
    out = list(dict.fromkeys(t["term"] for t in terms))
    for x, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n < 2 or len(out) >= k:
            break
        if not any(x in o or o in x for o in out):
            out.append(x)
    singles: dict[str, int] = {}
    for w in words:
        singles[w] = singles.get(w, 0) + 1
    for w, n in sorted(singles.items(), key=lambda kv: -kv[1]):
        if n < 3 or len(out) >= k:
            break
        if not any(w in o for o in out):
            out.append(w)
    return out[:k]


def _offerings(name: str, page_titles: list[str]) -> list[str]:
    """Product and solution pages, named by their own titles minus the site name."""
    out = []
    for t in page_titles[1:]:
        parts = [p.strip() for p in re.split(r"\s+[|–—·-]\s+", t) if p.strip()]
        parts = [p for p in parts if not name or p.lower() != name.lower()] or parts
        title = parts[0] if parts else ""
        if title and not _GENERIC_PAGE.match(title) and title not in out:
            out.append(title)
    return out[:6]


def analyze_company(name: str, description: str, text: str, need: str = "", lang: str = "en",
                    page_titles: list[str] | None = None) -> RequestAnalysis:
    """Company profile for the officer, from its website, shared documents and/or pasted notes, plus the
    optional business need. The search query leads with the stated need: that is what Bern answers."""
    base = _rules_analysis(" ".join(x for x in [description, text] if x), lang)
    # whole sentences only, line by line, so headings and menu items never run into a sentence
    sents = [x.strip() for line in text.splitlines() for x in _SENT.split(" ".join(line.split()))
             if 40 <= len(x.strip()) <= 400 and x.strip()[-1:] in ".!?" and not x.strip()[0].islower()]
    does = description or base.company_does or (sents[0] if sents else "")
    lead = f"{name}: {does}" if name and does and name.lower() not in does.lower() else does
    summary = lead
    for x in sents:
        if len(summary) + len(x) > 600:
            break
        if x != does and x not in summary:
            summary = f"{summary} {x}".strip()
    needs = [need.strip()] if need.strip() else []
    terms = find_terms(" ".join([need, description, text]), lang)
    query = " ".join(dict.fromkeys([need.strip(), *(t["term"] for t in terms[:8])])).strip() \
        or (description or text)[:200]
    base = RequestAnalysis(summary=summary, company_does=does, company_needs=needs,
                           offerings=_offerings(name, page_titles or []),
                           keywords=_keywords(f"{description}\n{text}", terms), sector="",
                           search_query=query[:300], terms=terms, generated_by="rules")
    if not llm.available():
        return base
    language = {"de": "German", "fr": "French"}.get(lang, "English")
    try:
        r: _LLMAnalysis = llm.chat_json([  # type: ignore[assignment]
            {"role": "system", "content": (
                "You prepare company profiles for the business-development team of the Canton of Bern, whose "
                "goal is to attract companies to Bern. The reader is a business professional, not a scientist. "
                "Write clear, concise, professional business language, as in a briefing note: no casual phrasing, "
                "no exclamation marks, no marketing superlatives; avoid jargon or explain it in a few words. "
                "Use ONLY the text given and do not invent facts about the company. "
                f"Write in {language}. JSON only.")},
            {"role": "user", "content": (
                f"Company: {name or 'unknown'}\n"
                + (f"Business need stated by the officer: {need}\n" if need else "")
                + "Text from the company's website, its documents or the officer's notes:\n<<<\n" + text[:7000]
                + "\n>>>\n\n"
                "Return:\n"
                "- summary: a 2-3 sentence company profile (what the company is, its market, its stage if stated).\n"
                "- company_does: one sentence describing its business activity.\n"
                "- company_needs: at most 4 business needs Bern's research, clinical and industrial ecosystem could "
                "address, as short noun phrases. A stated need comes first. Every other need must follow from something "
                "the text says (a product in clinical development → clinical validation partner; a new production "
                "site → manufacturing talent). No generic needs; if the company is already based in Switzerland, do "
                "not suggest market entry in Switzerland. Fewer items are better than speculative ones.\n"
                "- offerings: the company's main solutions, products or services (max 6, short names).\n"
                "- keywords: 6-10 main keywords of its business and technology (products, technologies, therapy "
                "areas, customer segments), each 1-3 words.\n"
                "- sector: e.g. medtech / diabetes technology.\n"
                "- search_query: 5-10 technical keywords to find matching university researchers, labs, "
                "clinical partners and facilities.")},
        ], _LLMAnalysis, mode="none", max_tokens=900)
    except llm.LLMError:
        return base
    query = " ".join(x for x in [need.strip(), r.search_query] if x) or base.search_query
    return RequestAnalysis(summary=r.summary, company_does=r.company_does,
                           company_needs=needs + [n for n in r.company_needs if n not in needs],
                           offerings=r.offerings[:6] or base.offerings, keywords=r.keywords[:10] or base.keywords,
                           sector=r.sector, search_query=query[:300], terms=terms, generated_by="apertus")
