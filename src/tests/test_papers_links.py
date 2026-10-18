"""Outgoing links on crawled pages and recognition of scholarly references (offline, local HTML only)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import config, crawl  # noqa: E402
from navigator.config import Source  # noqa: E402
from navigator.crawl import HTMLParser, extract_links  # noqa: E402
from navigator.papers_links import normalize_doi, normalize_url, paper_ref  # noqa: E402
from navigator.schema import Page  # noqa: E402


def ref(url, text=""):
    r = paper_ref(url, text)
    return (r.scheme, r.id) if r else None


# ---- DOI -------------------------------------------------------------------
@pytest.mark.parametrize("url,doi", [
    ("https://doi.org/10.1000/XYZ123", "10.1000/xyz123"),
    ("http://dx.doi.org/10.1007/s00134-020-06294-x", "10.1007/s00134-020-06294-x"),
    ("https://doi.org/10.1016/S0140-6736(20)30183-5", "10.1016/s0140-6736(20)30183-5"),
    ("https://doi.org/10.1000%2Fabc.def", "10.1000/abc.def"),
    ("https://onlinelibrary.wiley.com/doi/full/10.1002/mrm.28000", "10.1002/mrm.28000"),
    ("https://www.tandfonline.com/doi/pdf/10.1080/1234.5678?needAccess=true", "10.1080/1234.5678"),
    ("https://link.springer.com/article/10.1007/s11548-021-02345-6", "10.1007/s11548-021-02345-6"),
    ("https://journals.example.org/view?doi=10.3389/fphys.2021.00123", "10.3389/fphys.2021.00123"),
])
def test_doi_urls(url, doi):
    r = paper_ref(url)
    assert (r.scheme, r.id, r.url) == ("doi", doi, f"https://doi.org/{doi}")


def test_doi_normalisation_from_text_and_prefixes():
    assert normalize_doi("doi:10.1000/ABC.") == "10.1000/abc"
    assert normalize_doi("(see 10.1000/abc).") == "10.1000/abc"
    assert ref("doi:10.5555/X-1") == ("doi", "10.5555/x-1")
    # Anchor text carries the DOI while the href points to a generic publisher page
    assert ref("https://publisher.example.com/article/view/77", "doi: 10.1234/jmb.2020.5") == ("doi", "10.1234/jmb.2020.5")


# ---- PubMed / PMC / arXiv / BORIS / PDF -------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://pubmed.ncbi.nlm.nih.gov/33301246/", ("pubmed", "33301246")),
    ("https://www.ncbi.nlm.nih.gov/pubmed/12345678", ("pubmed", "12345678")),
    ("https://europepmc.org/article/MED/31234567", ("pubmed", "31234567")),
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7654321/", ("pmc", "PMC7654321")),
    ("https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/", ("pmc", "PMC123456")),
    ("https://europepmc.org/article/PMC/PMC99887", ("pmc", "PMC99887")),
    ("https://arxiv.org/abs/2101.00001v2", ("arxiv", "2101.00001")),
    ("https://arxiv.org/pdf/2312.12345.pdf", ("arxiv", "2312.12345")),
    ("https://arxiv.org/abs/hep-th/9901001", ("arxiv", "hep-th/9901001")),
    ("https://boris.unibe.ch/154321/", ("boris", "154321")),
    ("https://boris.unibe.ch/154321/1/paper.pdf", ("boris", "154321")),
    ("https://boris-portal.unibe.ch/handle/20.500.12422/187654", ("boris", "20.500.12422/187654")),
    ("https://boris-portal.unibe.ch/entities/publication/1b2c3d4e-0000-4abc-8def-1234567890ab",
     ("boris", "1b2c3d4e-0000-4abc-8def-1234567890ab")),
    ("https://www.artorg.unibe.ch/unibe/portal/content/e1/annual_report.pdf",
     ("pdf", "https://www.artorg.unibe.ch/unibe/portal/content/e1/annual_report.pdf")),
    ("https://example.org/files/Report.PDF?download=1", ("pdf", "https://example.org/files/Report.PDF")),
])
def test_schemes(url, expected):
    assert ref(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.artorg.unibe.ch/research/index_eng.html",
    "https://example.org/release/v10.2023/notes",          # version string, not a DOI boundary
    "https://example.org/10.12/abc",                        # registrant too short
    "https://example.org/10.12345",                         # no suffix
    "http://10.1234.5.6/index.html",                        # IP-ish host
    "https://pubmed.ncbi.nlm.nih.gov/?term=cancer",          # search page
    "https://www.ncbi.nlm.nih.gov/gene/672",                 # other NCBI db
    "https://arxiv.org/list/cs.LG/recent",
    "https://boris.unibe.ch/view/divisions/",
    "https://boris-portal.unibe.ch/search?query=heart",
    "https://example.org/pdf-guide.html",
    "https://example.org/file.pdf.html",
    "mailto:someone@unibe.ch",
    "",
])
def test_false_positives(url):
    assert paper_ref(url) is None


def test_normalize_url():
    assert normalize_url("../a/b.html#top", "https://WWW.Example.ORG:443/x/y/") == "https://www.example.org/x/a/b.html"
    assert normalize_url("http://h.ch:8080") == "http://h.ch:8080/"
    for bad in ("mailto:a@b.ch", "tel:+41", "javascript:void(0)", "#", "ftp://h/x"):
        assert normalize_url(bad, "https://h.ch/") is None


# ---- Link extraction on a local fixture -------------------------------------
FIXTURE = """<html lang="en"><head><title>Group</title></head><body>
<nav><a href="/">Home</a></nav>
<main>
  <p>We work on cochlear implants.</p>
  <a href="/research/hearing/index_eng.html">Hearing <b>Research</b></a>
  <a href="/research/hearing/index_eng.html#team"></a>
  <a href="https://www.insel.ch/en/">Inselspital</a>
  <a href="https://doi.org/10.1000/ABC.1">Paper A</a>
  <a href="https://dx.doi.org/10.1000/abc.1">Paper A again</a>
  <a href="https://pubmed.ncbi.nlm.nih.gov/33301246/">PubMed</a>
  <a href="https://boris.unibe.ch/154321/">BORIS record</a>
  <a href="/files/poster.pdf">Poster</a>
  <a href="doi:10.5555/xyz">doi link</a>
  <a href="mailto:x@unibe.ch">Mail</a>
  <a href="javascript:void(0)">JS</a>
</main></body></html>"""

SRC = Source(name="t", label="T", domains=["artorg.unibe.ch"], seeds=[], max_pages=1, max_depth=1,
             delay_seconds=0, user_agent="x", priority_keywords=[], skip_keywords=[])


def test_extract_links_kinds_dedup_and_text():
    links = extract_links(HTMLParser(FIXTURE), "https://www.artorg.unibe.ch/research/x/index_eng.html", SRC.allows)
    by = {l.url: l for l in links}
    assert by["https://www.artorg.unibe.ch/"].kind == "internal"
    hr = by["https://www.artorg.unibe.ch/research/hearing/index_eng.html"]
    assert hr.kind == "internal" and hr.text == "Hearing Research"  # fragment variant deduplicated
    assert by["https://www.insel.ch/en/"].kind == "external"
    papers = [(l.paper_ref.scheme, l.paper_ref.id) for l in links if l.kind == "paper"]
    # the two DOI hrefs differ as URLs, so both are kept, each with the same normalised DOI
    assert papers.count(("doi", "10.1000/abc.1")) == 2
    assert ("pubmed", "33301246") in papers and ("boris", "154321") in papers
    assert ("pdf", "https://www.artorg.unibe.ch/files/poster.pdf") in papers
    assert by["https://doi.org/10.5555/xyz"].paper_ref.id == "10.5555/xyz"
    assert not any(l.url.startswith(("mailto", "javascript")) for l in links)
    assert len(links) == len({l.url for l in links})


def test_extract_links_cap(monkeypatch):
    monkeypatch.setattr(crawl, "MAX_OTHER_LINKS", 5)
    html = "<body>" + "".join(f'<a href="/p{i}">p{i}</a>' for i in range(50)) + \
           '<a href="https://doi.org/10.1000/z">z</a></body>'
    links = extract_links(HTMLParser(html), "https://www.artorg.unibe.ch/", SRC.allows)
    assert sum(l.kind == "internal" for l in links) == 5
    assert sum(l.kind == "paper" for l in links) == 1  # papers are capped separately, never crowded out


# ---- Backward compatibility + skip rules + data dir ----------------------------
def test_old_jsonl_without_links_loads(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    old = {"url": "https://a.ch/x", "source": "old", "title": "X", "text": "t" * 200,
           "fetched_at": "2026-01-01T00:00:00+00:00", "lang": "de", "page_type": None}
    (tmp_path / "pages" / "old.jsonl").write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    pages = crawl.load_pages("old")
    assert len(pages) == 1 and pages[0].links == []
    # and a page with links round-trips
    p = Page.model_validate_json(Page(**old, links=extract_links(HTMLParser(FIXTURE), "https://a.ch/", SRC.allows))
                                 .model_dump_json())
    assert any(l.kind == "paper" for l in p.links)


def test_skip_uses_existing_skip_keywords():
    s = Source(name="t", label="T", domains=["unibe.ch"], seeds=[], max_pages=1, max_depth=1, delay_seconds=0,
               user_agent="x", priority_keywords=[], skip_keywords=["/news/", "/events/", "login"])
    assert crawl._skip("https://www.unibe.ch/news/2026/x.html", s)
    assert crawl._skip("https://www.unibe.ch/x/login", s)
    assert crawl._skip("https://other.ch/a", s)  # off-domain
    assert not crawl._skip("https://www.unibe.ch/research/index_eng.html", s)


def test_crawl_writes_to_data_dir_and_skips_papers(tmp_path, monkeypatch):
    """Whole crawl loop against an in-memory site: output lands in DATA_DIR, links saved, paper links not fetched."""
    import httpx

    site = {
        "https://www.artorg.unibe.ch/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
        "https://www.artorg.unibe.ch/": (200, "text/html", FIXTURE.replace("cochlear", "cochlear " + "x " * 100)),
    }
    fetched = []

    def handler(req):
        fetched.append(str(req.url))
        code, ctype, body = site.get(str(req.url), (404, "text/html", ""))
        return httpx.Response(code, headers={"content-type": ctype}, text=body)

    real = httpx.Client
    monkeypatch.setattr(crawl.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    src = Source(name="fx", label="FX", domains=["artorg.unibe.ch"], seeds=["https://www.artorg.unibe.ch/"],
                 max_pages=10, max_depth=2, delay_seconds=0, user_agent="x", priority_keywords=[],
                 skip_keywords=["/research/"])
    pages = crawl.crawl(src)
    out = tmp_path / "pages" / "fx.jsonl"
    assert out.exists() and not (tmp_path / "pages" / "fx.jsonl.partial").exists()
    assert len(pages) == 1 and any(l.kind == "paper" for l in pages[0].links)
    assert crawl.load_pages("fx")[0].links == pages[0].links
    assert not any(u.endswith(".pdf") or "doi.org" in u or "boris" in u or "pubmed" in u for u in fetched)
    assert not any("/research/" in u for u in fetched)  # skip_keywords honoured


def test_seeds_file_resolves_in_alternative_config_dir(tmp_path, monkeypatch):
    (tmp_path / "hosts.txt").write_text("# hosts\nfoo.unibe.ch\n", encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  - {name: u, seeds_file: config/hosts.txt, domains_from_seeds: true}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    (u,) = config.load_sources("u")
    assert u.seeds == ["https://foo.unibe.ch/"] and "foo.unibe.ch" in u.domains
