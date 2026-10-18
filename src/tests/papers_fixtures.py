"""Shared fixtures for the papers tests: OpenAlex + PDF host behind httpx.MockTransport (no network),
a tiny generated PDF, and a mock LLM that answers from the prompt."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from navigator.schema import Entity, Evidence, Link, Page, PaperRef

FIX = Path(__file__).resolve().parent / "fixtures" / "openalex"
SCENARIO = json.loads((FIX / "bern_scenario.json").read_text(encoding="utf-8"))
TS = "2026-10-18T09:00:00+00:00"
URL = "https://www.example.unibe.ch/"
PDF_URL = "https://repo.example.org/w1001.pdf"


def make_pdf(text: str) -> bytes:
    """Minimal valid one-page PDF (Helvetica text), xref offsets computed: a real file pypdf can read."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF_TEXT = "Photoacoustic resonator calibration for transcutaneous glucose sensing"
PDF_BYTES = make_pdf(PDF_TEXT)


def openalex_handler(calls: list | None = None):
    def handle(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req)
        path = req.url.path
        q = {k: v[0] for k, v in parse_qs(urlparse(str(req.url)).query).items()}
        if path == "/institutions":
            return httpx.Response(200, json=SCENARIO["institutions"])
        if path == "/authors":
            return httpx.Response(200, json=SCENARIO["authors"].get(q.get("search", ""), {"meta": {}, "results": []}))
        if path == "/works":
            f = q.get("filter", "")
            if f.startswith("author.id:"):
                aid = f.split(",", 1)[0].split(":", 1)[1]
                return httpx.Response(200, json=SCENARIO["works_by_author"].get(aid, {"meta": {}, "results": []}))
            if f.startswith("doi:"):
                want = set(f[4:].split("|"))
                res = [w for w in SCENARIO["works_by_doi"]["results"] if w["doi"].removeprefix("https://doi.org/") in want]
                return httpx.Response(200, json={"meta": {"cost_usd": 0.0001}, "results": res})
            return httpx.Response(200, json={"meta": {}, "results": []})
        return httpx.Response(404, json={"error": "not found"})
    return handle


def pdf_handler(calls: list | None = None):
    def handle(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if req.url.path == "/w1001.pdf":
            return httpx.Response(200, content=PDF_BYTES, headers={"content-type": "application/pdf"})
        if req.url.path == "/private/x.pdf":
            return httpx.Response(200, content=PDF_BYTES, headers={"content-type": "application/pdf"})
        if req.url.path == "/html.pdf":
            return httpx.Response(200, text="<html>paywall</html>", headers={"content-type": "text/html"})
        if req.url.path == "/fake.pdf":
            return httpx.Response(200, content=b"<html>not a pdf</html>", headers={"content-type": "application/pdf"})
        if req.url.path == "/big.pdf":
            return httpx.Response(200, content=PDF_BYTES * 50, headers={"content-type": "application/pdf"})
        return httpx.Response(404)
    return handle


def ent(eid, name, etype, unit, expertise, url, source="artorg", role=None) -> Entity:
    ev = [Evidence(field="name", value=name, snippet=f"{name} works here.", url=url)]
    if unit:
        ev.append(Evidence(field="unit", value=unit, snippet=f"{name} is a member of {unit}.", url=url))
    ev += [Evidence(field="expertise", value=x, snippet=f"{name} researches {x}.", url=url) for x in expertise]
    return Entity(id=eid, entity_type=etype, name=name, role=role, unit=unit, expertise=list(expertise), source=source,
                  source_label=source.upper(), source_urls=[url], evidence=ev, retrieved_at=TS)


def corpus(hid=lambda i: f"{i:016x}") -> list[Entity]:
    return [
        ent(hid(1), "Jane Doe", "person", "Diabetes Technology Lab",
            ["continuous glucose monitoring", "closed-loop insulin delivery"], URL + "jane"),
        ent(hid(2), "Diabetes Technology Lab", "unit", None, ["continuous glucose monitoring"], URL + "dtl"),
        ent(hid(3), "Prof. Max Muster", "person", "Hearing Research Lab", ["cochlear implant"], URL + "max"),
        ent(hid(4), "Hearing Research Lab", "unit", None, ["cochlear implant", "audiology"], URL + "hrl"),
        ent(hid(5), "Ann A", "person", "Big Lab", ["medical image analysis"], URL + "ann"),
    ]


def pages(ents: list[Entity]) -> list[Page]:
    out = []
    for e in ents:
        text = "\n".join(ev.snippet for ev in e.evidence)
        links = []
        if e.name == "Hearing Research Lab":
            links = [Link(url="https://doi.org/10.1000/unitpaper", text="Hearing preservation outcomes", kind="paper",
                          paper_ref=PaperRef(scheme="doi", id="10.1000/unitpaper", url="https://doi.org/10.1000/unitpaper")),
                     Link(url="https://boris.unibe.ch/123/", text="BORIS", kind="paper",
                          paper_ref=PaperRef(scheme="boris", id="123", url="https://boris.unibe.ch/123/"))]
        out.append(Page(url=e.source_urls[0], source=e.source, title=e.name, text=text, fetched_at=TS,
                        page_type=e.entity_type, links=links))
    return out


class FakeLLM:
    """Stands in for llm.chat_json: picks the author by the person name in the prompt, maps topics to 'new'
    unless a rule says otherwise. Records every call."""

    def __init__(self, authors: dict[str, str] | None = None, topics: dict[str, str] | None = None):
        self.authors = authors if authors is not None else {"Jane Doe": "A100", "Prof. Max Muster": "A200"}
        self.topics = topics or {}
        self.calls: list[str] = []

    def __call__(self, messages, schema, **kw):
        prompt = messages[-1]["content"]
        self.calls.append(schema.__name__)
        if schema.__name__ == "_AuthorChoice":
            card = json.loads(prompt.split("\n")[1])
            return schema(choice=self.authors.get(card["name"], "none"), reason="same lab and topics")
        if schema.__name__ == "_TopicChoice":
            label = prompt.split('"')[1]
            return schema(choice=self.topics.get(label, "new"), reason="mock")
        raise AssertionError(schema)
