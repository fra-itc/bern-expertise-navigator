"""Reading a company website from a pasted link (fake network, nothing is fetched)."""
import socket
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import api, cases, company, llm  # noqa: E402

HOME = """<html><head><title>Home | Acme Sensors</title><meta property="og:site_name" content="Acme Sensors">
<meta name="description" content="Acme Sensors builds a needle-free CGM patch for people with type 1 diabetes."></head>
<body><main><h1>Smart glucose sensing</h1><p>We make wearable sensors that measure blood sugar through the skin, without needles.</p>
<a href="/about-us/">About us</a> <a href="/technology">Our technology</a> <a href="/blog/post-1">Blog</a>
<a href="/products/secret">Products</a> <a href="https://other.com/about">Partner</a></main></body></html>"""
ABOUT = "<html><head><title>About</title></head><body><main><p>Founded in Munich in 2021 by two engineers, Acme Sensors now employs 40 people.</p></main></body></html>"
TECH = "<html><head><title>Technology</title></head><body><main><p>Our patch uses optical spectroscopy to estimate glucose levels every minute.</p></main></body></html>"


def _fake_dns(monkeypatch, table):
    def gai(host, port, *a, **k):
        literal = host.replace(".", "").isdigit()      # IP literals resolve to themselves
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host if literal else table.get(host, "93.184.216.34"), port))]
    monkeypatch.setattr(company.socket, "getaddrinfo", gai)


@pytest.fixture()
def site(monkeypatch):
    _fake_dns(monkeypatch, {"intranet.example": "10.0.0.5"})
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        html = {"/": HOME, "/about-us/": ABOUT, "/technology": TECH}.get(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /products/")
        if req.url.path == "/go-inside":
            return httpx.Response(302, headers={"location": "http://intranet.example/admin"})
        if html is None:
            return httpx.Response(404, text="no")
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(company, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(company, "DELAY", 0)
    return seen


def test_reads_home_and_key_pages(site):
    w = company.read("acme-sensors.example")          # no scheme: https is added
    assert w.name == "Acme Sensors" and "needle-free CGM" in w.description
    assert [p.title for p in w.pages] == ["Home | Acme Sensors", "Technology", "About"]
    assert "optical spectroscopy" in w.text and "Founded in Munich" in w.text
    assert "/blog/post-1" not in site                 # not a page about the company
    assert "/products/secret" not in site             # robots.txt disallows it
    assert not any("other.com" in p for p in site)    # other sites are never followed


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/", "http://localhost/", "http://intranet.example/",
                                 "http://db:5432/", "file:///etc/passwd", "https://acme.example:8443/"])
def test_refuses_internal_or_odd_addresses(site, monkeypatch, url):
    _fake_dns(monkeypatch, {"localhost": "127.0.0.1", "intranet.example": "10.0.0.5",
                            "db": "172.18.0.2"})
    with pytest.raises(company.FetchError):
        company.read(url)
    assert not [p for p in site if p != "/robots.txt"]


def test_redirect_into_private_network_is_refused(site):
    with pytest.raises(company.FetchError, match="private or internal"):
        company.read("https://acme-sensors.example/go-inside")


def test_new_case_from_link(site, tmp_path, monkeypatch):
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    from navigator import knowledge_access, published_pitch
    monkeypatch.setattr(knowledge_access, "member", lambda request: {"email": "officer@example.test", "role": "representative"})
    monkeypatch.setattr(published_pitch, "DB", tmp_path / "published.db")
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    queries = []
    monkeypatch.setattr(cases, "find_matches", lambda a, k=12: (queries.append(a.search_query) or [], None))
    client = TestClient(api.app)
    c = client.post("/cases", json={"company_url": "https://acme-sensors.example/", "need": "a clinical study partner",
                                    "actor": "Maria"}).json()
    assert c["company"] == "Acme Sensors" and c["website"]["url"] == "https://acme-sensors.example/"
    assert len(c["website"]["pages"]) == 3 and c["need"] == "a clinical study partner"
    a = c["analysis"]
    assert "needle-free CGM" in a["company_does"] and a["company_needs"] == ["a clinical study partner"]
    assert queries[0].startswith("a clinical study partner") and "continuous glucose monitoring" in queries[0]
    assert any(e["kind"] == "website" for e in c["events"])

    bad = client.post("/cases", json={"company_url": "http://127.0.0.1/", "actor": "Maria"})
    assert bad.status_code == 422 and "private or internal" in bad.json()["detail"]
    assert client.post("/cases", json={"actor": "Maria"}).status_code == 422
