"""Postgres backend (pgvector + FTS + AGE) against a real database.

Skipped unless TEST_DATABASE_URL points to a bern-pg database (role bern_app, migrations applied):
    TEST_DATABASE_URL=postgresql://bern_app:<pw>@127.0.0.1:55433/bern pytest -q tests/test_pg_backend.py
The database is wiped (DML only) before each test: never point this at a shared database.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import cases, config, crawl, graph, index, llm, search  # noqa: E402
from navigator.schema import Entity, Evidence, Page  # noqa: E402
from navigator.storage import StorageError, index_store  # noqa: E402

PG_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set (Postgres backend tests)")

URL = "https://www.example.unibe.ch/"
TS = "2026-10-18T09:00:00.123456+00:00"


def hid(i) -> str:
    return hashlib.sha1(f"ent{i}".encode()).hexdigest()[:16]


def fake_embed(texts, query=False):
    """768-dim hashing embedder: deterministic stand-in for multilingual-e5-base (no model download)."""
    out = np.zeros((len(texts), 768), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in re.findall(r"\w{3,}", t.lower()):
            out[i, int(hashlib.md5(tok.encode()).hexdigest(), 16) % 768] += 1
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def ent(i, name, etype, unit, expertise, source="artorg", projects=()):
    url = URL + str(i)
    ev = [Evidence(field="name", value=name, snippet=f"{name} works here.", url=url)]
    if unit:
        ev.append(Evidence(field="unit", value=unit, snippet=f"{name} is a member of {unit}.", url=url))
    ev += [Evidence(field="expertise", value=x, snippet=f"{name} researches {x}.", url=url) for x in expertise]
    ev += [Evidence(field="projects", value=p, snippet=f"{name} leads {p}.", url=url) for p in projects]
    return Entity(id=hid(i), entity_type=etype, name=name, unit=unit, expertise=list(expertise), projects=list(projects),
                  source=source, source_label=source.upper(), source_urls=[url], evidence=ev, retrieved_at=TS)


def corpus() -> list[Entity]:
    return [
        ent(1, "Jane Doe", "person", "Diabetes Technology Lab", ["continuous glucose monitoring", "closed-loop insulin delivery"],
            projects=["Artificial Pancreas"]),
        ent(2, "Diabetes Technology Lab", "unit", None, ["continuous glucose monitoring"], projects=["Artificial Pancreas"]),
        ent(8, "Artificial Pancreas", "project", "Diabetes Technology Lab", ["closed-loop insulin delivery"]),
        ent(3, "Prof. Max Muster", "person", "Hearing Research Lab", ["cochlear implant"]),
        ent(9, "Hearing Research Lab", "unit", None, ["cochlear implant", "audiology"]),
        ent(4, "Ann A", "person", "Big Lab", ["medical image analysis"]),
        ent(5, "Ann B", "person", "Big Lab", ["medical image analysis"]),
        ent(6, "Ann C", "person", "Big Lab", ["medical image analysis"]),
        ent(7, "Small Lab Lead", "person", "Small Lab", ["medical image analysis"], source="dcb"),
        ent(10, "Zürich Imaging Facility", "infrastructure", None, ["magnetic resonance imaging"], source="dcb"),
    ]


def pages(ents) -> list[Page]:
    seen = {}
    for e in ents:
        for ev in e.evidence:
            seen.setdefault(ev.url, (e.source, []))[1].append(ev.snippet)
    return [Page(url=u, source=s, title="t", text="\n".join(snips), fetched_at=TS) for u, (s, snips) in seen.items()]


def _wipe(url):
    import psycopg
    with psycopg.connect(url) as c:
        c.execute("SELECT * FROM cypher('expertise_graph', $$ MATCH (n) DETACH DELETE n $$) AS (v agtype)")
        for t in ('nav."case"', "nav.rejected_claim", "nav.passage", "nav.evidence", "nav.entity", "nav.page", "nav.source"):
            c.execute(f"DELETE FROM {t}")


def _sql(q, *params):
    import psycopg
    with psycopg.connect(PG_URL) as c:
        return c.execute(q, params).fetchall()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for name in ("BM25_PATH", "ENTITIES_PATH", "VEC_PATH", "VEC_META_PATH"):
        monkeypatch.setattr(index, name, tmp_path / Path(str(getattr(index, name))).name)
    monkeypatch.setattr(index, "DATA_DIR", tmp_path)
    monkeypatch.setattr(index, "embed", fake_embed)
    monkeypatch.setattr(config.settings, "qdrant_url", "")
    monkeypatch.setattr(config.settings, "use_llm_expansion", False)
    monkeypatch.setattr(config.settings, "use_llm_explain", False)
    monkeypatch.setattr(search.llm, "available", lambda *a, **k: False)
    monkeypatch.setattr(config.settings, "min_vector_score", 0.30)
    monkeypatch.setattr(config.settings, "max_per_unit", 2)
    ents = corpus()
    monkeypatch.setattr(crawl, "load_pages", lambda source=None: [p for p in pages(ents) if not source or p.source == source])
    (tmp_path / "rejected.jsonl").write_text(
        json.dumps({"source": "artorg", "url": URL + "1", "field": "role", "value": "CEO", "snippet": "invented"}) + "\n")
    _wipe(PG_URL)

    def use(backend: str):
        monkeypatch.setattr(config.settings, "database_url", PG_URL if backend == "pg" else "")
    use("pg")
    return use, ents


def test_index_writes_tables_and_graph(env):
    use, ents = env
    stats = index.build(ents)
    assert stats["entities"] == len(ents)
    counts = _sql("SELECT (SELECT count(*) FROM nav.entity), (SELECT count(*) FROM nav.evidence), "
                  "(SELECT count(*) FROM nav.passage), (SELECT count(*) FROM nav.page), "
                  "(SELECT count(*) FROM nav.rejected_claim), (SELECT count(*) FROM nav.source)")[0]
    n_ev = sum(len(e.evidence) for e in ents)
    n_pass = sum(len(index.entity_passages(e)) for e in ents)
    assert counts == (len(ents), n_ev, n_pass, len(pages(ents)), 1, 2)
    # every evidence row is linked to its page; every evidence passage to its evidence
    assert _sql("SELECT count(*) FROM nav.evidence WHERE page_id IS NULL")[0][0] == 0
    assert _sql("SELECT count(*) FROM nav.passage WHERE kind = 'evidence' AND evidence_id IS NULL")[0][0] == 0
    rels = dict(_sql("SELECT label, count(*) FROM cypher('expertise_graph', $$ MATCH ()-[r]->() RETURN label(r) $$) "
                     "AS (label agtype) GROUP BY 1"))
    assert rels['"MEMBER_OF"'] == 2 and rels['"WORKS_ON"'] == 1 and rels['"PART_OF"'] == 1
    assert rels['"FROM_SOURCE"'] == len(ents)
    assert int(_sql("SELECT count(*) FROM cypher('expertise_graph', $$ MATCH (t:Topic) RETURN t $$) AS (t agtype)")[0][0]) \
        == len({graph.topic_key(x) for e in ents if e.entity_type != "infrastructure" for x in e.expertise})
    # who shares expertise with Jane Doe? (2-hop through Topic)
    peers = {json.loads(r[0]) for r in _sql(
        "SELECT * FROM cypher('expertise_graph', $$ MATCH (p {entity_id: '" + hid(1) + "'})-[:HAS_EXPERTISE]->(:Topic)"
        "<-[:HAS_EXPERTISE]-(o) RETURN DISTINCT o.name $$) AS (n agtype)")}
    assert peers == {"Diabetes Technology Lab", "Artificial Pancreas"}


def test_reindex_is_idempotent_and_scoped(env):
    use, ents = env
    index.build(ents)
    before = _sql("SELECT count(*), sum(length(text)) FROM nav.passage")[0]
    index.build(ents)
    assert _sql("SELECT count(*), sum(length(text)) FROM nav.passage")[0] == before
    # re-index only dcb without its facility: artorg untouched, dcb replaced
    dcb_only = [e for e in ents if e.source == "dcb" and e.entity_type != "infrastructure"]
    index.build(ents[:3] + dcb_only, sources=["dcb"])
    by_src = dict(_sql("SELECT source, count(*) FROM nav.entity GROUP BY source"))
    assert by_src == {"artorg": 8, "dcb": 1}
    assert _sql("SELECT count(*) FROM nav.passage WHERE source = 'dcb' AND entity_type = 'infrastructure'")[0][0] == 0
    n_fac = _sql("SELECT count(*) FROM cypher('expertise_graph', $$ MATCH (i:Infrastructure) RETURN i $$) AS (i agtype)")
    assert n_fac[0][0] == 0


def test_neighbors_match_file_adjacency(env):
    use, ents = env
    index.build(ents)
    adj = graph.adjacency(ents)
    got = index_store().neighbors([e.id for e in ents])
    assert got == {e.id: adj.get(e.id, []) for e in ents}


QUERIES = ["glucose sensors", "medical image analysis", "closed-loop insulin delivery", "Dr. Jane Doe",
           "cochlear implant audiology", "volcano geochemistry iceland", "Prof. Erika Beispiel glucose"]


def _run(queries, **kw):
    return [search.search(q, **kw).model_dump(exclude={"took_ms"}) for q in queries]


def test_search_parity_file_vs_pg(env):
    """Same corpus, same queries: identical responses except lexical scores (FTS vs BM25 ranks feed RRF)."""
    use, ents = env
    use("file"); index.build(ents)
    use("pg"); index.build(ents)
    use("file"); f = _run(QUERIES) + _run(["medical image analysis"], sources=["dcb"])
    use("pg"); p = _run(QUERIES) + _run(["medical image analysis"], sources=["dcb"])
    for a, b in zip(f, p):
        assert a["abstained"] == b["abstained"], a["query"]
        assert {r["id"] for r in a["results"]} == {r["id"] for r in b["results"]}, a["query"]
        for ra, rb in zip(sorted(a["results"], key=lambda r: r["id"]), sorted(b["results"], key=lambda r: r["id"])):
            assert (ra["related"], ra["via"], ra["sources"], ra["why_match"]) == \
                   (rb["related"], rb["via"], rb["sources"], rb["why_match"]), (a["query"], ra["person_or_unit"])
            assert ra["confidence"] == pytest.approx(rb["confidence"], abs=0.011)


def test_pg_search_behaviour(env):
    use, ents = env
    index.build(ents)
    r = search.search("glucose sensors")
    assert not r.abstained and "Jane Doe" in [x.person_or_unit for x in r.results]
    assert all(x.sources and all(s.url and s.snippet for s in x.sources) for x in r.results)
    names = [x.person_or_unit for x in search.search("medical image analysis", k=3).results]
    assert "Small Lab Lead" in names and sum(n.startswith("Ann") for n in names) <= 2
    assert search.search("volcano geochemistry iceland").abstained
    jane = next(x for x in search.search("closed-loop insulin delivery").results if x.person_or_unit == "Jane Doe")
    assert "Diabetes Technology Lab" in jane.related
    # FTS: simple + unaccent -> 'zurich' finds 'Zürich'
    ids, top = index_store().lexical_rank(index.tokenize("zurich imaging"))
    assert ids and ids[0] == hid(10) and top > 0
    # vector filter by type
    hits = index_store().vector_search(fake_embed(["imaging"], query=True)[0], 50, types=["infrastructure"])
    assert [h[0] for h in hits] == [hid(10)]
    e = index.load_entities()[hid(1)]
    assert e.retrieved_at == TS and e.evidence == ents[0].evidence


def test_wrong_embedding_dim_is_structured_error(env, monkeypatch):
    use, ents = env
    monkeypatch.setattr(index, "embed", lambda texts, query=False: np.ones((len(texts), 384), dtype=np.float32))
    with pytest.raises(StorageError) as ei:
        index.build(ents)
    assert ei.value.code == "embedding_dim_mismatch"


def test_cases_roundtrip_and_api(env, monkeypatch):
    from fastapi.testclient import TestClient

    from navigator import api
    use, ents = env
    index.build(ents)
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    monkeypatch.setattr(cases.showcase, "build", lambda: {"highlights": []})
    client = TestClient(api.app)
    off = {"actor": "Maria"}
    req = {"request_text": "We need a partner for continuous glucose monitoring and closed-loop insulin delivery.",
           "country": "Switzerland", "canton": "BE", "area": "diabetes", "niche": "glucose", **off}
    c = client.post("/cases", json=req).json()
    assert c["matches"] and c["matches"][0]["id"] in {e.id for e in ents}
    assert (c["company"], c["canton"], c["area"], c["niche"]) == ("", "BE", "diabetes", "glucose")
    cid = c["id"]
    assert client.get(f"/cases/{cid}").json() == c
    stored = _sql('SELECT company, country, canton, area, niche FROM nav."case" WHERE id = %s', cid)[0]
    assert stored == ("", "Switzerland", "BE", "diabetes", "glucose")
    listed = client.get("/cases").json()[0]
    assert (listed["canton"], listed["area"], listed["niche"]) == ("BE", "diabetes", "glucose")
    sel = [c["matches"][0]["id"]]
    r = client.post(f"/cases/{cid}/selection", json={"selected": sel, **off}).json()
    assert [m["id"] for m in r["matches"] if m["selected"]] == sel
    r = client.post(f"/cases/{cid}/details", json={"company": "Example Sensors GmbH (fictional)",
                                                    "contact_name": "Anna", "contact_email": "anna@example.com", **off}).json()
    assert r["company"] == "Example Sensors GmbH (fictional)" and r["status"] == "new"
    assert _sql('SELECT company, contact_email FROM nav."case" WHERE id = %s', cid)[0] == \
        ("Example Sensors GmbH (fictional)", "anna@example.com")
    assert [e["kind"] for e in client.get(f"/cases/{cid}").json()["events"]] == ["created", "analysed", "details"]
    # the review step is gone on this backend too
    assert client.post(f"/cases/{cid}/review-request", json={"reviewer": "x", **off}).status_code in (404, 405)
    # a reindex that drops the matched entity keeps the match id (entity_ref snapshot)
    index.build([e for e in ents if e.id != sel[0]])
    again = client.get(f"/cases/{cid}").json()
    assert again["matches"][0]["id"] == sel[0] and again["matches"][0]["selected"]
    assert client.get("/cases").json()[0]["id"] == cid
    # executive brief (outreach jsonb) + its public link, then the short email that points to it
    from navigator import brief
    brief._publications.cache_clear()
    b = client.post(f"/cases/{cid}/brief", json={"lang": "en", **off}).json()
    assert b["token"] and client.get(f"/briefs/{b['token']}").json()["company"] == "Example Sensors GmbH (fictional)"
    assert _sql("""SELECT outreach->'brief'->>'token' FROM nav."case" WHERE id = %s""", cid)[0][0] == b["token"]
    assert client.get("/cases").json()[0]["has_brief"]
    d = client.post(f"/cases/{cid}/draft", json={"lang": "en", **off}).json()
    assert d["to"] == "anna@example.com" and d["matches"] == sel
    done = client.post(f"/cases/{cid}/outcome", json={"kind": "email", "subject": d["subject"], "body": d["body"], **off}).json()
    assert done["status"] == "contacted" and _sql('SELECT status FROM nav."case" WHERE id = %s', cid)[0][0] == "contacted"
    assert client.delete(f"/cases/{cid}").status_code in (200, 204)
    assert _sql('SELECT count(*) FROM nav.case_match WHERE case_id = %s', cid)[0][0] == 0


def test_company_link_documents_and_broad_search_roundtrip(env, monkeypatch, tmp_path):
    """Main's request from a company link / shared documents and the broad search (migration 0005):
    every new field survives the Postgres round trip and matches what the file backend stores."""
    use, ents = env
    use("file"); index.build(ents)
    use("pg"); index.build(ents)
    from fastapi.testclient import TestClient
    from navigator import api, company as company_web
    from navigator.storage import case_store
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    site = company_web.CompanyWebsite(url="https://example.com/", name="Example Sensors (fictional)",
                                      description="Glucose sensors.", text="We build continuous glucose monitoring sensors.",
                                      pages=[company_web.WebPage(url="https://example.com/", title="Home")])
    monkeypatch.setattr(company_web, "read", lambda url: site)
    off = {"actor": "Maria"}
    doc = {"name": "pitch.pdf", "kind": "PDF", "pages": 2, "text": "Closed-loop insulin delivery for type 1 diabetes."}
    reqs = [
        {"request_text": "glucose company in Milan", "broad": True, **off},
        {"company_url": "https://example.com", "documents": [doc], "need": "clinical validation partner", **off},
    ]
    seen = {}
    for backend in ("file", "pg"):
        use(backend)
        assert case_store().name == ("postgres" if backend == "pg" else "sqlite")
        client = TestClient(api.app)
        out = []
        for r in reqs:
            c = client.post("/cases", json=r).json()
            assert client.get(f"/cases/{c['id']}").json() == c
            out.append(c)
        seen[backend] = out
    broad, linked = seen["pg"]
    assert (broad["city"], broad["country"], broad["area"], broad["niche"]) == ("Milan", "Italy", "diabetes", "glucose")
    assert {d["kind"] for d in broad["understood"]} >= {"city", "country", "niche"}
    assert linked["company"] == "Example Sensors (fictional)" and linked["company_url"] == "https://example.com/"
    assert linked["website"]["pages"][0]["title"] == "Home" and linked["documents"][0]["name"] == "pitch.pdf"
    assert linked["need"] == "clinical validation partner" and linked["matches"]
    assert all(m["archetype"] for m in linked["matches"])
    stored = _sql('SELECT city, understood, company_url, need, website->>\'name\', documents->0->>\'kind\' '
                  'FROM nav."case" WHERE id = %s', linked["id"])[0]
    assert stored[2:] == ("https://example.com/", "clinical validation partner", "Example Sensors (fictional)", "PDF")
    assert _sql('SELECT city FROM nav."case" WHERE id = %s', broad["id"])[0][0] == "Milan"
    arch = [a for (a,) in _sql("SELECT archetype FROM nav.case_match WHERE case_id = %s ORDER BY rank", linked["id"])]
    assert arch == [m["archetype"] for m in linked["matches"]]
    # same content on both backends (ids and timestamps differ; FTS vs BM25 may reorder matches and
    # nudge their confidence, see test_search_parity_file_vs_pg)
    volatile = {"id", "created_at", "updated_at", "events", "matches"}
    for f, p in zip(seen["file"], seen["pg"]):
        assert {k: v for k, v in f.items() if k not in volatile} == {k: v for k, v in p.items() if k not in volatile}
        assert {m["id"]: m["archetype"] for m in f["matches"]} == {m["id"]: m["archetype"] for m in p["matches"]}
