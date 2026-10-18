-- 0004: academic papers (OpenAlex) of the indexed people, their embeddings and the embedding-derived graph.
-- Apply as the owner (postgres), once:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0004_papers.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; nothing existing is changed.
--
-- Design: the relational tables are the source of truth; the AGE vertices/edges (Paper, AUTHORED, ABOUT, CITES,
-- SIMILAR_TO) are a projection rebuilt from them (pgstore._write_paper_graph), also after every reindex.
-- Paper text lives in its own nav.paper_chunk (not nav.passage): a chunk belongs to a paper, which has n authors;
-- in nav.passage it would need a NULL entity_id or one copy per author, and every existing passage query (search
-- parity with the file backend, reindex deletes) would have to learn to skip it.
BEGIN;
SET LOCAL search_path = nav, public;

CREATE TABLE IF NOT EXISTS nav.paper (
  id               text PRIMARY KEY CHECK (id ~ '^W[0-9]+$'),       -- OpenAlex work id (short form)
  doi              text UNIQUE,                                     -- lowercase, without https://doi.org/
  title            text NOT NULL DEFAULT '',
  year             int,
  venue            text,
  abstract         text,                                            -- rebuilt from abstract_inverted_index
  authorships      jsonb NOT NULL DEFAULT '[]'::jsonb,              -- [{position, author_id, name, institutions, entity_id}]
  topics           jsonb NOT NULL DEFAULT '[]'::jsonb,              -- OpenAlex topics [{id, display_name, score, ...}]
  concepts         jsonb NOT NULL DEFAULT '[]'::jsonb,
  cited_by_count   int NOT NULL DEFAULT 0,
  referenced_works text[] NOT NULL DEFAULT '{}',                    -- short OpenAlex ids
  is_oa            boolean NOT NULL DEFAULT false,
  oa_status        text,
  pdf_url          text,                                            -- the OA PDF actually downloaded
  landing_url      text,
  pmid             text,
  pmcid            text,
  pdf_sha1         text CHECK (pdf_sha1 ~ '^[0-9a-f]{40}$'),         -- data/papers/pdf/<sha1>.pdf (sha1 of pdf_url)
  fulltext_chars   int,
  fulltext_status  text,
  embedding        vector(768),                                     -- normalised abstract (+ full-text mean)
  embed_model      text,
  fetched_at       timestamptz NOT NULL,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('nav.simple_unaccent'::regconfig, coalesce(title, '')), 'A')
     || setweight(to_tsvector('nav.simple_unaccent'::regconfig, coalesce(abstract, '')), 'B')) STORED
);
CREATE INDEX IF NOT EXISTS paper_tsv_idx ON nav.paper USING gin (tsv);
CREATE INDEX IF NOT EXISTS paper_embedding_hnsw ON nav.paper
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
DROP TRIGGER IF EXISTS paper_touch ON nav.paper;
CREATE TRIGGER paper_touch BEFORE UPDATE ON nav.paper FOR EACH ROW EXECUTE FUNCTION nav.touch_updated_at();

-- paper <-> entity: 'author' = an OpenAlex authorship of the entity's matched author (position = index in
-- authorships, 0-based); 'page_link' = the entity's own page links the work (paper_ref on the page).
CREATE TABLE IF NOT EXISTS nav.paper_author (
  paper_id            text NOT NULL REFERENCES nav.paper(id) ON DELETE CASCADE,
  entity_id           text NOT NULL REFERENCES nav.entity(id) ON DELETE CASCADE,
  relation            text NOT NULL CHECK (relation IN ('author', 'page_link')),
  position            int CHECK (position >= 0),
  openalex_author_id  text CHECK (openalex_author_id ~ '^A[0-9]+$'),
  page_url            text,
  PRIMARY KEY (paper_id, entity_id, relation),
  CHECK ((relation = 'author') = (openalex_author_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS paper_author_entity_idx ON nav.paper_author(entity_id);

-- Embedded text of a paper: chunk 0 of kind 'abstract' (title + abstract), 'fulltext' windows from the OA PDF.
-- embedding is NULL until `cli papers embed` fills it (incremental: only new/changed text is embedded).
CREATE TABLE IF NOT EXISTS nav.paper_chunk (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  paper_id     text NOT NULL REFERENCES nav.paper(id) ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('abstract', 'fulltext')),
  chunk_no     int NOT NULL CHECK (chunk_no >= 0),
  text         text NOT NULL,
  text_md5     text GENERATED ALWAYS AS (md5(text)) STORED,
  embedding    vector(768),
  embed_model  text,
  UNIQUE (paper_id, kind, chunk_no)
);
CREATE INDEX IF NOT EXISTS paper_chunk_embedding_hnsw ON nav.paper_chunk
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS paper_chunk_paper_idx ON nav.paper_chunk(paper_id);

-- "Research profile" of a person: normalised mean of the embeddings of its papers.
CREATE TABLE IF NOT EXISTS nav.research_profile (
  entity_id    text PRIMARY KEY REFERENCES nav.entity(id) ON DELETE CASCADE,
  embedding    vector(768) NOT NULL,
  embed_model  text NOT NULL,
  n_papers     int NOT NULL CHECK (n_papers > 0),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_profile_embedding_hnsw ON nav.research_profile
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Audit of every person <-> OpenAlex author decision (history kept; entity_id is a plain snapshot, no FK,
-- so the audit survives a reindex that drops the entity).
CREATE TABLE IF NOT EXISTS nav.author_match (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_id         text NOT NULL,
  entity_name       text NOT NULL,
  candidates        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- what the matcher saw (compact OpenAlex cards)
  chosen_author_id  text CHECK (chosen_author_id ~ '^A[0-9]+$'),
  decided_by        text NOT NULL CHECK (decided_by IN ('llm', 'rules')),
  reason            text NOT NULL,
  model             text,
  decided_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS author_match_entity_idx ON nav.author_match(entity_id, decided_at DESC);

-- OpenAlex topic -> Topic vertex of the expertise graph (chosen by the LLM among existing Topics, or new).
CREATE TABLE IF NOT EXISTS nav.topic_map (
  openalex_topic_id  text PRIMARY KEY CHECK (openalex_topic_id ~ '^T[0-9]+$'),
  openalex_label     text NOT NULL,
  topic_key          text NOT NULL,
  topic_label        text NOT NULL,
  is_new             boolean NOT NULL,
  decided_by         text NOT NULL CHECK (decided_by IN ('llm', 'rules')),
  reason             text NOT NULL DEFAULT '',
  candidates         jsonb NOT NULL DEFAULT '[]'::jsonb,
  decided_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nav.paper_topic (
  paper_id   text NOT NULL REFERENCES nav.paper(id) ON DELETE CASCADE,
  topic_key  text NOT NULL,
  score      real,
  PRIMARY KEY (paper_id, topic_key)
);

-- Embedding-derived similarity edges (kNN on pgvector), undirected: a < b.
CREATE TABLE IF NOT EXISTS nav.similarity (
  kind        text NOT NULL CHECK (kind IN ('person', 'paper')),
  a           text NOT NULL,
  b           text NOT NULL,
  score       real NOT NULL CHECK (score BETWEEN -1 AND 1),
  method      text NOT NULL,
  threshold   real NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, method, a, b),
  CHECK (a < b)
);
CREATE INDEX IF NOT EXISTS similarity_a_idx ON nav.similarity(kind, a);
CREATE INDEX IF NOT EXISTS similarity_b_idx ON nav.similarity(kind, b);

-- Graph labels (bern_app cannot create labels) ---------------------------------------------------------------
SET LOCAL search_path = ag_catalog, nav, public;   -- graphid_ops (start/end indexes) lives in ag_catalog
DO $$
DECLARE
  g oid := (SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'expertise_graph');
  l text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_label WHERE graph = g AND name = 'Paper') THEN
    PERFORM ag_catalog.create_vlabel('expertise_graph', 'Paper');
  END IF;
  FOREACH l IN ARRAY ARRAY['AUTHORED', 'ABOUT', 'CITES', 'SIMILAR_TO'] LOOP
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_label WHERE graph = g AND name = l) THEN
      PERFORM ag_catalog.create_elabel('expertise_graph'::cstring, l::cstring);
    END IF;
  END LOOP;
  EXECUTE 'CREATE INDEX IF NOT EXISTS paper_props_gin ON expertise_graph."Paper" USING gin (properties)';
  FOREACH l IN ARRAY ARRAY['AUTHORED', 'ABOUT', 'CITES', 'SIMILAR_TO'] LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON expertise_graph.%I (start_id)', lower(l) || '_start_idx', l);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON expertise_graph.%I (end_id)',   lower(l) || '_end_idx',   l);
  END LOOP;
END $$;

-- Privileges: new nav tables are covered by the default privileges of 04-grants.sql; the new label tables of
-- the graph schema are not (no default privileges there), so grant them explicitly.
GRANT SELECT, INSERT, UPDATE, DELETE, MAINTAIN ON ALL TABLES IN SCHEMA nav TO bern_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nav TO bern_app;
REVOKE INSERT, UPDATE, DELETE ON nav.schema_migrations FROM bern_app;
GRANT SELECT, INSERT, UPDATE, DELETE, MAINTAIN ON ALL TABLES IN SCHEMA expertise_graph TO bern_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA expertise_graph TO bern_app;

INSERT INTO nav.schema_migrations(version) VALUES ('0004_papers') ON CONFLICT DO NOTHING;
COMMIT;
