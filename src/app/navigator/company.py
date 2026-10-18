"""Read a company's own website when the officer pastes its link (step 1 of a request).

Polite and bounded: the pasted page plus at most MAX_EXTRA pages on the same site whose links look
like "about / products / technology", robots.txt respected, one request at a time.

The server is public, so the URL is untrusted input: only http(s) on ports 80/443, and every host
(including each redirect hop) must resolve to a public address — never localhost, the Docker
network or the database.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .crawl import RobotRules, page_text, url_key

USER_AGENT = "BernExpertiseNavigator/0.2 (+https://bern-expertise.ch; reads one company site on request)"
MAX_EXTRA = 5
MAX_BYTES = 2_000_000
MAX_TEXT = 20_000          # what is kept and analysed, across all pages
DELAY = 0.5
_transport: httpx.BaseTransport | None = None   # tests swap in a fake network

# Pages that describe the company, in EN/DE/FR
_KEY = re.compile(r"about|company|who-we-are|mission|product|solution|technolog|platform|science|research|"
                  r"innovation|pipeline|ueber-uns|uber-uns|unternehmen|firma|produkt|loesung|losung|technologie|"
                  r"forschung|a-propos|entreprise|societe|produit|technologie|recherche", re.I)
_SKIP = re.compile(r"news|blog|press|career|job|event|login|cart|shop|privacy|datenschutz|imprint|impressum|"
                   r"cookie|legal|terms|contact|kontakt|\.(pdf|jpg|jpeg|png|svg|zip)$", re.I)


class FetchError(ValueError):
    """Shown to the officer as is: say what went wrong and that pasting the text works too."""


class WebPage(BaseModel):
    url: str
    title: str = ""


class CompanyWebsite(BaseModel):
    url: str
    name: str = ""
    description: str = ""          # the site's own meta description, if any
    pages: list[WebPage] = []
    text: str = ""


def normalise(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    return urldefrag(url)[0]


def _check_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchError("Please enter a web address starting with http:// or https://.")
    if p.port not in (None, 80, 443) or p.username or p.password:
        raise FetchError("This web address is not supported (unusual port or login in the link).")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError(f"The website {p.hostname} could not be found. Check the link for typos.") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError("This address points to a private or internal network and cannot be read.")


class _Resp(BaseModel):
    status: int
    ctype: str
    url: str
    text: str


def _get(client: httpx.Client, url: str) -> _Resp:
    """GET with manual redirects so every hop is checked; body capped at MAX_BYTES."""
    for _ in range(6):
        _check_public(url)
        with client.stream("GET", url) as r:
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            return _Resp(status=r.status_code, ctype=r.headers.get("content-type", ""), url=url,
                         text=body.decode(r.encoding or "utf-8", errors="replace"))
    raise FetchError("The website redirected too many times.")


def _meta(tree: HTMLParser, *names: str) -> str:
    for n in names:
        el = tree.css_first(f'meta[property="{n}"]') or tree.css_first(f'meta[name="{n}"]')
        if el and (el.attributes.get("content") or "").strip():
            return " ".join(el.attributes["content"].split())
    return ""


def _name(tree: HTMLParser, host: str) -> str:
    site = _meta(tree, "og:site_name", "application-name")
    if site:
        return site
    title = tree.css_first("title").text(strip=True) if tree.css_first("title") else ""
    parts = [x.strip() for x in re.split(r"\s+[|–—·-]\s+", title) if x.strip()]
    if parts:
        # "Home | Acme Medical" / "Acme Medical – Smart sensors": the shortest part is usually the brand
        return min(parts, key=len) if len(parts) > 1 else parts[0]
    return host.removeprefix("www.").split(".")[0].capitalize()


def _key_links(tree: HTMLParser, page_url: str) -> list[str]:
    host = (urlparse(page_url).hostname or "").removeprefix("www.")
    tag = tree.css_first("base[href]")       # relative links resolve against <base href> when the page sets one
    base = urljoin(page_url, tag.attributes.get("href") or "") if tag else page_url
    seen, out = {url_key(page_url)}, []
    for a in tree.css("a[href]"):
        u = urldefrag(urljoin(base, a.attributes.get("href") or ""))[0]
        p = urlparse(u)
        if p.scheme not in ("http", "https") or (p.hostname or "").removeprefix("www.") != host:
            continue
        path = p.path.lower()
        if url_key(u) in seen or _SKIP.search(path) or not _KEY.search(path + " " + a.text(strip=True).lower()):
            continue
        seen.add(url_key(u))
        out.append(u)
    # shallow pages first: /about before /about/team/history
    return sorted(out, key=lambda u: urlparse(u).path.count("/"))[:MAX_EXTRA]


def read(url: str) -> CompanyWebsite:
    url = normalise(url)
    _check_public(url)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=False, timeout=12, transport=_transport) as client:
        p = urlparse(url)
        try:
            rb = _get(client, f"{p.scheme}://{p.netloc}/robots.txt")
            robots = RobotRules(rb.text if rb.status == 200 else "", USER_AGENT)
        except (httpx.HTTPError, FetchError):
            robots = RobotRules("", USER_AGENT)
        if not robots.can_fetch(url):
            raise FetchError("This website asks automated tools not to read this page (robots.txt). "
                             "Please paste a description of the company instead.")
        try:
            r = _get(client, url)
        except httpx.HTTPError as e:
            raise FetchError(f"The website could not be reached ({type(e).__name__}). "
                             "Please try again or paste a description of the company.") from None
        if r.status != 200 or "html" not in r.ctype:
            raise FetchError(f"The website answered with an error (HTTP {r.status}). "
                             "Please check the link or paste a description of the company.")
        final = r.url
        tree = HTMLParser(r.text)
        site = CompanyWebsite(url=final, name=_name(tree, urlparse(final).hostname or ""),
                              description=_meta(tree, "og:description", "description"))
        texts: list[str] = []

        def add(u: str, html: str, t: HTMLParser) -> None:
            title = t.css_first("title").text(strip=True) if t.css_first("title") else ""
            text = page_text(html).strip()
            if text and text not in texts:
                texts.append(text)
                site.pages.append(WebPage(url=u, title=title))

        add(final, r.text, tree)
        for link in _key_links(tree, final):
            if sum(map(len, texts)) >= MAX_TEXT or not robots.can_fetch(link):
                continue
            time.sleep(DELAY)
            try:
                x = _get(client, link)
            except (httpx.HTTPError, FetchError):
                continue
            if x.status == 200 and "html" in x.ctype:
                add(x.url, x.text, HTMLParser(x.text))
    site.text = "\n\n".join(texts)[:MAX_TEXT]
    if len(site.text) < 80 and not site.description:
        raise FetchError("The website has almost no readable text (it may need JavaScript). "
                         "Please paste a description of the company instead.")
    return site
