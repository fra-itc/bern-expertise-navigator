"""Papers: entities that already carry their OpenAlex author id, incremental/resumable collect, dry-run estimate.
No network, DB or model (same mocks as test_papers.py)."""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from navigator import llm, papers  # noqa: E402
from navigator.openalex_client import OpenAlexClient, parse_work  # noqa: E402
from navigator.schema import Evidence  # noqa: E402
from papers_fixtures import SCENARIO, FakeLLM, corpus, ent, openalex_handler, pages, pdf_handler  # noqa: E402


def client(tmp_path, calls=None) -> OpenAlexClient:
    # no disk cache shared between runs: every request must reach the handler to be counted
    return OpenAlexClient(base_url="https://api.openalex.test", mailto="", api_key="", rps=1000, cache_dir=None,
                          transport=httpx.MockTransport(openalex_handler(calls)),
                          sleep=lambda s: None)


def fetcher(tmp_path, calls=None) -> papers.PdfFetcher:
    http = httpx.Client(transport=httpx.MockTransport(pdf_handler(calls)), follow_redirects=True)
    return papers.PdfFetcher(tmp_path / "pdf", client=http, delay=0, sleep=lambda s: None)


def from_openalex(eid: str, name: str, *urls: str, values: tuple[str, ...] = ()):
    e = ent(eid, name, "person", None, ["glucose sensing"], urls[0] if urls else "https://example.org/x",
            source="unibe")
    ev = [*e.evidence, *(Evidence(field="description", value=v, snippet=v, url=e.source_urls[0]) for v in values)]
    return e.model_copy(update={"extractor": "openalex", "source_urls": list(urls) or e.source_urls, "evidence": ev})


def authors_calls(calls) -> list[str]:
    return [str(c.url) for c in calls if c.url.path == "/authors"]


# ---------------- known id decision table ----------------------------------------------------------------------
def test_known_author_id_decision_table():
    one = from_openalex("a" * 16, "Jane Doe", "https://openalex.org/A100")
    assert papers.known_author_id(one) == ("A100", "known_id: entity extracted from OpenAlex author A100")
    api = from_openalex("b" * 16, "Jane Doe", "https://api.openalex.org/authors/a100")
    assert papers.known_author_id(api)[0] == "A100"                      # API URL, lowercase id
    bare = from_openalex("c" * 16, "Jane Doe", "https://example.org/x", values=("A100",))
    assert papers.known_author_id(bare)[0] == "A100"                     # id as an evidence value
    two = from_openalex("d" * 16, "Jane Doe", "https://openalex.org/A100", "https://openalex.org/A200")
    assert papers.known_author_id(two)[0] is None                        # ambiguous: normal matching
    none = from_openalex("e" * 16, "Jane Doe", "https://example.org/x")
    assert papers.known_author_id(none)[0] is None
    web = ent("f" * 16, "Jane Doe", "person", None, [], "https://openalex.org/A100")   # extractor apertus
    assert papers.known_author_id(web)[0] is None
    work = from_openalex("1" * 16, "Jane Doe", "https://openalex.org/W1001")         # a work, not an author
    assert papers.known_author_id(work)[0] is None


def test_known_id_skips_search_and_llm(tmp_path, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat_json", fake)
    calls: list = []
    e = from_openalex("a" * 16, "Jane Doe", "https://openalex.org/A100")
    res = papers.collect([e], [], client(tmp_path, calls), use_llm=True, text_dir=tmp_path / "text")
    (m,) = res.matches
    assert (m.chosen_author_id, m.decided_by, m.candidates) == ("A100", "known_id", [])
    assert fake.calls == [] and authors_calls(calls) == []                # no author search, no LLM call
    assert set(res.works) == {"W1001", "W1002"} and res.stats["decided_by"] == {"known_id": 1}
    assert {(l.entity_id, l.relation) for l in res.works["W1001"].links} == {(e.id, "author")}


# ---------------- incremental + resumable collect ---------------------------------------------------------------
def run(tmp_path, ents, prev_works, prev_matches, limit, calls, pdf_calls):
    res = papers.collect(ents, pages(ents), client(tmp_path, calls), fetcher=fetcher(tmp_path, pdf_calls),
                         use_llm=True, limit=limit, text_dir=tmp_path / "text",
                         skip_ids=papers.decided_ids(prev_matches), previous_works={w.id: w for w in prev_works},
                         previous_matches=prev_matches)
    merged = papers.merge_results(prev_works, prev_matches, res)
    papers.save_jsonl(merged, tmp_path / "w.jsonl", tmp_path / "m.jsonl")
    return res, papers.load_jsonl(tmp_path / "w.jsonl", tmp_path / "m.jsonl")


def test_limit_people_then_resume_never_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", FakeLLM())
    ents = corpus()
    jane, max_ = ents[0], ents[2]
    calls, pdf_calls = [], []
    # run 1: one person (Jane)
    r1, (w1, m1) = run(tmp_path, ents, [], [], 1, calls, pdf_calls)
    assert [m.entity_name for m in r1.matches] == ["Jane Doe"] and len(authors_calls(calls)) == 1
    assert {l.entity_id for l in next(w for w in w1 if w.id == "W1001").links} == {jane.id}
    assert [u for u in pdf_calls if u.endswith(".pdf")] == ["https://repo.example.org/w1001.pdf"]
    # run 2: the next person (Max); Jane is not searched again, her PDF is not downloaded again
    calls.clear(); pdf_calls.clear()
    r2, (w2, m2) = run(tmp_path, ents, w1, m1, 1, calls, pdf_calls)
    assert [m.entity_name for m in r2.matches] == ["Prof. Max Muster"]
    assert r2.stats["skipped_done"] == 1 and len(authors_calls(calls)) == 1
    assert [u for u in pdf_calls if u.endswith(".pdf")] == []
    w1001 = next(w for w in w2 if w.id == "W1001")
    assert {(l.entity_id, l.relation) for l in w1001.links} == {(jane.id, "author"), (max_.id, "author")}
    assert w1001.fulltext_status == "ok" and w1001.pdf_sha1
    assert sorted(m.entity_name for m in m2) == ["Jane Doe", "Prof. Max Muster"]
    # run 3 (Ann) and run 4 (nobody left): totals stable, ids unique
    _, (w3, m3) = run(tmp_path, ents, w2, m2, 0, calls, pdf_calls)
    calls.clear()
    r4, (w4, m4) = run(tmp_path, ents, w3, m3, 0, calls, pdf_calls)
    assert r4.stats["people"] == 0 and authors_calls(calls) == []
    assert len(w4) == len({w.id for w in w4}) == len(w3) and len(m4) == len({m.entity_id for m in m4}) == 3
    for w in w4:
        keys = [(l.entity_id, l.relation) for l in w.links]
        assert len(keys) == len(set(keys))


def test_rules_decision_while_llm_down_is_retried():
    from navigator.schema import AuthorMatch
    down = AuthorMatch(entity_id="x", entity_name="X", candidates=[], decided_by="rules",
                       reason="LLM unavailable (timeout); rules: no Bern-affiliated candidate named exactly 'x'")
    final = AuthorMatch(entity_id="y", entity_name="Y", candidates=[], decided_by="rules", reason="rules: ...")
    assert papers.decided_ids([down, final]) == {"y"}


def test_fulltext_outcomes_kept_or_retried(tmp_path):
    raw = SCENARIO["works_by_author"]["A100"]["results"]
    works = [parse_work(r, "t") for r in raw]
    oa = next(w for w in works if w.pdf_urls)
    calls: list = []
    prev = {oa.id: oa.model_copy(update={"fulltext_status": "http_404"})}
    stats = papers.fetch_fulltexts([w.model_copy() for w in works], fetcher(tmp_path, calls),
                                   text_dir=tmp_path / "text", previous=prev)
    assert stats.get("kept_http_404") == 1 and [c for c in calls if c.endswith(".pdf")] == []
    prev = {oa.id: oa.model_copy(update={"fulltext_status": "skipped_limit"})}   # budget, not a verdict: retried
    stats = papers.fetch_fulltexts([w.model_copy() for w in works], fetcher(tmp_path, calls),
                                   text_dir=tmp_path / "text", previous=prev)
    assert stats.get("ok") == 1 and [c for c in calls if c.endswith(".pdf")] == ["https://repo.example.org/w1001.pdf"]


# ---------------- dry-run estimate ---------------------------------------------------------------------------
def test_estimate_without_network(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network or LLM used in a dry run")
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(llm, "chat_json", boom)
    monkeypatch.setattr(papers.settings, "papers_max_works", 30)
    monkeypatch.setattr(papers.settings, "papers_max_chunks", 8)
    ents = corpus() + [from_openalex("a" * 16, "Known Person", "https://openalex.org/A100")]
    est = papers.estimate(ents, pages(ents), max_pdfs=5)
    assert est["people"] == {"selected": 4, "known_openalex_id": 1, "to_search": 3, "already_decided_skipped": 0,
                             "types": ["person"], "limit": 0}
    # 1 institutions + 3 searches + 4 works_by_author + 1 DOI batch (BORIS refs have no OpenAlex lookup)
    assert est["openalex_requests_max"]["total"] == 9
    assert est["llm_calls_max"]["author_match"] == 3
    assert est["works_max"] == 4 * 30 + 1 and est["pdf_downloads_max"] == 5
    assert est["chunks_max"] == {"abstract": 121, "fulltext": 40, "total": 161}
    inc = papers.estimate(ents, pages(ents), limit=2, skip_ids={ents[0].id}, use_llm=False, pdf=False)
    assert inc["people"]["selected"] == 2 and inc["people"]["already_decided_skipped"] == 1
    assert inc["llm_calls_max"]["author_match"] == 0 and inc["pdf_downloads_max"] == 0
