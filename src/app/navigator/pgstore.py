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
from .schema import Entity, Evidence
from .storage import IndexBundle, StorageError

BACKEND = "postgres"
GRAPH = "expertise_graph"
DIM = 768
FTS_CONFIG = "nav.simple_unaccent"
# 0002_remove_technical_review (main) is not required: the store neither reads nor writes the review columns.
REQUIRED_MIGRATIONS = ("0001_initial", "0002_index_order_and_match_ref", "0003_case_search_filters",
                       "0005_case_company_sources")
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
                "country, canton, area, niche, request_text, analysis, no_match_message, outreach, "
                "city, understood, company_url, need, website, documents) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                "updated_at = EXCLUDED.updated_at, status = EXCLUDED.status, company = EXCLUDED.company, "
                "contact_name = EXCLUDED.contact_name, contact_email = EXCLUDED.contact_email, country = EXCLUDED.country, "
                "canton = EXCLUDED.canton, area = EXCLUDED.area, niche = EXCLUDED.niche, "
                "request_text = EXCLUDED.request_text, analysis = EXCLUDED.analysis, "
                "no_match_message = EXCLUDED.no_match_message, outreach = EXCLUDED.outreach, city = EXCLUDED.city, "
                "understood = EXCLUDED.understood, company_url = EXCLUDED.company_url, need = EXCLUDED.need, "
                "website = EXCLUDED.website, documents = EXCLUDED.documents",
                (case.id, case.created_at, case.updated_at, case.status, case.company, case.contact_name,
                 case.contact_email, case.country, case.canton, case.area, case.niche, case.request_text,
                 Jsonb(case.analysis.model_dump(mode="json")), case.no_match_message, Jsonb(case.outreach),
                 case.city, Jsonb(case.understood), case.company_url, case.need,
                 Jsonb(case.website.model_dump(mode="json")) if case.website else None,
                 Jsonb([d.model_dump(mode="json") for d in case.documents])))
            cur.execute("DELETE FROM nav.case_match WHERE case_id = %s", (case.id,))
            cur.executemany(
                "INSERT INTO nav.case_match(case_id, entity_id, entity_ref, rank, name, entity_type, role, unit, "
                "institution, why, plain, url, contact, confidence, via, selected, archetype) "
                "VALUES (%s,(SELECT id FROM nav.entity WHERE id = %s),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(case.id, m.id, m.id, i, m.name, m.entity_type, m.role, m.unit, m.institution, m.why,
                  m.plain or "", m.url, m.contact, m.confidence, m.via, m.selected, m.archetype)
                 for i, m in enumerate(case.matches)])
            cur.execute("DELETE FROM nav.case_event WHERE case_id = %s", (case.id,))
            cur.executemany("INSERT INTO nav.case_event(case_id, at, actor, kind, text) VALUES (%s,%s,%s,%s,%s)",
                            [(case.id, ev.at, ev.actor, ev.kind, ev.text) for ev in case.events])

    _CASE_COLS = ('id, created_at, updated_at, status, company, contact_name, contact_email, country, canton, area, '
                  'niche, request_text, analysis, no_match_message, outreach, city, understood, company_url, need, website, '
                  'documents')

    def _load(self, cur, where: str, params: tuple) -> list:
        from .cases import Case, Event, Match
        cur.execute(f'SELECT {self._CASE_COLS} FROM nav."case" {where}', params)
        heads = cur.fetchall()
        if not heads:
            return []
        ids = [h[0] for h in heads]
        cur.execute("SELECT case_id, entity_ref, name, entity_type, role, unit, institution, why, plain, url, contact, "
                    "confidence, via, selected, archetype FROM nav.case_match WHERE case_id = ANY(%s) "
                    "ORDER BY case_id, rank", (ids,))
        matches: dict[str, list] = defaultdict(list)
        for (cid, ref, name, et, role, unit, inst, why, plain, url, contact, conf, via, sel, arch) in cur.fetchall():
            matches[cid].append(Match(id=ref, name=name, entity_type=et, role=role, unit=unit, institution=inst,
                                      why=why, plain=plain or None, url=url or "", contact=contact, confidence=conf,
                                      via=via, selected=sel, archetype=arch or ""))
        cur.execute("SELECT case_id, at, actor, kind, text FROM nav.case_event WHERE case_id = ANY(%s) ORDER BY case_id, id",
                    (ids,))
        events: dict[str, list] = defaultdict(list)
        for cid, at, actor, kind, text in cur.fetchall():
            events[cid].append(Event(at=_iso(at, seconds=True), actor=actor, kind=kind, text=text))
        out = []
        for (cid, created, updated, status, company, cname, cemail, country, canton, area, niche, req, analysis,
             nomatch, outreach, city, understood, curl, need, website, documents) in heads:
            out.append(Case(id=cid, created_at=_iso(created, seconds=True), updated_at=_iso(updated, seconds=True),
                            status=status, company=company, contact_name=cname, contact_email=cemail, country=country,
                            canton=canton, area=area, niche=niche, request_text=req, analysis=analysis, matches=matches.get(cid, []),
                            no_match_message=nomatch, city=city, understood=understood or [], company_url=curl,
                            need=need, website=website, documents=documents or [],
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
