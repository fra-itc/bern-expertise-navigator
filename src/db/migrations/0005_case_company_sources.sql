-- 0005: the request from a company link / shared documents and the broad search (main 32a3c4c, 6dc8027,
-- 6f933bc, ae7ba6e) as seen by the app's Postgres backend (navigator/pgstore.py).
-- (0004 is taken by the papers branch.)
-- Apply as the owner (postgres), once, after 0003:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0005_case_company_sources.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; additive only, no data is removed.
BEGIN;

-- Case: what the company gave us besides the pasted text, and what the broad search recognised.
-- Empty string / empty list / NULL = not given, as in the file backend.
ALTER TABLE nav."case" ADD COLUMN IF NOT EXISTS city        text  NOT NULL DEFAULT '',
                       ADD COLUMN IF NOT EXISTS understood  jsonb NOT NULL DEFAULT '[]'::jsonb,  -- understand.Detection[]
                       ADD COLUMN IF NOT EXISTS company_url text  NOT NULL DEFAULT '',
                       ADD COLUMN IF NOT EXISTS need        text  NOT NULL DEFAULT '',
                       ADD COLUMN IF NOT EXISTS website     jsonb,                               -- company.CompanyWebsite
                       ADD COLUMN IF NOT EXISTS documents   jsonb NOT NULL DEFAULT '[]'::jsonb;  -- documents.Document[]
-- request_text is optional now (a link or a document is enough); existing rows keep their text.
ALTER TABLE nav."case" ALTER COLUMN request_text SET DEFAULT '';

-- Match: archetype id (navigator/archetypes.py). '' on older rows: the app classifies them on load.
ALTER TABLE nav.case_match ADD COLUMN IF NOT EXISTS archetype text NOT NULL DEFAULT '';

INSERT INTO nav.schema_migrations(version) VALUES ('0005_case_company_sources') ON CONFLICT DO NOTHING;
COMMIT;
