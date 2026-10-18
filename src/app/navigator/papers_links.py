"""Recognise links to scholarly works (DOI, PubMed, PMC, arXiv, BORIS, direct PDF).

Pure functions, no I/O. These are structured identifiers with a fixed published syntax, so fixed
patterns are the right tool here (not an LLM): a DOI is ``10.<registrant>/<suffix>``, a PubMed id is
a number on a known host, and so on.

    paper_ref("https://doi.org/10.1000/XYZ.1")  ->  PaperRef(scheme="doi", id="10.1000/xyz.1", ...)
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urldefrag, urljoin, urlparse, urlunparse

from .schema import PaperRef

# Crossref's recommended pattern; must start at a boundary so "v10.2023/x" or "a10.1234/b" do not match
_DOI = re.compile(r"(?:^|(?<=[/=:\s(\[]))(10\.\d{4,9}/[-._;()/:a-z0-9<>]+)", re.I)
# Publisher URLs often append a view after the DOI: .../10.1002/abc.123/full
_DOI_TAIL = re.compile(r"(/(full|abstract|pdf|epdf|fulltext(\.html)?|references|figures|meta|summary|html))+$"
                       r"|\.pdf$", re.I)
_TRAIL_PUNCT = ".,;:)]}'\""

_PUBMED = re.compile(r"^/(?:pubmed/)?(\d{1,9})/?$")
_PMC = re.compile(r"(?:^|/)pmc(\d{1,9})(?:/|$)", re.I)
_EPMC_MED = re.compile(r"^/(?:abstract|article)/med/(\d{1,9})/?$", re.I)
_ARXIV_NEW = re.compile(r"^/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(v\d+)?(?:\.pdf)?/?$", re.I)
_ARXIV_OLD = re.compile(r"^/(?:abs|pdf)/([a-z][a-z.-]+/\d{7})(v\d+)?(?:\.pdf)?/?$", re.I)
_BORIS_EPRINT = re.compile(r"^/(\d{1,9})(?:/|$)")
_BORIS_PORTAL = re.compile(r"^/(?:handle/(\d+(?:\.\d+)*/\d+)|entities/publication/([0-9a-f-]{36}))/?", re.I)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(href: str, base: str | None = None) -> str | None:
    """Absolute http(s) URL without fragment; scheme/host lowercased, default port dropped.
    Returns None for mailto:, tel:, javascript:, '#...', empty hrefs and anything not http(s)."""
    href = (href or "").strip()
    if not href or href.startswith("#"):  # in-page anchors are not links to another document
        return None
    u = urldefrag(urljoin(base, href) if base else href)[0]
    p = urlparse(u)
    scheme = p.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not p.hostname:
        return None
    host = p.hostname.lower()
    if p.port and p.port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{p.port}"
    return urlunparse((scheme, host, p.path or "/", p.params, p.query, ""))


def normalize_doi(raw: str) -> str | None:
    """'https://doi.org/10.1000/ABC.' / 'doi:10.1000/abc' / '10.1000%2Fabc' -> '10.1000/abc'."""
    s = unquote(raw or "").strip()
    m = _DOI.search(s)
    if not m:
        return None
    doi = m.group(1).rstrip(_TRAIL_PUNCT)
    # a trailing ")" is only punctuation when unbalanced: 10.1016/S0140-6736(20)30183-5 keeps its parens
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(_TRAIL_PUNCT)
    doi = _DOI_TAIL.sub("", doi).rstrip(_TRAIL_PUNCT)
    return doi.lower() if "/" in doi and doi.split("/", 1)[1] else None


def find_doi(text: str) -> str | None:
    """First DOI written in free text (anchor text such as 'doi: 10.1000/xyz')."""
    return normalize_doi(text) if text and "10." in text else None


def _doi_ref(doi: str) -> PaperRef:
    return PaperRef(scheme="doi", id=doi, url=f"https://doi.org/{doi}")


def paper_ref(url: str, text: str = "") -> PaperRef | None:
    """Classify an absolute URL (plus optional anchor text) as a scholarly reference, or None."""
    u = normalize_url(url)
    if u is None:
        # "doi:10.x/y" hrefs are not http(s) but are still DOIs
        doi = normalize_doi(url) if (url or "").strip().lower().startswith("doi:") else None
        return _doi_ref(doi) if doi else None
    p = urlparse(u)
    host = p.hostname or ""
    host = host.removeprefix("www.")
    path = unquote(p.path)

    if host in ("doi.org", "dx.doi.org"):
        doi = normalize_doi(path.lstrip("/"))
        return _doi_ref(doi) if doi else None
    if host in ("pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"):
        m = _PMC.search(path)
        if m and (host != "ncbi.nlm.nih.gov" or path.lower().startswith("/pmc/")):
            return _pmc_ref(m.group(1))
        sub = path[len("/pubmed"):] if host == "ncbi.nlm.nih.gov" and path.lower().startswith("/pubmed/") else \
            (path if host == "pubmed.ncbi.nlm.nih.gov" else "")
        m = _PUBMED.match(sub) if sub else None
        if m:
            return PaperRef(scheme="pubmed", id=m.group(1), url=f"https://pubmed.ncbi.nlm.nih.gov/{m.group(1)}/")
    if host == "pmc.ncbi.nlm.nih.gov" or host == "europepmc.org":
        m = _PMC.search(path)
        if m:
            return _pmc_ref(m.group(1))
        m = _EPMC_MED.match(path) if host == "europepmc.org" else None
        if m:
            return PaperRef(scheme="pubmed", id=m.group(1), url=f"https://pubmed.ncbi.nlm.nih.gov/{m.group(1)}/")
    if host in ("arxiv.org", "export.arxiv.org"):
        m = _ARXIV_NEW.match(path) or _ARXIV_OLD.match(path)
        if m:
            aid = m.group(1).lower()
            return PaperRef(scheme="arxiv", id=aid, url=f"https://arxiv.org/abs/{aid}")
    if host == "boris.unibe.ch":
        m = _BORIS_EPRINT.match(path)
        if m:
            return PaperRef(scheme="boris", id=m.group(1), url=f"https://boris.unibe.ch/{m.group(1)}/")
    if host == "boris-portal.unibe.ch":
        m = _BORIS_PORTAL.match(path)
        if m:
            bid = (m.group(1) or m.group(2)).lower()
            return PaperRef(scheme="boris", id=bid, url=u.split("?", 1)[0])

    # Publisher landing pages carry the DOI in the path (/doi/10.x/y, /article/10.x/y) or query (?doi=)
    doi = normalize_doi(path) or (normalize_doi(unquote(p.query)) if "10." in p.query else None) or find_doi(text)
    if doi:
        return _doi_ref(doi)
    if path.lower().endswith(".pdf"):
        clean = u.split("?", 1)[0]
        return PaperRef(scheme="pdf", id=clean, url=clean)
    return None


def _pmc_ref(num: str) -> PaperRef:
    pid = f"PMC{int(num)}"
    return PaperRef(scheme="pmc", id=pid, url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pid}/")
