"""Postgres backend (DATABASE_URL set): nav.* tables, pgvector, FTS and the AGE graph expertise_graph.

The app role (bern_app) has DML only: this module never issues DDL. Schema changes are migrations
in src/db/migrations/, checked at connect time (REQUIRED_MIGRATIONS).
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from . import graph
from .config import load_sources, settings
from .schema import AuthorMatch, Entity, Evidence, Work
from .storage import IndexBundle, PaperHit, StorageError

BACKEND = "postgres"
GRAPH = "expertise_graph"
DIM = 768
FTS_CONFIG = "nav.simple_unaccent"
# 0002_remove_technical_review (main) is not required: the store neither reads nor writes the review columns.
REQUIRED_MIGRATIONS = ("0001_initial", "0002_index_order_and_match_ref", "0003_case_search_filters", "0004_papers")
_REINDEX_LOCK = 0x6E617669  # pg_advisory_xact_lock key: one reindex at a time


def _iso(dt: datetime | None, seconds: bool = False) -> str | None:
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds") if seconds else dt.isoformat()


def _configure(conn: psycopg.Connection) -> None:
    from pgvector.psycopg import register_vector
    register_vector(conn)
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()


class _Pg:
    """Connection pool + structured error wrapping, shared by the index and case stores."""

    def __init__(self, url: str):
        self.url = url
        try:
            self.pool = ConnectionPool(url, min_size=1, max_size=settings.pg_pool_max, configure=_configure,
                                       kwargs={"application_name": "bern-navigator"}, open=False)
            self.pool.open(wait=True, timeout=15)
        except (psycopg.Error, PoolTimeout) as e:
            self.pool.close()
            raise StorageError("connect_failed", "cannot connect to DATABASE_URL", backend=BACKEND, cause=e) from e
        try:
            with self.op("schema_check") as cur:
                cur.execute("SELECT version FROM nav.schema_migrations")
                have = {r[0] for r in cur.fetchall()}
            missing = [m for m in REQUIRED_MIGRATIONS if m not in have]
            if missing:
                raise StorageError("schema_outdated",
                                   f"missing migrations {missing}: apply src/db/migrations/*.sql as the DB owner",
                                   backend=BACKEND)
        except StorageError:
            self.pool.close()
            raise

    @contextmanager
    def op(self, code: str):
        """One transaction; any driver error becomes StorageError(code)."""
        try:
            with self.pool.connection(timeout=15) as conn, conn.transaction(), conn.cursor() as cur:
                yield cur
        except StorageError:
            raise
        except (psycopg.Error, PoolTimeout) as e:
            raise StorageError(code, f"postgres operation '{code}' failed", backend=BACKEND, cause=e) from e


_BREAKER_S = 30.0
_pg_ok: dict[str, _Pg] = {}
_pg_fail: dict[str, tuple[float, StorageError]] = {}
_pg_lock = threading.Lock()


def _pg(url: str) -> _Pg:
    """One pool per URL. Circuit breaker: after a failed connect, fail fast for _BREAKER_S seconds
    instead of making every request wait for the pool timeout again."""
    with _pg_lock:
        if url in _pg_ok:
            return _pg_ok[url]
        failed = _pg_fail.get(url)
        if failed and time.monotonic() - failed[0] < _BREAKER_S:
            raise StorageError(failed[1].code, f"{failed[1].detail} (circuit open, retry in "
                               f"{_BREAKER_S - (time.monotonic() - failed[0]):.0f}s)", backend=BACKEND)
        try:
            _pg_ok[url] = _Pg(url)
        except StorageError as e:
            _pg_fail[url] = (time.monotonic(), e)
            raise
        _pg_fail.pop(url, None)
        return _pg_ok[url]


def _cypher(cur, query: str, params: dict | None = None, cols: str = "v agtype"):
    """Run Cypher on expertise_graph; params go through AGE's single agtype parameter."""
    q = f"SELECT * FROM cypher('{GRAPH}', $$ {query} $$" + (", %s" if params is not None else "") + f") AS ({cols})"
    cur.execute(q, (json.dumps(params),) if params is not None else None)


def _batches(rows: list, n: int = 500):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


# =============================================================================
class PgIndexStore:
    name = "postgres"
    persists_corpus = True
    supports_papers = True

    def __init__(self, pg: _Pg):
        self.pg = pg
        self._lock = threading.Lock()
        self._cache: tuple[str, dict[str, Entity]] | None = None

    @classmethod
    def for_url(cls, url: str) -> "PgIndexStore":
        return _index_store(url)

    # ---------------- write ---------------------------------------------------
    def write_index(self, b: IndexBundle) -> dict:
        if len(b.passages) and b.vectors.shape[1] != DIM:
            raise StorageError("embedding_dim_mismatch",
                               f"{b.embed_model} gives {b.vectors.shape[1]} dims, nav.passage is vector({DIM})",
                               backend=BACKEND)
        bad = [e.source for e in b.entities if b.scope and e.source not in b.scope]
        if bad:
            raise StorageError("scope_violation", f"entities outside scope {b.scope}: {sorted(set(bad))}", backend=BACKEND)
        stats: dict = {"store": "postgres (pgvector + FTS + AGE)"}
        with self.pg.op("write_index") as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_REINDEX_LOCK,))
            self._write_sources(cur, b)
            scope = b.scope
            ids = [e.id for e in b.entities]
            # entities that disappeared from the (re)indexed sources; case_match keeps its snapshot
            if scope:
                cur.execute("DELETE FROM nav.entity WHERE source = ANY(%s) AND NOT (id = ANY(%s))", (scope, ids))
            else:
                cur.execute("DELETE FROM nav.entity WHERE NOT (id = ANY(%s))", (ids,))
            stats["entities_removed"] = cur.rowcount
            self._write_pages(cur, b)
            self._write_entities(cur, b, stats)
            self._write_passages(cur, b, stats)
            self._write_rejected(cur, b, stats)
            self._write_graph(cur, b, stats)
            # the paper subgraph is a projection of nav.paper*: rebuilt so a reindex never loses it
            self._write_paper_graph(cur, stats)
            cur.execute("ANALYZE nav.passage")
            cur.execute("ANALYZE nav.entity")
        stats["entities"], stats["vectors"] = len(b.entities), len(b.passages)
        with self._lock:
            self._cache = None
        return stats

    def _write_sources(self, cur, b: IndexBundle) -> None:
        cfg = {s.name: s for s in load_sources()}
        names: dict[str, str] = {}
        for e in b.entities:
            names.setdefault(e.source, e.source_label)
        for p in b.pages:
            names.setdefault(p.source, p.source)
        for r in b.rejected:
            names.setdefault(r["source"], r["source"])
        rows = []
        for n, label in names.items():
            s = cfg.get(n)
            conf = {"seeds": s.seeds, "max_pages": s.max_pages, "max_depth": s.max_depth} if s else {}
            rows.append((n, s.label if s else label, s.domains if s else [], Jsonb(conf)))
        cur.executemany(
            "INSERT INTO nav.source(name, label, domains, config) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label, domains = EXCLUDED.domains, config = EXCLUDED.config",
            rows)

    def _write_pages(self, cur, b: IndexBundle) -> None:
        if b.scope:
            cur.execute("DELETE FROM nav.page WHERE source = ANY(%s)", (b.scope,))
        else:
            cur.execute("DELETE FROM nav.page")
        cur.executemany(
            "INSERT INTO nav.page(url, source, title, text, fetched_at, lang, page_type) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (url) DO UPDATE SET source = EXCLUDED.source, title = EXCLUDED.title, text = EXCLUDED.text, "
            "fetched_at = EXCLUDED.fetched_at, lang = EXCLUDED.lang, page_type = EXCLUDED.page_type",
            [(p.url, p.source, p.title, p.text, p.fetched_at, p.lang, p.page_type) for p in b.pages])

    def _write_entities(self, cur, b: IndexBundle, stats: dict) -> None:
        ids = [e.id for e in b.entities]
        cur.execute("DELETE FROM nav.passage WHERE entity_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM nav.evidence WHERE entity_id = ANY(%s)", (ids,))
        cur.executemany(
            "INSERT INTO nav.entity(id, entity_type, name, role, unit, institute, email, expertise, projects, "
            "infrastructure, description, source, source_label, source_urls, retrieved_at, extractor, load_order) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "entity_type = EXCLUDED.entity_type, name = EXCLUDED.name, role = EXCLUDED.role, unit = EXCLUDED.unit, "
            "institute = EXCLUDED.institute, email = EXCLUDED.email, expertise = EXCLUDED.expertise, "
            "projects = EXCLUDED.projects, infrastructure = EXCLUDED.infrastructure, description = EXCLUDED.description, "
            "source = EXCLUDED.source, source_label = EXCLUDED.source_label, source_urls = EXCLUDED.source_urls, "
            "retrieved_at = EXCLUDED.retrieved_at, extractor = EXCLUDED.extractor, load_order = EXCLUDED.load_order",
            [(e.id, e.entity_type, e.name, e.role, e.unit, e.institute, e.email, e.expertise, e.projects,
              e.infrastructure, e.description, e.source, e.source_label, e.source_urls, e.retrieved_at,
              e.extractor, i) for i, e in enumerate(b.entities)])
        ev_rows = [(e.id, ev.field, ev.value, ev.snippet, ev.url) for e in b.entities for ev in e.evidence]
        n_before = len(ev_rows)
        cur.executemany(
            "INSERT INTO nav.evidence(entity_id, field, value, snippet, url, page_id) "
            "VALUES (%s,%s,%s,%s,%s,(SELECT id FROM nav.page WHERE url = %s)) ON CONFLICT DO NOTHING",
            [(*r, r[4]) for r in ev_rows])
        cur.execute("SELECT count(*) FROM nav.evidence WHERE entity_id = ANY(%s)", (ids,))
        stats["evidence"] = cur.fetchone()[0]
        stats["evidence_duplicates_dropped"] = n_before - stats["evidence"]

    def _write_passages(self, cur, b: IndexBundle, stats: dict) -> None:
        ids = [e.id for e in b.entities]
        cur.execute("SELECT DISTINCT ON (entity_id, snippet) entity_id, snippet, id FROM nav.evidence "
                    "WHERE entity_id = ANY(%s) AND field NOT IN ('name', 'email') ORDER BY entity_id, snippet, id", (ids,))
        ev_id = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        rows = []
        for p, vec in zip(b.passages, b.vectors):
            eid = None if p["kind"] == "profile" else ev_id.get((p["entity_id"], p["snippet"]))
            if p["kind"] == "evidence" and eid is None:
                raise StorageError("passage_without_evidence",
                                   f"evidence row missing for passage of {p['entity_id']}", backend=BACKEND)
            rows.append((p["entity_id"], eid, p["kind"], p["text"], np.asarray(vec, dtype=np.float32),
                         b.embed_model, p["source"], p["type"]))
        cur.executemany(
            "INSERT INTO nav.passage(entity_id, evidence_id, kind, text, embedding, embed_model, source, entity_type) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
        cur.execute("SELECT count(*) FROM nav.passage WHERE entity_id = ANY(%s)", (ids,))
        stats["passages_stored"] = cur.fetchone()[0]

    def _write_rejected(self, cur, b: IndexBundle, stats: dict) -> None:
        if b.scope:
            cur.execute("DELETE FROM nav.rejected_claim WHERE source = ANY(%s)", (b.scope,))
        else:
            cur.execute("DELETE FROM nav.rejected_claim")
        cur.executemany(
            "INSERT INTO nav.rejected_claim(source, url, field, value, snippet, reason, page_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,(SELECT id FROM nav.page WHERE url = %s))",
            [(r["source"], r["url"], r["field"], r.get("value", ""), r.get("snippet", ""),
              r.get("reason", "snippet_not_found"), r["url"]) for r in b.rejected])
        stats["rejected_claims"] = len(b.rejected)

    def _write_graph(self, cur, b: IndexBundle, stats: dict) -> None:
        if b.scope:
            _cypher(cur, "MATCH (n) WHERE n.source IN $src DETACH DELETE n", {"src": b.scope})
        else:
            _cypher(cur, "MATCH (n) DETACH DELETE n")
        for s in sorted({e.source for e in b.entities}):
            _cypher(cur, "MERGE (:Source {name: $name})", {"name": s})
        by_label: dict[str, list[dict]] = defaultdict(list)
        for e in b.entities:
            by_label[graph.LABEL[e.entity_type]].append({"id": e.id, "name": e.name, "source": e.source})
        for label, rows in by_label.items():
            for chunk in _batches(rows):
                _cypher(cur, f"UNWIND $rows AS r CREATE (:{label} {{entity_id: r.id, name: r.name, source: r.source}})",
                        {"rows": chunk})
                _cypher(cur, f"UNWIND $rows AS r MATCH (e:{label} {{entity_id: r.id}}), (s:Source {{name: r.source}}) "
                             "CREATE (e)-[:FROM_SOURCE]->(s)", {"rows": chunk})
        # structural edges: the same rules search.py uses (graph.link_pairs), typed by graph.EDGE_RULES
        etype = {e.id: graph.LABEL[e.entity_type] for e in b.entities}
        groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        try:
            edges = graph.typed_edges(b.entities)
        except ValueError as e:
            raise StorageError("graph_rule_missing", str(e), backend=BACKEND) from e
        for ed in edges:
            groups[(ed.rel, etype[ed.src], etype[ed.dst])].append({"s": ed.src, "d": ed.dst, "seq": ed.seq})
        for (rel, ls, ld), rows in groups.items():
            for chunk in _batches(rows):
                _cypher(cur, f"UNWIND $rows AS r MATCH (a:{ls} {{entity_id: r.s}}), (b:{ld} {{entity_id: r.d}}) "
                             f"CREATE (a)-[:{rel} {{seq: r.seq}}]->(b)", {"rows": chunk})
        stats["graph_edges"] = {rel: sum(len(r) for (g_rel, _, _), r in groups.items() if g_rel == rel)
                                for rel in graph.STRUCTURAL}
        # topics: one vertex per normalised expertise string, shared across sources
        topics: dict[str, str] = {}
        links: dict[str, list[dict]] = defaultdict(list)
        for e in b.entities:
            if e.entity_type == "infrastructure":
                continue
            for x in dict.fromkeys(graph.topic_key(t) for t in e.expertise):
                if x:
                    links[graph.LABEL[e.entity_type]].append({"id": e.id, "k": x})
            for t in e.expertise:
                topics.setdefault(graph.topic_key(t), t)
        topics.pop("", None)
        for chunk in _batches([{"k": k, "l": v} for k, v in topics.items()]):
            _cypher(cur, "UNWIND $rows AS r MERGE (t:Topic {key: r.k}) SET t.label = r.l", {"rows": chunk})
        for label, rows in links.items():
            for chunk in _batches(rows):
                _cypher(cur, f"UNWIND $rows AS r MATCH (e:{label} {{entity_id: r.id}}), (t:Topic {{key: r.k}}) "
                             "CREATE (e)-[:HAS_EXPERTISE]->(t)", {"rows": chunk})
        _cypher(cur, "MATCH (t:Topic) OPTIONAL MATCH (t)-[r]-() WITH t, count(r) AS c WHERE c = 0 DELETE t")
        stats["graph_edges"]["HAS_EXPERTISE"] = sum(len(r) for r in links.values())
        stats["topics"] = len(topics)

    # ---------------- read ----------------------------------------------------
    def version(self) -> str:
        with self.pg.op("version") as cur:
            cur.execute("SELECT count(*)::text || '@' || coalesce(max(updated_at)::text, '') FROM nav.entity")
            return cur.fetchone()[0]

    def load_entities(self) -> dict[str, Entity]:
        v = self.version()
        with self._lock:
            if self._cache and self._cache[0] == v:
                return self._cache[1]
        with self.pg.op("load_entities") as cur:
            cur.execute("SELECT id, entity_type, name, role, unit, institute, email, expertise, projects, infrastructure, "
                        "description, source, source_label, source_urls, retrieved_at, extractor "
                        "FROM nav.entity ORDER BY load_order, id")
            rows = cur.fetchall()
            cur.execute("SELECT entity_id, field, value, snippet, url FROM nav.evidence ORDER BY id")
            evs: dict[str, list[Evidence]] = defaultdict(list)
            for eid, f, val, snip, url in cur.fetchall():
                evs[eid].append(Evidence(field=f, value=val, snippet=snip, url=url))
        out: dict[str, Entity] = {}
        for (eid, et, name, role, unit, inst, email, exp, proj, infra, desc, src, slabel, urls, ret, extractor) in rows:
            out[eid] = Entity(id=eid, entity_type=et, name=name, role=role, unit=unit, institute=inst, email=email,
                              expertise=exp, projects=proj, infrastructure=infra, description=desc, source=src,
                              source_label=slabel, source_urls=urls, evidence=evs.get(eid, []),
                              retrieved_at=_iso(ret), extractor=extractor)
        with self._lock:
            self._cache = (v, out)
        return out

    def vector_search(self, qvec, limit, sources=None, types=None):
        """Best point per entity among the `limit` nearest passages (HNSW + iterative scan for filters)."""
        where = [sql.SQL("embed_model = %(model)s")]
        if sources:
            where.append(sql.SQL("source = ANY(%(sources)s)"))
        if types:
            where.append(sql.SQL("entity_type = ANY(%(types)s)"))
        q = sql.SQL(
            "WITH hits AS (SELECT entity_id, embedding <=> %(v)s AS dist FROM nav.passage WHERE {w} "
            "ORDER BY embedding <=> %(v)s LIMIT %(n)s) "
            "SELECT entity_id, 1 - min(dist) AS cos FROM hits GROUP BY entity_id ORDER BY cos DESC, entity_id"
        ).format(w=sql.SQL(" AND ").join(where))
        ef = min(1000, max(settings.pg_ef_search, limit))
        with self.pg.op("vector_search") as cur:
            cur.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(ef)))
            cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            cur.execute(q, {"v": np.asarray(qvec, dtype=np.float32), "n": limit, "model": settings.embed_model,
                            "sources": sources, "types": types})
            return [(r[0], float(r[1])) for r in cur.fetchall()]

    def lexical_rank(self, tokens, top=100):
        """FTS replacement for BM25: OR over the query tokens, ts_rank on entity fields + distinct snippets."""
        if not tokens:
            return [], 0.0
        tsq = " | ".join(dict.fromkeys(tokens))  # tokens are \\w{2,}: no tsquery operators inside
        with self.pg.op("lexical_rank") as cur:
            cur.execute(
                "WITH q AS (SELECT to_tsquery(%(cfg)s::regconfig, %(q)s) AS q), "
                "s AS (SELECT e.id, ts_rank(e.tsv, q.q) AS r FROM nav.entity e, q WHERE e.tsv @@ q.q "
                "      UNION ALL "
                "      SELECT d.entity_id, ts_rank(d.tsv, q.q) FROM "
                "        (SELECT DISTINCT ON (entity_id, md5(snippet)) entity_id, tsv FROM nav.evidence, q "
                "         WHERE tsv @@ q.q) d, q) "
                "SELECT id, sum(r) AS score FROM s GROUP BY id ORDER BY score DESC, id LIMIT %(n)s",
                {"cfg": FTS_CONFIG, "q": tsq, "n": top})
            rows = cur.fetchall()
        return [r[0] for r in rows if r[1] > 0], float(rows[0][1]) if rows else 0.0

    def neighbors(self, ids):
        """Structural neighbours via Cypher, ordered like the file backend's adjacency list (edge seq)."""
        if not ids:
            return {}
        with self.pg.op("neighbors") as cur:
            _cypher(cur, "MATCH (a)-[r]-(b) WHERE a.entity_id IN $ids AND r.seq IS NOT NULL "
                         "RETURN a.entity_id, b.entity_id, r.seq", {"ids": list(ids)},
                    cols="a agtype, b agtype, seq agtype")
            rows = [(json.loads(a), json.loads(b_), int(json.loads(s))) for a, b_, s in cur.fetchall()]
        acc: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for a, b_, s in rows:
            acc[a].append((s, b_))
        return {i: list(dict.fromkeys(n for _, n in sorted(acc.get(i, [])))) for i in ids}

    # ---------------- papers (migration 0004) --------------------------------------
    def write_papers(self, works: list[Work], matches: list[AuthorMatch], chunks: dict[str, list[tuple[str, int, str]]]
                     ) -> dict:
        """Upsert papers, their entity links, their text chunks (embedding kept when the text is unchanged)
        and the author-match audit; then re-project the paper subgraph."""
        stats: dict = {}
        with self.pg.op("write_papers") as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_REINDEX_LOCK,))
            cur.executemany(
                "INSERT INTO nav.paper(id, doi, title, year, venue, abstract, authorships, topics, concepts, "
                "cited_by_count, referenced_works, is_oa, oa_status, pdf_url, landing_url, pmid, pmcid, pdf_sha1, "
                "fulltext_chars, fulltext_status, fetched_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                "doi = EXCLUDED.doi, title = EXCLUDED.title, year = EXCLUDED.year, venue = EXCLUDED.venue, "
                "abstract = EXCLUDED.abstract, authorships = EXCLUDED.authorships, topics = EXCLUDED.topics, "
                "concepts = EXCLUDED.concepts, cited_by_count = EXCLUDED.cited_by_count, "
                "referenced_works = EXCLUDED.referenced_works, is_oa = EXCLUDED.is_oa, oa_status = EXCLUDED.oa_status, "
                "pdf_url = EXCLUDED.pdf_url, landing_url = EXCLUDED.landing_url, pmid = EXCLUDED.pmid, "
                "pmcid = EXCLUDED.pmcid, pdf_sha1 = EXCLUDED.pdf_sha1, fulltext_chars = EXCLUDED.fulltext_chars, "
                "fulltext_status = EXCLUDED.fulltext_status, fetched_at = EXCLUDED.fetched_at",
                [(w.id, w.doi, w.title, w.year, w.venue, w.abstract,
                  Jsonb([a.model_dump() for a in w.authors]), Jsonb(w.topics), Jsonb(w.concepts), w.cited_by_count,
                  w.referenced_works, w.is_oa, w.oa_status, w.pdf_url, w.landing_url, w.pmid, w.pmcid, w.pdf_sha1,
                  w.fulltext_chars, w.fulltext_status, w.fetched_at) for w in works])
            ids = [w.id for w in works]
            cur.execute("SELECT id FROM nav.entity WHERE id = ANY(%s)",
                        (sorted({l.entity_id for w in works for l in w.links}),))
            known = {r[0] for r in cur.fetchall()}
            cur.execute("DELETE FROM nav.paper_author WHERE paper_id = ANY(%s)", (ids,))
            rows = [(w.id, l.entity_id, l.relation, l.position, l.author_id, l.page_url)
                    for w in works for l in w.links if l.entity_id in known]
            cur.executemany("INSERT INTO nav.paper_author(paper_id, entity_id, relation, position, openalex_author_id, "
                            "page_url) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
            stats["paper_authors"] = len(rows)
            stats["links_to_unknown_entities"] = sum(1 for w in works for l in w.links if l.entity_id not in known)
            crow = [(pid, kind, no, text) for pid, cs in chunks.items() for kind, no, text in cs]
            cur.execute("DELETE FROM nav.paper_chunk c WHERE c.paper_id = ANY(%s) AND NOT EXISTS ("
                        "SELECT 1 FROM unnest(%s::text[], %s::text[], %s::int[]) AS n(p, k, i) "
                        "WHERE n.p = c.paper_id AND n.k = c.kind AND n.i = c.chunk_no)",
                        (list(chunks), [r[0] for r in crow], [r[1] for r in crow], [r[2] for r in crow]))
            cur.executemany(
                "INSERT INTO nav.paper_chunk AS c (paper_id, kind, chunk_no, text) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (paper_id, kind, chunk_no) DO UPDATE SET text = EXCLUDED.text, "
                "embedding = CASE WHEN c.text_md5 = md5(EXCLUDED.text) THEN c.embedding END, "
                "embed_model = CASE WHEN c.text_md5 = md5(EXCLUDED.text) THEN c.embed_model END", crow)
            stats["chunks"] = len(crow)
            cur.executemany(
                "INSERT INTO nav.author_match(entity_id, entity_name, candidates, chosen_author_id, decided_by, reason, "
                "model) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [(m.entity_id, m.entity_name, Jsonb(m.candidates), m.chosen_author_id, m.decided_by, m.reason, m.model)
                 for m in matches])
            stats["author_matches"] = len(matches)
            self._write_paper_graph(cur, stats)
        stats["papers"] = len(works)
        return stats

    def chunks_to_embed(self, model: str, limit: int = 512) -> list[tuple[int, str]]:
        with self.pg.op("chunks_to_embed") as cur:
            cur.execute("SELECT id, text FROM nav.paper_chunk WHERE embedding IS NULL OR embed_model IS DISTINCT FROM %s "
                        "ORDER BY id LIMIT %s", (model, limit))
            return cur.fetchall()

    def write_chunk_embeddings(self, rows: list[tuple[int, np.ndarray]], model: str) -> None:
        if rows and len(rows[0][1]) != DIM:
            raise StorageError("embedding_dim_mismatch", f"{model} gives {len(rows[0][1])} dims, need {DIM}",
                               backend=BACKEND)
        with self.pg.op("write_chunk_embeddings") as cur:
            cur.executemany("UPDATE nav.paper_chunk SET embedding = %s, embed_model = %s WHERE id = %s",
                            [(np.asarray(v, dtype=np.float32), model, i) for i, v in rows])

    def refresh_vectors(self, model: str) -> dict:
        """paper.embedding = normalise(mean(abstract) + mean(fulltext)); research profile of a person =
        normalised mean of its papers' vectors (both relations)."""
        with self.pg.op("refresh_vectors") as cur:
            cur.execute(
                "WITH a AS (SELECT paper_id, avg(embedding) FILTER (WHERE kind = 'abstract') AS va, "
                "                  avg(embedding) FILTER (WHERE kind = 'fulltext') AS vf "
                "           FROM nav.paper_chunk WHERE embedding IS NOT NULL AND embed_model = %(m)s GROUP BY paper_id) "
                "UPDATE nav.paper p SET embedding = l2_normalize(CASE WHEN a.va IS NULL THEN a.vf "
                "    WHEN a.vf IS NULL THEN a.va ELSE a.va + a.vf END), embed_model = %(m)s "
                "FROM a WHERE p.id = a.paper_id", {"m": model})
            n_papers = cur.rowcount
            cur.execute("DELETE FROM nav.research_profile")
            cur.execute(
                "INSERT INTO nav.research_profile(entity_id, embedding, embed_model, n_papers) "
                "SELECT d.entity_id, l2_normalize(avg(p.embedding)), %(m)s, count(*) FROM "
                "  (SELECT DISTINCT pa.entity_id, pa.paper_id FROM nav.paper_author pa "
                "   JOIN nav.entity e ON e.id = pa.entity_id WHERE e.entity_type = 'person') d "
                "JOIN nav.paper p ON p.id = d.paper_id WHERE p.embedding IS NOT NULL AND p.embed_model = %(m)s "
                "GROUP BY d.entity_id", {"m": model})
            n_people = cur.rowcount
            cur.execute("ANALYZE nav.paper_chunk")
            cur.execute("ANALYZE nav.paper")
            cur.execute("ANALYZE nav.research_profile")
        return {"paper_vectors": n_papers, "research_profiles": n_people}

    def knn_candidates(self, kind: str, k: int) -> list[tuple[str, str, float]]:
        """Directed kNN pairs (a, b, cosine) through the HNSW index: person research profiles or paper vectors."""
        table, key = {"person": ("nav.research_profile", "entity_id"), "paper": ("nav.paper", "id")}[kind]
        q = sql.SQL(
            "SELECT a.{key}, n.{key}, 1 - n.dist FROM {t} a CROSS JOIN LATERAL ("
            "  SELECT b.{key}, b.embedding <=> a.embedding AS dist FROM {t} b "
            "  WHERE b.{key} <> a.{key} AND b.embedding IS NOT NULL AND b.embed_model = a.embed_model "
            "  ORDER BY b.embedding <=> a.embedding LIMIT %(k)s) n "
            "WHERE a.embedding IS NOT NULL AND a.embed_model = %(m)s ORDER BY 1, 3 DESC"
        ).format(key=sql.Identifier(key), t=sql.SQL(table))
        with self.pg.op("knn_candidates") as cur:
            cur.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(max(settings.pg_ef_search, 4 * k))))
            cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            cur.execute(q, {"k": k, "m": settings.embed_model})
            return [(a, b, float(s)) for a, b, s in cur.fetchall()]

    def write_similarity(self, kind: str, method: str, threshold: float, edges: list[tuple[str, str, float]]) -> None:
        with self.pg.op("write_similarity") as cur:
            cur.execute("DELETE FROM nav.similarity WHERE kind = %s", (kind,))
            cur.executemany("INSERT INTO nav.similarity(kind, a, b, score, method, threshold) "
                            "VALUES (%s,%s,%s,%s,%s,%s)", [(kind, a, b, s, method, threshold) for a, b, s in edges])

    def existing_topics(self) -> list[tuple[str, str]]:
        """(key, label) of the Topic vertices: the whitelist the LLM chooses from."""
        with self.pg.op("existing_topics") as cur:
            _cypher(cur, "MATCH (t:Topic) RETURN t.key, t.label", cols="k agtype, l agtype")
            return sorted((json.loads(k), json.loads(l) if l else json.loads(k)) for k, l in cur.fetchall())

    def paper_topics(self) -> list[tuple[str, list[dict]]]:
        with self.pg.op("paper_topics") as cur:
            cur.execute("SELECT id, topics FROM nav.paper ORDER BY id")
            return cur.fetchall()

    def topic_map(self) -> dict[str, str]:
        with self.pg.op("topic_map") as cur:
            cur.execute("SELECT openalex_topic_id, topic_key FROM nav.topic_map")
            return dict(cur.fetchall())

    def write_topics(self, decisions: list[dict], paper_rows: list[tuple[str, str, float | None]]) -> dict:
        """decisions: new nav.topic_map rows; paper_rows: (paper_id, topic_key, score), replacing all paper topics."""
        stats: dict = {}
        with self.pg.op("write_topics") as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_REINDEX_LOCK,))
            cur.executemany(
                "INSERT INTO nav.topic_map(openalex_topic_id, openalex_label, topic_key, topic_label, is_new, decided_by, "
                "reason, candidates) VALUES (%(id)s,%(label)s,%(key)s,%(topic_label)s,%(is_new)s,%(by)s,%(reason)s,"
                "%(cands)s) ON CONFLICT (openalex_topic_id) DO UPDATE SET topic_key = EXCLUDED.topic_key, "
                "topic_label = EXCLUDED.topic_label, is_new = EXCLUDED.is_new, decided_by = EXCLUDED.decided_by, "
                "reason = EXCLUDED.reason, candidates = EXCLUDED.candidates, decided_at = now()",
                [{**d, "cands": Jsonb(d["cands"])} for d in decisions])
            cur.execute("DELETE FROM nav.paper_topic")
            cur.executemany("INSERT INTO nav.paper_topic(paper_id, topic_key, score) VALUES (%s,%s,%s) "
                            "ON CONFLICT DO NOTHING", paper_rows)
            stats["paper_topics"] = len(paper_rows)
            self._write_paper_graph(cur, stats)
        return stats

    def write_paper_graph(self) -> dict:
        stats: dict = {}
        with self.pg.op("write_paper_graph") as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_REINDEX_LOCK,))
            self._write_paper_graph(cur, stats)
        return stats

    def _write_paper_graph(self, cur, stats: dict) -> None:
        """Project nav.paper* / nav.similarity into the AGE graph (idempotent: delete, then recreate)."""
        _cypher(cur, "MATCH (p:Paper) DETACH DELETE p")
        _cypher(cur, "MATCH ()-[r:SIMILAR_TO]->() DELETE r")
        _cypher(cur, "MATCH (t:Topic) WHERE t.origin = 'openalex' OPTIONAL MATCH (t)-[r]-() "
                     "WITH t, count(r) AS c WHERE c = 0 DELETE t")
        cur.execute("SELECT id, coalesce(doi, ''), title, coalesce(year, 0) FROM nav.paper ORDER BY id")
        papers = [{"id": i, "doi": d, "t": t, "y": y} for i, d, t, y in cur.fetchall()]
        for chunk in _batches(papers):
            _cypher(cur, "UNWIND $rows AS r CREATE (:Paper {paper_id: r.id, doi: r.doi, title: r.t, year: r.y})",
                    {"rows": chunk})
        cur.execute("SELECT pa.entity_id, pa.paper_id, coalesce(pa.position, -1), pa.openalex_author_id "
                    "FROM nav.paper_author pa JOIN nav.entity e ON e.id = pa.entity_id "
                    "WHERE pa.relation = 'author' AND e.entity_type = 'person' ORDER BY 1, 2")
        authored = [{"e": e, "p": p, "pos": pos, "au": au} for e, p, pos, au in cur.fetchall()]
        for chunk in _batches(authored):
            _cypher(cur, "UNWIND $rows AS r MATCH (a:Person {entity_id: r.e}), (p:Paper {paper_id: r.p}) "
                         "CREATE (a)-[:AUTHORED {position: r.pos, author_id: r.au}]->(p)", {"rows": chunk})
        cur.execute("SELECT DISTINCT p.id, r FROM nav.paper p, unnest(p.referenced_works) AS r "
                    "WHERE r IN (SELECT id FROM nav.paper) AND r <> p.id ORDER BY 1, 2")
        cites = [{"a": a, "b": b} for a, b in cur.fetchall()]
        for chunk in _batches(cites):
            _cypher(cur, "UNWIND $rows AS r MATCH (a:Paper {paper_id: r.a}), (b:Paper {paper_id: r.b}) "
                         "CREATE (a)-[:CITES]->(b)", {"rows": chunk})
        # topics: reuse existing Topic vertices, create the new ones the topic map asked for
        cur.execute("SELECT pt.paper_id, pt.topic_key, coalesce(pt.score, 0), "
                    "coalesce((SELECT topic_label FROM nav.topic_map m WHERE m.topic_key = pt.topic_key "
                    "          ORDER BY m.openalex_topic_id LIMIT 1), pt.topic_key) "
                    "FROM nav.paper_topic pt WHERE pt.paper_id IN (SELECT id FROM nav.paper) ORDER BY 1, 2")
        about = cur.fetchall()
        _cypher(cur, "MATCH (t:Topic) RETURN t.key", cols="k agtype")
        have = {json.loads(r[0]) for r in cur.fetchall()}
        new = {k: l for _, k, _, l in about if k not in have}
        for chunk in _batches([{"k": k, "l": l} for k, l in sorted(new.items())]):
            _cypher(cur, "UNWIND $rows AS r CREATE (:Topic {key: r.k, label: r.l, origin: 'openalex'})", {"rows": chunk})
        for chunk in _batches([{"p": p, "k": k, "s": float(s)} for p, k, s, _ in about]):
            _cypher(cur, "UNWIND $rows AS r MATCH (p:Paper {paper_id: r.p}), (t:Topic {key: r.k}) "
                         "CREATE (p)-[:ABOUT {score: r.s}]->(t)", {"rows": chunk})
        sim: dict[str, int] = {}
        for kind, label, key in (("person", "Person", "entity_id"), ("paper", "Paper", "paper_id")):
            cur.execute("SELECT a, b, score, method FROM nav.similarity WHERE kind = %s ORDER BY a, b", (kind,))
            rows = [{"a": a, "b": b, "s": float(s), "m": m} for a, b, s, m in cur.fetchall()]
            for chunk in _batches(rows):
                _cypher(cur, f"UNWIND $rows AS r MATCH (a:{label} {{{key}: r.a}}), (b:{label} {{{key}: r.b}}) "
                             "CREATE (a)-[:SIMILAR_TO {score: r.s, method: r.m}]->(b)", {"rows": chunk})
            sim[kind] = len(rows)
        stats["paper_graph"] = {"Paper": len(papers), "AUTHORED": len(authored), "CITES": len(cites),
                                "ABOUT": len(about), "new_topics": len(new), "SIMILAR_TO": sim}

    # ---------------- papers: read side (search) -----------------------------------------
    def has_paper_vectors(self) -> bool:
        with self.pg.op("has_paper_vectors") as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM nav.paper_chunk WHERE embedding IS NOT NULL)")
            return bool(cur.fetchone()[0])

    _HIT_COLS = ("SELECT DISTINCT ON (pa.entity_id) pa.entity_id, 1 - h.dist, p.id, p.title, p.year, "
                 "coalesce('https://doi.org/' || p.doi, p.landing_url, 'https://openalex.org/' || p.id), c.kind, "
                 "c.text, pa.relation, p.fetched_at ")

    def _hits(self, cur) -> dict[str, PaperHit]:
        return {r[0]: PaperHit(entity_id=r[0], cos=float(r[1]), paper_id=r[2], title=r[3], year=r[4], url=r[5],
                               kind=r[6], text=r[7], relation=r[8], fetched_at=_iso(r[9]))
                for r in cur.fetchall()}

    def paper_hits(self, qvec, limit: int = 200) -> dict[str, PaperHit]:
        """Best chunk per entity among the `limit` chunks nearest to the query (HNSW + iterative scan)."""
        with self.pg.op("paper_hits") as cur:
            cur.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(
                sql.Literal(min(1000, max(settings.pg_ef_search, limit)))))
            cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            cur.execute(
                "WITH h AS (SELECT id, paper_id, embedding <=> %(v)s AS dist FROM nav.paper_chunk "
                "           WHERE embed_model = %(m)s ORDER BY embedding <=> %(v)s LIMIT %(n)s) "
                + self._HIT_COLS +
                "FROM h JOIN nav.paper_author pa ON pa.paper_id = h.paper_id JOIN nav.paper p ON p.id = h.paper_id "
                "JOIN nav.paper_chunk c ON c.id = h.id ORDER BY pa.entity_id, h.dist, p.id, c.id",
                {"v": np.asarray(qvec, dtype=np.float32), "m": settings.embed_model, "n": limit})
            return self._hits(cur)

    def paper_best_for(self, qvec, ids: list[str]) -> dict[str, PaperHit]:
        """Exact best chunk of the given entities (people reached through SIMILAR_TO)."""
        if not ids:
            return {}
        with self.pg.op("paper_best_for") as cur:
            cur.execute(
                "WITH h AS (SELECT c.id, c.paper_id, c.embedding <=> %(v)s AS dist FROM nav.paper_chunk c "
                "           WHERE c.embed_model = %(m)s AND c.paper_id IN "
                "             (SELECT paper_id FROM nav.paper_author WHERE entity_id = ANY(%(ids)s))) "
                + self._HIT_COLS +
                "FROM h JOIN nav.paper_author pa ON pa.paper_id = h.paper_id AND pa.entity_id = ANY(%(ids)s) "
                "JOIN nav.paper p ON p.id = h.paper_id JOIN nav.paper_chunk c ON c.id = h.id "
                "ORDER BY pa.entity_id, h.dist, p.id, c.id",
                {"v": np.asarray(qvec, dtype=np.float32), "m": settings.embed_model, "ids": list(ids)})
            return self._hits(cur)

    def similar_neighbors(self, ids: list[str]) -> dict[str, list[tuple[str, float]]]:
        """Person -> [(person, score)] along SIMILAR_TO, strongest first."""
        if not ids:
            return {}
        with self.pg.op("similar_neighbors") as cur:
            _cypher(cur, "MATCH (a:Person)-[r:SIMILAR_TO]-(b:Person) WHERE a.entity_id IN $ids "
                         "RETURN a.entity_id, b.entity_id, r.score", {"ids": list(ids)},
                    cols="a agtype, b agtype, s agtype")
            rows = [(json.loads(a), json.loads(b_), float(json.loads(s))) for a, b_, s in cur.fetchall()]
        out: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for a, b_, s in sorted(rows, key=lambda r: (r[0], -r[2], r[1])):
            out[a].append((b_, s))
        return dict(out)

@lru_cache(maxsize=4)
def _index_store(url: str) -> PgIndexStore:
    return PgIndexStore(_pg(url))


# =============================================================================
class PgCaseStore:
    name = "postgres"

    def __init__(self, pg: _Pg):
        self.pg = pg

    @classmethod
    def for_url(cls, url: str) -> "PgCaseStore":
        return _case_store(url)

    def save(self, case) -> None:
        with self.pg.op("case_save") as cur:
            cur.execute(
                'INSERT INTO nav."case"(id, created_at, updated_at, status, company, contact_name, contact_email, '
                "country, canton, area, niche, request_text, analysis, no_match_message, outreach) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                "updated_at = EXCLUDED.updated_at, status = EXCLUDED.status, company = EXCLUDED.company, "
                "contact_name = EXCLUDED.contact_name, contact_email = EXCLUDED.contact_email, country = EXCLUDED.country, "
                "canton = EXCLUDED.canton, area = EXCLUDED.area, niche = EXCLUDED.niche, "
                "request_text = EXCLUDED.request_text, analysis = EXCLUDED.analysis, "
                "no_match_message = EXCLUDED.no_match_message, outreach = EXCLUDED.outreach",
                (case.id, case.created_at, case.updated_at, case.status, case.company, case.contact_name,
                 case.contact_email, case.country, case.canton, case.area, case.niche, case.request_text,
                 Jsonb(case.analysis.model_dump(mode="json")), case.no_match_message, Jsonb(case.outreach)))
            cur.execute("DELETE FROM nav.case_match WHERE case_id = %s", (case.id,))
            cur.executemany(
                "INSERT INTO nav.case_match(case_id, entity_id, entity_ref, rank, name, entity_type, role, unit, "
                "institution, why, plain, url, contact, confidence, via, selected) "
                "VALUES (%s,(SELECT id FROM nav.entity WHERE id = %s),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(case.id, m.id, m.id, i, m.name, m.entity_type, m.role, m.unit, m.institution, m.why,
                  m.plain or "", m.url, m.contact, m.confidence, m.via, m.selected)
                 for i, m in enumerate(case.matches)])
            cur.execute("DELETE FROM nav.case_event WHERE case_id = %s", (case.id,))
            cur.executemany("INSERT INTO nav.case_event(case_id, at, actor, kind, text) VALUES (%s,%s,%s,%s,%s)",
                            [(case.id, ev.at, ev.actor, ev.kind, ev.text) for ev in case.events])

    _CASE_COLS = ('id, created_at, updated_at, status, company, contact_name, contact_email, country, canton, area, '
                  'niche, request_text, analysis, no_match_message, outreach')

    def _load(self, cur, where: str, params: tuple) -> list:
        from .cases import Case, Event, Match
        cur.execute(f'SELECT {self._CASE_COLS} FROM nav."case" {where}', params)
        heads = cur.fetchall()
        if not heads:
            return []
        ids = [h[0] for h in heads]
        cur.execute("SELECT case_id, entity_ref, name, entity_type, role, unit, institution, why, plain, url, contact, "
                    "confidence, via, selected FROM nav.case_match WHERE case_id = ANY(%s) "
                    "ORDER BY case_id, rank", (ids,))
        matches: dict[str, list] = defaultdict(list)
        for (cid, ref, name, et, role, unit, inst, why, plain, url, contact, conf, via, sel) in cur.fetchall():
            matches[cid].append(Match(id=ref, name=name, entity_type=et, role=role, unit=unit, institution=inst,
                                      why=why, plain=plain or None, url=url or "", contact=contact, confidence=conf,
                                      via=via, selected=sel))
        cur.execute("SELECT case_id, at, actor, kind, text FROM nav.case_event WHERE case_id = ANY(%s) ORDER BY case_id, id",
                    (ids,))
        events: dict[str, list] = defaultdict(list)
        for cid, at, actor, kind, text in cur.fetchall():
            events[cid].append(Event(at=_iso(at, seconds=True), actor=actor, kind=kind, text=text))
        out = []
        for (cid, created, updated, status, company, cname, cemail, country, canton, area, niche, req, analysis,
             nomatch, outreach) in heads:
            out.append(Case(id=cid, created_at=_iso(created, seconds=True), updated_at=_iso(updated, seconds=True),
                            status=status, company=company, contact_name=cname, contact_email=cemail, country=country,
                            canton=canton, area=area, niche=niche, request_text=req, analysis=analysis, matches=matches.get(cid, []),
                            no_match_message=nomatch,
                            outreach=outreach or {}, events=events.get(cid, [])))
        return out

    def get(self, cid: str):
        with self.pg.op("case_get") as cur:
            got = self._load(cur, "WHERE id = %s", (cid,))
        return got[0] if got else None

    def list(self) -> list:
        with self.pg.op("case_list") as cur:
            return self._load(cur, "ORDER BY updated_at DESC", ())

    def delete(self, cid: str) -> None:
        with self.pg.op("case_delete") as cur:
            cur.execute('DELETE FROM nav."case" WHERE id = %s', (cid,))


@lru_cache(maxsize=4)
def _case_store(url: str) -> PgCaseStore:
    return PgCaseStore(_pg(url))
