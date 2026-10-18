"""Papers on the Postgres backend, end to end: index -> papers collect (fixtures) -> embed -> link -> search.

Skipped unless TEST_DATABASE_URL points to a throwaway bern-pg database with every migration (0001-0005):
    TEST_DATABASE_URL=postgresql://bern_app:<pw>@127.0.0.1:55437/bern pytest -q tests/test_pg_papers.py
The database is wiped (DML only) before each test.
"""
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from navigator import config, crawl, index, llm, papers, search  # noqa: E402
from navigator.openalex_client import OpenAlexClient  # noqa: E402
from navigator.storage import index_store  # noqa: E402
from papers_fixtures import FakeLLM, corpus, openalex_handler, pages, pdf_handler  # noqa: E402
from test_pg_backend import fake_embed  # noqa: E402

PG_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set (Postgres backend tests)")

TOPICS = {"Diabetes Management and Glucose Monitoring": "continuous glucose monitoring"}
PAPER_QUERY = "photoacoustic spectroscopy noninvasively through skin acoustic resonator"


def _sql(q, *params):
    import psycopg
    with psycopg.connect(PG_URL) as c:
        return c.execute(q, params).fetchall()


def _graph_count(label):
    q = f"SELECT count(*) FROM cypher('expertise_graph', $$ MATCH ()-[r:{label}]->() RETURN r $$) AS (r agtype)"
    return _sql(q)[0][0]


def _wipe():
    import psycopg
    with psycopg.connect(PG_URL) as c:
        c.execute("SELECT * FROM cypher('expertise_graph', $$ MATCH (n) DETACH DELETE n $$) AS (v agtype)")
        for t in ("nav.similarity", "nav.paper_topic", "nav.topic_map", "nav.author_match", "nav.research_profile",
                  "nav.paper_chunk", "nav.paper_author", "nav.paper", 'nav."case"', "nav.rejected_claim",
                  "nav.passage", "nav.evidence", "nav.entity", "nav.page", "nav.source"):
            c.execute(f"DELETE FROM {t}")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for name in ("BM25_PATH", "ENTITIES_PATH", "VEC_PATH", "VEC_META_PATH"):
        monkeypatch.setattr(index, name, tmp_path / Path(str(getattr(index, name))).name)
    monkeypatch.setattr(index, "DATA_DIR", tmp_path)
    monkeypatch.setattr(index, "embed", fake_embed)
    for k, v in {"qdrant_url": "", "use_llm_expansion": False, "use_llm_explain": False, "min_vector_score": 0.30,
                 "max_per_unit": 2, "database_url": PG_URL, "similar_person_threshold": "0.1",
                 "similar_paper_threshold": "0.1"}.items():
        monkeypatch.setattr(config.settings, k, v)
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)   # search: deterministic explanations
    monkeypatch.setattr(llm, "chat_json", FakeLLM(topics=TOPICS))  # matcher / topic mapping
    ents = corpus()
    monkeypatch.setattr(crawl, "load_pages", lambda source=None: pages(ents))
    _wipe()
    index.build(ents)
    return tmp_path, ents


def _run_papers(tmp_path, ents):
    oa = OpenAlexClient(base_url="https://api.openalex.test", mailto="", api_key="", rps=1000,
                        cache_dir=tmp_path / "cache", transport=httpx.MockTransport(openalex_handler()),
                        sleep=lambda s: None)
    fetch = papers.PdfFetcher(tmp_path / "pdf", client=httpx.Client(transport=httpx.MockTransport(pdf_handler())),
                              delay=0, sleep=lambda s: None)
    res = papers.collect(ents, pages(ents), oa, fetcher=fetch, use_llm=True, text_dir=tmp_path / "text")
    st = index_store()
    out = {"store": st.write_papers(list(res.works.values()), res.matches,
                                    {w.id: papers.paper_chunks(w, tmp_path / "text") for w in res.works.values()})}
    out["embed"] = papers.embed_pending(st)
    out["similar"] = papers.link_similar(st)
    out["topics"] = papers.link_topics(st, use_llm=True)
    return res, out


def test_papers_tables_graph_and_reindex(env):
    tmp_path, ents = env
    res, out = _run_papers(tmp_path, ents)
    jane, maxm, hrl = ents[0].id, ents[2].id, ents[3].id
    assert _sql("SELECT count(*) FROM nav.paper")[0][0] == 4
    assert set(_sql("SELECT paper_id, entity_id, relation, position FROM nav.paper_author")) == {
        ("W1001", jane, "author", 0), ("W1001", maxm, "author", 2), ("W1002", jane, "author", 0),
        ("W2001", maxm, "author", 0), ("W3001", hrl, "page_link", None)}
    audit = dict(_sql("SELECT entity_name, decided_by || ':' || coalesce(chosen_author_id, '-') FROM nav.author_match"))
    assert audit == {"Jane Doe": "llm:A100", "Prof. Max Muster": "llm:A200", "Ann A": "rules:-"}
    # every chunk embedded; abstract + full text of the OA paper
    assert _sql("SELECT count(*) FROM nav.paper_chunk WHERE embedding IS NULL")[0][0] == 0
    assert dict(_sql("SELECT kind, count(*) FROM nav.paper_chunk WHERE paper_id = 'W1001' GROUP BY kind")) == \
        {"abstract": 1, "fulltext": 1}
    assert out["embed"]["research_profiles"] == 2 and out["embed"]["paper_vectors"] == 4
    # graph projection
    assert _graph_count("AUTHORED") == 4 and _graph_count("CITES") == 1  # W1001 -> W1002 (W9999 unknown)
    assert out["similar"]["person"]["edges"] == 1 and _graph_count("SIMILAR_TO") >= 1
    assert out["similar"]["person"]["distribution"]["n"] == 2
    topics = dict(_sql("SELECT openalex_label, topic_key || '|' || is_new::text FROM nav.topic_map"))
    assert topics["Diabetes Management and Glucose Monitoring"] == "continuous glucose monitoring|false"
    assert topics["Photoacoustic and Ultrasonic Imaging"].endswith("|true")
    about = {json.loads(r[0]) for r in _sql(
        "SELECT * FROM cypher('expertise_graph', $$ MATCH (:Paper {paper_id: 'W1001'})-[:ABOUT]->(t:Topic) "
        "RETURN t.key $$) AS (k agtype)")}
    assert about == {"continuous glucose monitoring", "photoacoustic and ultrasonic imaging"}
    # 2-hop: who shares a topic with Jane through a paper? (Person)-[:AUTHORED]->(Paper)-[:ABOUT]->(Topic)
    peers = {json.loads(r[0]) for r in _sql(
        "SELECT * FROM cypher('expertise_graph', $$ MATCH (p:Person {entity_id: '" + jane + "'})-[:AUTHORED]->(:Paper)"
        "-[:ABOUT]->(t:Topic)<-[:HAS_EXPERTISE]-(o) RETURN DISTINCT o.name $$) AS (n agtype)")}
    assert "Diabetes Technology Lab" in peers
    # a full reindex rebuilds the entity graph; the paper subgraph is re-projected from the tables
    index.build(ents)
    assert _graph_count("AUTHORED") == 4 and _graph_count("ABOUT") == 5 and _graph_count("SIMILAR_TO") >= 1
    assert _sql("SELECT count(*) FROM nav.research_profile")[0][0] == 2
    # rerun of the whole papers pipeline is idempotent (embeddings kept: nothing new to embed)
    _, again = _run_papers(tmp_path, ents)
    assert again["embed"]["chunks_embedded"] == 0 and _graph_count("AUTHORED") == 4
    # ... and the author-match audit does not record the same decisions twice
    assert again["store"]["author_matches"] == 0 and _sql("SELECT count(*) FROM nav.author_match")[0][0] == 3


def test_openalex_entity_indexes_and_uses_known_id(env):
    """An entity from the team's OpenAlex source (extractor 'openalex', author URL) goes into nav.entity
    (0004 widens the CHECK) and is matched by its id: no search, decided_by known_id in the audit."""
    tmp_path, ents = env
    oa_ent = ents[0].model_copy(update={"id": "00000000000000aa", "name": "Jane Q. Doe", "extractor": "openalex",
                                        "source": "unibe", "source_urls": ["https://openalex.org/A100"]})
    index.build([*ents, oa_ent])
    loaded = index_store().load_entities()["00000000000000aa"]
    assert loaded.extractor == "openalex" and papers.known_author_id(loaded)[0] == "A100"
    oa = OpenAlexClient(base_url="https://api.openalex.test", mailto="", api_key="", rps=1000, cache_dir=None,
                        transport=httpx.MockTransport(openalex_handler()), sleep=lambda s: None)
    res = papers.collect([loaded], [], oa, use_llm=True, text_dir=tmp_path / "text")
    index_store().write_papers(list(res.works.values()), res.matches, {})
    assert _sql("SELECT decided_by, chosen_author_id, candidates FROM nav.author_match") == [("known_id", "A100", [])]


def test_search_finds_person_through_paper(env, monkeypatch):
    tmp_path, ents = env
    # before papers: nothing on the pages supports the query -> honest abstention
    assert search.search(PAPER_QUERY).abstained
    _run_papers(tmp_path, ents)
    r = search.search(PAPER_QUERY)
    assert not r.abstained
    jane = next(x for x in r.results if x.person_or_unit == "Jane Doe")
    src = jane.sources[0]
    assert src.url == "https://doi.org/10.1000/w1001" and src.field == "publication"
    assert "Photoacoustic spectroscopy" in src.snippet
    assert "Author of “Photoacoustic glucose sensing in interstitial fluid” (2024)" in jane.why_match
    assert src.snippet[:40] in jane.why_match
    assert all(x.sources and all(s.url and s.snippet for s in x.sources) for x in r.results)
    # same API shape as before: only a new source type
    assert set(jane.model_dump()) == set(search.SearchResult.model_fields)
    # abstention unchanged for out-of-domain queries
    assert search.search("volcano geochemistry iceland").abstained
    # papers switched off -> back to page evidence only
    monkeypatch.setattr(config.settings, "use_papers", False)
    assert search.search(PAPER_QUERY).abstained


def test_similar_to_propagation(env):
    tmp_path, ents = env
    _run_papers(tmp_path, ents)
    jane, maxm = ents[0].id, ents[2].id
    nb = index_store().similar_neighbors([jane])
    assert [b for b, _ in nb[jane]] == [maxm]
    fused = {jane: 0.05}
    via = search.propagate_similar(fused, index.load_entities())
    assert via == {maxm: (jane, nb[jane][0][1])}
    assert fused[maxm] == pytest.approx(0.05 * config.settings.similar_damping * nb[jane][0][1])
    # the explanation says why and cites Max's own paper
    from navigator.storage import PaperHit
    qv = fake_embed(["cochlear implant electrode insertion"], query=True)[0]
    hit = index_store().paper_best_for(qv, [maxm])[maxm]
    assert isinstance(hit, PaperHit) and hit.paper_id == "W2001"
    why, refs = search.explain_similar("cochlear implant electrode insertion", index.load_entities()[maxm],
                                       index.load_entities()[jane], 0.9, [], hit)
    assert why.startswith("Research profile similar to Jane Doe") and refs[-1].url == "https://doi.org/10.1000/w2001"
