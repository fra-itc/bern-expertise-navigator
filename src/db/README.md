# bern-db: PostgreSQL 18 + pgvector + Apache AGE

> Deployed on the team server at /opt/bern/db — see docs/server-handoff.md.

The single database for the Bern Expertise Navigator. It replaces the YAML files, the entities JSON,
SQLite, Qdrant/NumPy and the BM25 pickle.

## Architecture

- Immagine `bern-pg:18-age1.8.0-vec0.8.6`: `apache/age:release_PG18_1.8.0` (PG 18.6, AGE 1.8.0) + `postgresql-18-pgvector=0.8.6-1.pgdg13+1`.
  The `initdb/` scripts are copied into the image and run **only on first start** (empty volume). Later schema changes are made with migrations recorded in `nav.schema_migrations`. Migration files live in `migrations/` (e.g. `0002_remove_technical_review.sql`, which drops the former technical-review columns and statuses); apply them as `postgres` on databases created before the change.
- A single `db` service. The port is published only on `127.0.0.1:${PG_HOST_PORT:-5432}`. It uses the `pgdata` volume (mounted at `/var/lib/postgresql`, PG18 layout) and the `bern` network, which the app containers join.
- AGE is in `shared_preload_libraries`: no `LOAD 'age'` needed. The `bern_app` role has `search_path = nav, ag_catalog, public`.
- Roles:
  - `postgres`: owner and DDL.
  - `bern_app`: LOGIN, not superuser. Can run DML and MAINTAIN on `nav` and on the label tables of `expertise_graph`. Cannot run DDL: it cannot create tables or new graph labels.
- Tuning for 8 vCPU / 15 GB shared with the app:
  - `shared_buffers=3GB`, `effective_cache_size=8GB`, `work_mem=32MB`;
  - `maintenance_work_mem=1GB` and `max_parallel_maintenance_workers=4`, for the HNSW build;
  - `shm_size=2gb`, because the parallel HNSW build uses POSIX DSM.

  All of these values can be changed in `.env`.

## From current files to tables

| Before | Now |
|---|---|
| `sources/*.yaml` | `nav.source` |
| pagine crawl (`Page`) | `nav.page` |
| entities JSON (`Entity`) | `nav.entity` (with generated `tsv`: simple+unaccent, weights A/B/C; trigram on `name`) |
| `Entity.evidence[]` | `nav.evidence` (FK entity, optional FK page, `tsv` on the snippet) |
| rejected claims | `nav.rejected_claim` (+ `reason`) |
| Qdrant / NumPy | `nav.passage` (`vector(768)` cosine, HNSW m=16 ef_c=64; `source`/`entity_type` denormalized) |
| BM25 pickle | Postgres FTS (`nav.entity.tsv`, `nav.evidence.tsv`) |
| SQLite cases (JSON blob) | `nav."case"`, `nav.case_match`, `nav.case_event` |
| implicit graph (same name/same source, `link_site_structure`, `derive_units`) | AGE graph `expertise_graph` |

Graph:
- Vertices:
  - `Person`, `Unit`, `Project`, `Infrastructure`, with properties `entity_id` (= `nav.entity.id`), `name` and `source`;
  - `Source`, with property `name`;
  - `Topic`, with properties `key` and `label`.
- Edges:
  - `MEMBER_OF`: person->unit;
  - `WORKS_ON`: person->project;
  - `PART_OF`: project->unit e unit->unit;
  - `OPERATES`: unit->infrastructure;
  - `FROM_SOURCE`: entity->source;
  - `HAS_EXPERTISE`: ->topic.

Papers (migration `0004_papers`, filled by `navigator.cli papers`):
- Tables (source of truth): `nav.paper` (OpenAlex work: doi, title, year, venue, abstract, authorships, topics,
  cited_by_count, referenced_works, OA status, `pdf_url`/`pdf_sha1`, `embedding`), `nav.paper_author` (paper↔entity,
  `relation` `author` with position + OpenAlex author id, or `page_link`), `nav.paper_chunk` (abstract + full-text
  chunks, `vector(768)`, HNSW), `nav.research_profile` (person = normalised mean of its papers, HNSW),
  `nav.author_match` (audit of every person↔author decision: candidates, choice, reason, `llm`/`rules`, model),
  `nav.topic_map` (OpenAlex topic → Topic key, decided once), `nav.paper_topic`, `nav.similarity` (kNN edges, `a < b`,
  score, method, threshold).
- Graph projection, rebuilt from those tables by `papers link` and after **every** reindex:
  - vertex `Paper` (`paper_id`, `doi`, `title`, `year`);
  - `AUTHORED`: person->paper (`position`, `author_id`);
  - `ABOUT`: paper->topic (`score`); topics created for papers carry `origin: 'openalex'`;
  - `CITES`: paper->paper, only between known papers;
  - `SIMILAR_TO`: person-person and paper-paper (`score`, `method`), from embeddings.
- Why `nav.paper_chunk` and not `nav.passage`: a chunk belongs to a paper with n authors; in `nav.passage` it would need
  a NULL `entity_id` or one copy per author, and every existing passage query would have to learn to skip it.

Why `Topic` is a vertex: today expertise values are free-form strings repeated in every entity. As vertices they become a meeting point: the query "who shares expertise with X" is a 2-hop. Synonyms can also be merged later, by letting the LLM choose from a list of existing Topics, with no alias dictionaries. `key` is the normalized form (lowercase, accent-free), `label` is the original text.

## Getting started

```bash
cp .env.example .env    # put the real passwords in
docker compose build
docker compose up -d
docker compose ps       # must show (healthy)
```

To connect the app, add it to the `bern` network (`networks: { bern: { external: true } }`) and use this connection string:
`postgresql://bern_app:<APP_DB_PASSWORD>@db:5432/bern`.

For remote access, through an SSH tunnel:

```bash
ssh -L 5432:127.0.0.1:5432 deploy@116.203.127.208
psql "postgresql://bern_app@127.0.0.1:5432/bern"
```

## Example queries (as `bern_app`)

Vector search filtered by source, keeping the best point per entity. `$1` is the normalized e5 embedding of the query, `"query: ..."`.

```sql
SET hnsw.ef_search = 100;
SET hnsw.iterative_scan = relaxed_order;   -- pgvector 0.8: the filter does not empty the top-k
WITH hits AS (
  SELECT entity_id, kind, text, embedding <=> $1 AS dist
  FROM nav.passage WHERE source = $2
  ORDER BY embedding <=> $1 LIMIT 100)
SELECT DISTINCT ON (entity_id) entity_id, kind, text, 1 - dist AS cos_sim
FROM hits ORDER BY entity_id, dist;        -- then re-sort by cos_sim in the app or in an outer SELECT
```

FTS, which replaces BM25. With unaccent, `zurich` finds `Zürich`.

```sql
SELECT id, name, ts_rank(tsv, q) AS rank
FROM nav.entity, websearch_to_tsquery('nav.simple_unaccent', $1) q
WHERE tsv @@ q ORDER BY rank DESC LIMIT 20;
-- fuzzy match on name
SELECT id, name, similarity(name, $1) FROM nav.entity WHERE name % $1 ORDER BY 3 DESC;
```

Cypher 1-hop, unit -> people:

```sql
SELECT * FROM cypher('expertise_graph', $$
  MATCH (p:Person)-[:MEMBER_OF]->(u:Unit {entity_id: 'a1b2c3d4e5f60001'})
  RETURN p.entity_id, p.name $$) AS (entity_id agtype, name agtype);
```

Hybrid graph+vector query: members of a unit ordered by similarity to the query. `agtype::text` strips the quotes.

```sql
WITH members AS (
  SELECT g.entity_id::text AS id FROM cypher('expertise_graph', $$
    MATCH (p:Person)-[:MEMBER_OF]->(:Unit {entity_id: 'a1b2c3d4e5f60001'}) RETURN p.entity_id
  $$) AS g(entity_id agtype))
SELECT e.id, e.name, e.role, 1 - min(ps.embedding <=> $1) AS best_sim
FROM members m JOIN nav.passage ps ON ps.entity_id = m.id JOIN nav.entity e ON e.id = m.id
GROUP BY e.id, e.name, e.role ORDER BY best_sim DESC;
```

Papers. Authors whose research is closest to a person (`SIMILAR_TO`), and the shared topics through papers:

```sql
SELECT * FROM cypher('expertise_graph', $$
  MATCH (p:Person {entity_id: 'a1b2c3d4e5f60001'})-[s:SIMILAR_TO]-(o:Person)
  RETURN o.name, s.score ORDER BY s.score DESC $$) AS (name agtype, score agtype);

SELECT * FROM cypher('expertise_graph', $$
  MATCH (p:Person {entity_id: 'a1b2c3d4e5f60001'})-[:AUTHORED]->(w:Paper)-[:ABOUT]->(t:Topic)<-[:HAS_EXPERTISE]-(o)
  RETURN DISTINCT t.label, o.name $$) AS (topic agtype, name agtype);
```

Best paper chunk per author for a query (what search uses as `publication` evidence):

```sql
WITH h AS (SELECT id, paper_id, embedding <=> $1 AS dist FROM nav.paper_chunk ORDER BY embedding <=> $1 LIMIT 200)
SELECT DISTINCT ON (pa.entity_id) pa.entity_id, 1 - h.dist AS cos, p.title, 'https://doi.org/' || p.doi AS url, c.text
FROM h JOIN nav.paper_author pa USING (paper_id) JOIN nav.paper p ON p.id = h.paper_id JOIN nav.paper_chunk c ON c.id = h.id
ORDER BY pa.entity_id, h.dist;
```

Audit of the author matching:

```sql
SELECT DISTINCT ON (entity_id) entity_name, decided_by, chosen_author_id, reason, jsonb_array_length(candidates)
FROM nav.author_match ORDER BY entity_id, decided_at DESC;
```

Planner note: with few rows and a weakly selective filter, Postgres may prefer a bitmap scan on the `source` index followed by an exact sort. This is correct, because at that scale it is faster. The HNSW index comes into play when the table grows or when the query has no filter. After a bulk load run `ANALYZE nav.passage;`: `bern_app` has the MAINTAIN privilege.

## Migrations

`initdb/` runs only on an empty volume. Later schema changes are versioned SQL files in `migrations/`
(`0002_*.sql`, ...), each one wrapped in a transaction and recording itself in `nav.schema_migrations`.

- Fresh volume: the image copies `migrations/` to `/migrations` and `initdb/06-migrations.sh` applies them in order.
- Existing database: apply each new file once, as the owner:

  ```bash
  docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0002_index_order_and_match_ref.sql
  docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0003_case_search_filters.sql
  docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0004_papers.sql
  ```

The app (`navigator/pgstore.py`) checks `nav.schema_migrations` at connect time and refuses to start
with a `schema_outdated` error if a migration it needs is missing.

| Version | What |
|---|---|
| `0002_index_order_and_match_ref` | `nav.entity.load_order` (input order, for identical tie-breaks with the file backend); `nav.case_match.entity_ref` (match id survives a reindex that drops the entity) |
| `0002_remove_technical_review` | (team, main) end of the technical-review step: open review statuses become `new`, status CHECK narrowed to `new/contacted/call_scheduled/closed`, review columns **dropped**. Already part of the fresh `initdb/` schema (registered by `05-migrations.sql`); not required by the app |
| `0003_case_search_filters` | `nav."case".canton/area/niche` (search-first request filters, `config/medtech_areas.yaml` ids) + index `(area, niche)`; on databases that still have the review columns they become nullable and unused (nothing dropped) |
| `0004_papers` | papers: `nav.paper`, `paper_author`, `paper_chunk` (HNSW), `research_profile` (HNSW), `author_match`, `topic_map`, `paper_topic`, `similarity`; graph labels `Paper`, `AUTHORED`, `ABOUT`, `CITES`, `SIMILAR_TO` (+ indexes, grants to `bern_app`). Additive and idempotent |

Order on an existing database: `0002_index_order_and_match_ref`, `0003_case_search_filters`, then `0004_papers` (all
three required by the app).
`0002_remove_technical_review` is independent and destructive (drops the review columns): take a backup first
(see below) if that data matters.

## Backup and restore

```bash
docker compose exec -T db pg_dump -U postgres -d bern -Fc > bern_$(date +%F).dump
docker compose exec -T db pg_restore -U postgres -d bern --clean --if-exists < bern_YYYY-MM-DD.dump
```

**After every restore, realign the AGE catalog** (once, as `postgres`):

```bash
docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < post-restore-age.sql
```

AGE stores the graph schema OID as a plain `oid` (`ag_graph.graphid`, `ag_label.graph`). A restore recreates the schema
`expertise_graph` with a new OID, so `cypher()` fails with `graph with oid NNNNN does not exist` until the catalog is
realigned. Tables, vectors and FTS are unaffected. Running the script again is a no-op.

The dump includes both the `nav` schema and the AGE graph (the `expertise_graph` schema and `ag_catalog.ag_graph`/`ag_label`). To restore into an empty DB, first run `CREATE EXTENSION age; CREATE EXTENSION vector;`, which initdb already does.

## Local test (Docker Desktop)

```bash
docker compose -p bern-db-test build
docker compose -p bern-db-test up -d    # with PG_HOST_PORT=55432 in .env
docker compose -p bern-db-test down -v
```
