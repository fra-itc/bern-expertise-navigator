"""Papers pipeline without network, DB or model: OpenAlex behind MockTransport (recorded + scenario JSON),
generated PDF, mock LLM."""
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from navigator import llm, papers  # noqa: E402
from navigator.config import settings  # noqa: E402
from navigator.openalex_client import OpenAlexClient, OpenAlexError, candidate_summary, parse_work, reconstruct_abstract  # noqa: E402
from papers_fixtures import (FIX, PDF_BYTES, PDF_TEXT, PDF_URL, SCENARIO, FakeLLM, corpus,  # noqa: E402
                             openalex_handler, pages, pdf_handler)

BERN = {"I118564535", "I2801112126"}


def client(tmp_path, handler=None, **kw) -> OpenAlexClient:
    kw.setdefault("sleep", lambda s: None)
    return OpenAlexClient(base_url="https://api.openalex.test", mailto="", api_key="", rps=1000,
                          cache_dir=tmp_path / "cache", transport=httpx.MockTransport(handler or openalex_handler()), **kw)


def fetcher(tmp_path, handler=None, **kw) -> papers.PdfFetcher:
    http = httpx.Client(transport=httpx.MockTransport(handler or pdf_handler()), follow_redirects=True)
    return papers.PdfFetcher(tmp_path / "pdf", client=http, delay=0, sleep=lambda s: None, **kw)


# ---------------- parsing ---------------------------------------------------------------
def test_reconstruct_abstract_orders_words_by_position():
    assert reconstruct_abstract({"world": [1], "hello": [0, 2]}) == "hello world hello"
    assert reconstruct_abstract(None) is None and reconstruct_abstract({}) is None


def test_parse_recorded_work():
    raw = json.loads((FIX / "recorded_work_W2741809807.json").read_text(encoding="utf-8"))
    w = parse_work(raw, "2026-10-18T00:00:00+00:00")
    assert w.id == "W2741809807" and w.doi == "10.7717/peerj.4375" and w.year == 2018
    assert w.title.startswith("The state of OA") and w.venue == "PeerJ"
    assert w.abstract.startswith("Despite growing interest in Open Access")
    assert [a.position for a in w.authors] == list(range(len(w.authors)))
    assert w.authors[0].author_id == "A5048491430" and w.authors[0].author_position == "first"
    assert all(r.startswith("W") for r in w.referenced_works) and len(w.referenced_works) == 47
    assert w.is_oa and w.oa_status == "gold" and w.pmid == "29456894"
    assert w.topics[0]["id"].startswith("T") and w.url() == "https://doi.org/10.7717/peerj.4375"


def test_pdf_urls_only_from_open_access_locations():
    raw = SCENARIO["works_by_author"]["A100"]["results"]
    oa, closed = parse_work(raw[0], "t"), parse_work(raw[1], "t")
    assert oa.pdf_urls == [PDF_URL] and closed.pdf_urls == [] and not closed.is_oa
    raw_closed_with_pdf = {**raw[1], "locations": [{"is_oa": False, "pdf_url": "https://publisher.example/x.pdf"}]}
    assert parse_work(raw_closed_with_pdf, "t").pdf_urls == []


def test_candidate_summary_flags_bern_through_lineage():
    jane = SCENARIO["authors"]["jane doe"]["results"]
    c = candidate_summary(jane[0], BERN)
    assert c["id"] == "A100" and c["bern"] and c["affiliations"][0]["years"] == "2019-2024"
    rec = json.loads((FIX / "recorded_author_A5048491430.json").read_text(encoding="utf-8"))
    assert not candidate_summary(rec, BERN)["bern"]


# ---------------- client: cache, retry, breaker, credentials --------------------------------
def test_client_caches_and_keeps_key_out_of_url(tmp_path):
    calls = []
    c = OpenAlexClient(base_url="https://api.openalex.test", mailto="ops@example.org", api_key="SECRET", rps=1000,
                       cache_dir=tmp_path, transport=httpx.MockTransport(openalex_handler(calls)), sleep=lambda s: None)
    a = c.search_authors("jane doe", ["I118564535"])
    b = c.search_authors("jane doe", ["I118564535"])
    assert a == b and len(calls) == 1 and c.usage["cache_hits"] == 1
    assert calls[0].headers["authorization"] == "Bearer SECRET" and "SECRET" not in str(calls[0].url)
    assert "mailto=ops%40example.org" in str(calls[0].url)
    assert all("SECRET" not in p.read_text() for p in tmp_path.glob("*.json"))
    assert c.usage["cost_usd"] == pytest.approx(0.001)


def test_client_retries_429_then_succeeds(tmp_path):
    n = {"i": 0}
    slept = []

    def h(req):
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="slow down")
        return openalex_handler()(req)
    c = client(tmp_path, h, sleep=slept.append)
    assert c.institutions_by_ror(["https://ror.org/02k7v4d05"])
    assert n["i"] == 3 and c.usage["retries"] == 2 and 2.0 in slept


def test_client_circuit_breaker_fails_fast(tmp_path):
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(503)
    c = client(tmp_path, h, max_retries=1, breaker_threshold=2, breaker_cooldown=60)
    with pytest.raises(OpenAlexError) as e1:
        c.get("/works", {"filter": "doi:x"})
    assert e1.value.code == "http_503"
    with pytest.raises(OpenAlexError) as e2:
        c.get("/works", {"filter": "doi:y"})
    assert e2.value.code == "circuit_open" and n["i"] == 2


def test_client_404_is_structured(tmp_path):
    with pytest.raises(OpenAlexError) as e:
        client(tmp_path).work("doi:10.1/none")
    assert e.value.code == "not_found"


# ---------------- disambiguation --------------------------------------------------------------
def _cands(name):
    return [candidate_summary(a, BERN) for a in SCENARIO["authors"][name]["results"]]


def test_llm_choice_is_validated_against_whitelist(monkeypatch):
    e = corpus()[0]
    monkeypatch.setattr(llm, "chat_json", FakeLLM())
    m = papers.choose_author(e, _cands("jane doe"), use_llm=True)
    assert (m.chosen_author_id, m.decided_by) == ("A100", "llm") and m.model == settings.llm_model
    monkeypatch.setattr(llm, "chat_json", FakeLLM(authors={"Jane Doe": "A5048491430"}))  # real id, not offered
    m = papers.choose_author(e, _cands("jane doe"), use_llm=True)
    assert m.chosen_author_id is None and "not among candidates" in m.reason
    monkeypatch.setattr(llm, "chat_json", FakeLLM(authors={}))
    assert papers.choose_author(e, _cands("jane doe"), use_llm=True).chosen_author_id is None


def test_rules_fallback_is_conservative(monkeypatch):
    def down(*a, **k):
        raise llm.LLMError("connection refused")
    monkeypatch.setattr(llm, "chat_json", down)
    jane, _, maxm = corpus()[0], None, corpus()[2]
    # two Bern-affiliated "Jane Doe" profiles (A100, A101): ambiguous -> no match
    m = papers.choose_author(jane, _cands("jane doe"), use_llm=True)
    assert m.decided_by == "rules" and m.chosen_author_id is None and "ambiguous" in m.reason
    assert "LLM unavailable" in m.reason
    # unique Bern candidate with the identical normalised name ("Prof. Max Muster" == "Max Muster") -> match
    m = papers.choose_author(maxm, _cands("max muster"), use_llm=True)
    assert (m.chosen_author_id, m.decided_by) == ("A200", "rules")
    # same name but no Bern affiliation -> no match
    nb = [{**c, "bern": False} for c in _cands("max muster")]
    assert papers.choose_author(maxm, nb, use_llm=False).chosen_author_id is None
    assert papers.choose_author(maxm, [], use_llm=True).reason.startswith("no Bern")


# ---------------- chunking -------------------------------------------------------------------
def test_chunk_words_windows_overlap_and_cap():
    text = " ".join(f"w{i}" for i in range(1000))
    ch = papers.chunk_words(text, size=300, overlap=50, max_chunks=8)
    assert [len(c.split()) for c in ch] == [300, 300, 300, 250]
    assert ch[0].split()[-50:] == ch[1].split()[:50]
    assert len(papers.chunk_words(text, size=100, overlap=20, max_chunks=3)) == 3
    assert papers.chunk_words("short text", size=300, overlap=50) == ["short text"]
    assert papers.chunk_words("", size=300, overlap=50) == []
    with pytest.raises(ValueError):
        papers.chunk_words(text, size=50, overlap=50)


# ---------------- PDF download with limits ---------------------------------------------------------
def test_pdf_fetch_ok_and_text_extracted(tmp_path):
    f = fetcher(tmp_path)
    r = f.fetch(PDF_URL)
    assert r.status == "ok" and r.path.read_bytes() == PDF_BYTES and r.path.name == f"{r.sha1}.pdf"
    assert PDF_TEXT in papers.pdf_text(r.path)
    assert f.fetch(PDF_URL).status == "ok"  # kept on disk: no second download


@pytest.mark.parametrize("path,status", [("/private/x.pdf", "robots_disallowed"), ("/html.pdf", "bad_content_type"),
                                         ("/fake.pdf", "not_pdf"), ("/big.pdf", "too_large"), ("/missing.pdf", "http_404")])
def test_pdf_fetch_limits(tmp_path, path, status):
    r = fetcher(tmp_path, max_bytes=5000).fetch("https://repo.example.org" + path)
    assert r.status == status and r.path is None
    assert not list((tmp_path / "pdf").glob("*.pdf")) if (tmp_path / "pdf").exists() else True


def test_pdf_streaming_size_limit_without_content_length(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=iter([PDF_BYTES] * 20), headers={"content-type": "application/pdf"})
    assert fetcher(tmp_path, h, max_bytes=3000).fetch("https://repo.example.org/s.pdf").status == "too_large"


def test_only_open_access_works_are_downloaded(tmp_path):
    calls = []
    raw = SCENARIO["works_by_author"]["A100"]["results"]
    works = [parse_work(r, "t") for r in raw]
    stats = papers.fetch_fulltexts(works, fetcher(tmp_path, pdf_handler(calls)), text_dir=tmp_path / "text")
    assert stats == {"ok": 1, "not_oa": 1}
    assert [c for c in calls if c.endswith(".pdf")] == [PDF_URL]
    ok = next(w for w in works if w.fulltext_status == "ok")
    assert ok.fulltext_chars == len((tmp_path / "text" / f"{ok.pdf_sha1}.txt").read_text(encoding="utf-8")) > 20


# ---------------- page links decision table ---------------------------------------------------------------
def test_page_links_only_from_the_entitys_own_page():
    ents = corpus()
    pg = pages(ents)
    links = papers.page_paper_links(ents, pg)
    assert links == {ents[3].id: [("doi", "10.1000/unitpaper", ents[3].source_urls[0]),
                                  ("boris", "123", ents[3].source_urls[0])]}
    # a directory page shared by two units attributes nothing
    shared = [e.model_copy(update={"source_urls": ents[3].source_urls}) if e.id == ents[1].id else e for e in ents]
    assert papers.page_paper_links(shared, pg) == {}


# ---------------- collect end to end (mocked) --------------------------------------------------------------
def test_collect_matches_works_links_and_fulltext(tmp_path, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat_json", fake)
    ents = corpus()
    res = papers.collect(ents, pages(ents), client(tmp_path), fetcher=fetcher(tmp_path), use_llm=True,
                         workers=2, text_dir=tmp_path / "text")
    by = {m.entity_name: m for m in res.matches}
    assert by["Jane Doe"].chosen_author_id == "A100" and by["Prof. Max Muster"].chosen_author_id == "A200"
    assert by["Ann A"].chosen_author_id is None and by["Ann A"].decided_by == "rules"  # no candidates: no LLM call
    assert fake.calls.count("_AuthorChoice") == 2
    assert set(res.works) == {"W1001", "W1002", "W2001", "W3001"}
    w = res.works["W1001"]
    links = {(l.entity_id, l.relation, l.position) for l in w.links}
    assert links == {(ents[0].id, "author", 0), (ents[2].id, "author", 2)}  # Jane first, Max last (co-author)
    assert [a.entity_id for a in w.authors] == [ents[0].id, None, ents[2].id]
    assert w.fulltext_status == "ok" and w.pdf_url == PDF_URL and w.fulltext_chars > 0
    assert res.works["W1002"].fulltext_status == "not_oa" and res.works["W2001"].fulltext_status == "no_pdf_url"
    unit = res.works["W3001"].links
    assert [(l.entity_id, l.relation) for l in unit] == [(ents[3].id, "page_link")]
    assert res.stats["page_links"] == {"refs": 2, "resolved": 1, "unsupported_scheme": 1}
    assert res.stats["institutions"][0]["ror"] == "https://ror.org/02k7v4d05"
    # chunks: abstract + full text
    ch = papers.paper_chunks(w, tmp_path / "text")
    assert ch[0][0] == "abstract" and ch[0][2].startswith("Photoacoustic glucose sensing") and ch[1][0] == "fulltext"
    # JSONL round trip
    papers.save_jsonl(res, tmp_path / "w.jsonl", tmp_path / "m.jsonl")
    works, matches = papers.load_jsonl(tmp_path / "w.jsonl", tmp_path / "m.jsonl")
    assert {x.id for x in works} == set(res.works) and len(matches) == 3


def test_collect_reports_unknown_ror(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "papers_rors", ("https://ror.org/02k7v4d05", "https://ror.org/02k7v4623"))
    papers.collect([], [], client(tmp_path), use_llm=False)
    assert "02k7v4623" in capsys.readouterr().out


def test_file_backend_refuses_embed_and_link():
    from navigator.filestore import FileIndexStore
    from navigator.storage import StorageError
    with pytest.raises(StorageError) as e:
        papers.embed_pending(FileIndexStore())
    assert e.value.code == "unsupported"


# ---------------- kNN / threshold ------------------------------------------------------------------
def test_select_edges_threshold_and_degree_cap():
    pairs = [("a", "b", 0.95), ("b", "a", 0.95), ("a", "c", 0.93), ("a", "d", 0.92), ("c", "d", 0.70), ("b", "c", 0.91)]
    assert papers.select_edges(pairs, k=2, threshold=0.9) == [("a", "b", 0.95), ("a", "c", 0.93), ("b", "c", 0.91)]
    assert papers.select_edges(pairs, k=5, threshold=0.94) == [("a", "b", 0.95)]


def test_calibrate_threshold_and_knn_reference():
    scores = [0.80, 0.82, 0.85, 0.88, 0.90, 0.91, 0.93, 0.95, 0.96, 0.99]
    assert papers.calibrate_threshold(scores, quantile=0.5, floor=0.0) == pytest.approx(0.905)
    assert papers.calibrate_threshold(scores, quantile=0.1, floor=0.9) == 0.9
    assert papers.calibrate_threshold([], floor=0.8) == 0.8
    d = papers.distribution(scores)
    assert d["n"] == 10 and d["min"] == 0.8 and d["max"] == 0.99
    v = np.array([[1, 0], [0.99, 0.141], [0, 1]], dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    pairs = papers.knn_pairs(["x", "y", "z"], v, k=1)
    assert [(a, b) for a, b, _ in pairs] == [("x", "y"), ("y", "x"), ("z", "y")]
    assert papers.select_edges(pairs, k=1, threshold=0.5) == [("x", "y", pytest.approx(0.99, abs=1e-3))]


# ---------------- topics ------------------------------------------------------------------------------
def test_map_topic_whitelist_llm_and_rules(monkeypatch):
    wl = [("continuous glucose monitoring", "continuous glucose monitoring"), ("audiology", "audiology")]
    monkeypatch.setattr(llm, "chat_json", FakeLLM(topics={"Diabetes Management": "continuous glucose monitoring",
                                                          "Bogus": "volcanology"}))
    assert papers.map_topic("Diabetes Management", "Medicine", wl, True)[:2] == ("continuous glucose monitoring", "llm")
    assert papers.map_topic("Photoacoustic Imaging", "Medicine", wl, True)[:2] == (None, "llm")
    key, by, reason = papers.map_topic("Bogus", "x", wl, True)
    assert key is None and "invalid choice" in reason

    def down(*a, **k):
        raise llm.LLMError("down")
    monkeypatch.setattr(llm, "chat_json", down)
    assert papers.map_topic("Audiology", "Medicine", wl, True)[:2] == ("audiology", "rules")
    assert papers.map_topic("Diabetes Management", "Medicine", wl, True)[0] is None
