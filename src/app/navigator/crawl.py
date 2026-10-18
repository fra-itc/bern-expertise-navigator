"""Stage 1 — polite, bounded, config-driven crawler (robots.txt aware)."""
from __future__ import annotations

import hashlib
import heapq
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urldefrag, urlparse

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import config
from .config import Source
from .papers_links import normalize_url, paper_ref
from .schema import Link, Page


_BOILER = re.compile(r"(^|[\s_-])(nav|navbar|navigation|menu|footer|header|cookie|breadcrumb|sidebar|social|share|"
                     r"skip|search|lang|language|topbar|meta-nav|servicenav)([\s_-]|$)", re.I)


def dom_text(html: str) -> str:
    """Visible text minus navigation/boilerplate, one line per block.

    trafilatura is tuned for articles and drops directory-style pages (team grids, member cards),
    which are exactly the pages that list experts.
    """
    t = HTMLParser(html)
    for n in t.css("script,style,noscript,svg,nav,header,footer,aside,form,iframe,template"):
        n.decompose()
    for n in t.css("[id],[class],[role]"):
        a = n.attributes
        key = " ".join(filter(None, [a.get("id"), a.get("class"), a.get("role")]))
        if n.tag not in ("body", "html", "main") and _BOILER.search(key):
            n.decompose()
    root = t.css_first("main") or t.body
    if root is None:
        return ""
    out: list[str] = []
    for line in root.text(separator="\n").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


# Teaser blocks for OTHER pages ("More recent projects", "Related posts") would attach their
# people and topics to this page; everything after such a marker is dropped.
_RELATED = re.compile(r"^(more recent (projects|news|posts)|related (posts|projects|articles|news)|recent (posts|projects)|"
                      r"you (may|might) also like|weitere (projekte|beiträge|news)|ähnliche beiträge|"
                      r"autres projets|articles similaires)\s*:?$", re.I | re.M)


def page_text(html: str) -> str:
    art = trafilatura.extract(html, include_tables=True, favor_recall=True) or ""
    dom = dom_text(html)
    text = dom if len(dom) > 1.3 * len(art) else art
    m = _RELATED.search(text)
    return text[: m.start()].rstrip() if m and m.start() > 200 else text


def _priority(url: str, depth: int, src: Source) -> int:
    path = url.lower()
    bonus = -10 if any(k in path for k in src.priority_keywords) else 0
    return depth * 10 + bonus


class RobotRules:
    """robots.txt with Google-style wildcards ('*', '$'), longest-match wins.

    The stdlib RobotFileParser ignores wildcards, and UniBE sites rely on them
    (e.g. 'Disallow: /*index.html').
    """

    def __init__(self, text: str, ua: str):
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if rules:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(v.lower())
            elif k in ("allow", "disallow") and agents:
                if v:
                    rules.append((k == "allow", v))
        if agents:
            groups.append((agents, rules))
        ua = ua.lower()
        specific = [r for a, r in groups if any(x != "*" and x in ua for x in a)]
        self.rules = [x for r in (specific or [r for a, r in groups if "*" in a]) for x in r]

    @staticmethod
    def _match(pattern: str, path: str) -> bool:
        rx = re.escape(pattern).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        return re.match(rx, path) is not None

    def can_fetch(self, url: str) -> bool:
        p = urlparse(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best: tuple[int, bool] = (-1, True)
        for allow, pat in self.rules:
            if self._match(pat, path) and (len(pat) > best[0] or (len(pat) == best[0] and allow)):
                best = (len(pat), allow)
        return best[1]


class _Robots:
    def __init__(self, ua: str, client: httpx.Client):
        self.ua, self.client, self.cache = ua, client, {}

    def ok(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            try:
                r = self.client.get(base + "/robots.txt", timeout=10)
                text = r.text if r.status_code == 200 else ""
            except httpx.HTTPError:
                text = ""
            self.cache[base] = RobotRules(text, self.ua)
        return self.cache[base].can_fetch(url)


# Date / pagination archives (WordPress etc.) only repeat content found elsewhere
_ARCHIVE = re.compile(r"/(19|20)\d\d/(\d\d/)?$|/page/\d+/?$")


def url_key(url: str) -> str:
    """Dedup key: no fragment, no scheme/www difference, no trailing slash."""
    u = urldefrag(url)[0]
    p = urlparse(u)
    host = (p.hostname or "").lower().removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")


# Per-page caps keep the JSONL bounded on link-farm pages (sitemaps, A-Z lists, publication lists).
MAX_PAPER_LINKS = 500
MAX_OTHER_LINKS = 300


def extract_links(tree: HTMLParser, base_url: str, is_internal) -> list[Link]:
    """Outgoing links of a page, read from the raw DOM (before any text extraction strips it).

    Absolute + normalised, deduplicated per page (first non-empty anchor text wins), classified as
    paper (see papers_links), internal (`is_internal(url)`, i.e. the source's domains) or external.
    """
    by_url: dict[str, Link] = {}
    n_paper = n_other = 0
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        url = normalize_url(href, base_url)
        text = re.sub(r"\s+", " ", a.text(separator=" ") or "").strip()[:300]
        ref = paper_ref(url, text) if url else (paper_ref(href) if href.lower().startswith("doi:") else None)
        if url is None and ref is not None:
            url = ref.url
        if url is None:
            continue
        if url in by_url:
            if text and not by_url[url].text:
                by_url[url].text = text
            continue
        if ref is not None:
            if n_paper >= MAX_PAPER_LINKS:
                continue
            n_paper += 1
            kind = "paper"
        else:
            if n_other >= MAX_OTHER_LINKS:
                continue
            n_other += 1
            kind = "internal" if is_internal(url) else "external"
        by_url[url] = Link(url=url, text=text, kind=kind, paper_ref=ref)
    return list(by_url.values())


def _skip(url: str, src: Source) -> bool:
    return (not src.allows(url) or any(k in url.lower() for k in src.skip_keywords)
            or _ARCHIVE.search(url) is not None)


def crawl(src: Source) -> list[Page]:
    out_path = config.DATA_DIR / "pages" / f"{src.name}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Written to a side file and swapped in at the end: an interrupted re-crawl keeps the old pages.
    tmp_path = out_path.with_name(out_path.name + ".partial")
    seen: set[str] = set()
    content_hashes: set[str] = set()
    queue: list[tuple[int, int, int, str]] = []
    counter = 0  # FIFO tie-break among equal priorities
    for s in src.seeds:
        heapq.heappush(queue, (0, 0, counter, s))
        counter += 1
    pages: list[Page] = []
    skipped_robots = 0

    with httpx.Client(headers={"User-Agent": src.user_agent}, follow_redirects=True, timeout=20) as client, \
            tmp_path.open("w", encoding="utf-8") as fh:
        robots = _Robots(src.user_agent, client)
        while queue and len(pages) < src.max_pages:
            _, depth, _, url = heapq.heappop(queue)
            url = urldefrag(url)[0]
            key = url_key(url)
            if key in seen or _skip(url, src):
                continue
            seen.add(key)
            if not robots.ok(url):
                skipped_robots += 1
                continue
            try:
                r = client.get(url)
            except httpx.HTTPError:
                continue
            final = str(r.url)
            seen.add(url_key(final))
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
            if not src.allows(final):  # redirected off-domain
                continue
            html = r.text
            text = page_text(html)
            tree = HTMLParser(html)
            title = (tree.css_first("title").text(strip=True) if tree.css_first("title") else "")
            links = extract_links(tree, final, src.allows)
            digest = hashlib.sha1(text.encode()).hexdigest()
            if len(text) > 150 and digest not in content_hashes:
                content_hashes.add(digest)
                lang = (tree.css_first("html").attributes.get("lang") or "")[:2] if tree.css_first("html") else ""
                page = Page(url=final, source=src.name, title=title, text=text, lang=lang or None,
                            fetched_at=datetime.now(timezone.utc).isoformat(), links=links)
                pages.append(page)
                fh.write(page.model_dump_json() + "\n")
                fh.flush()
                if len(pages) % 25 == 0:
                    print(f"[crawl] {src.name}: {len(pages)} pages (queue {len(queue)})")
            if depth < src.max_depth:
                for a in tree.css("a[href]"):
                    nxt = urldefrag(urljoin(final, a.attributes.get("href") or ""))[0]
                    # Paper links (DOI, PubMed, BORIS records, PDFs, ...) are recorded on the page, never fetched
                    if nxt.startswith("http") and url_key(nxt) not in seen and src.allows(nxt) \
                            and paper_ref(nxt) is None:
                        heapq.heappush(queue, (_priority(nxt, depth + 1, src), depth + 1, counter, nxt))
                        counter += 1
            time.sleep(src.delay_seconds)
    tmp_path.replace(out_path)
    n_links = sum(len(p.links) for p in pages)
    n_paper = sum(1 for p in pages for x in p.links if x.kind == "paper")
    print(f"[crawl] {src.name}: {len(pages)} pages -> {out_path} ({skipped_robots} URLs disallowed by robots.txt; "
          f"{n_links} links recorded, {n_paper} to papers)")
    return pages


def load_pages(source: str | None = None) -> list[Page]:
    files = sorted((config.DATA_DIR / "pages").glob(f"{source or '*'}.jsonl"))
    return [Page.model_validate_json(l) for f in files for l in f.open(encoding="utf-8") if l.strip()]


def dump_jsonl(items, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write((it.model_dump_json() if hasattr(it, "model_dump_json") else json.dumps(it)) + "\n")
