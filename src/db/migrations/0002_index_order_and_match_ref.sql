-- 0002: what the app's Postgres backend (navigator/pgstore.py) needs beyond 0001_initial.
-- Apply as the owner (postgres), once:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0002_index_order_and_match_ref.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh.
BEGIN;

-- Order of the entities in the indexed input (extracted.jsonl): the file backend's iteration order,
-- kept so tie-breaks (pinned person order, stats key order) are identical on both backends.
ALTER TABLE nav.entity ADD COLUMN IF NOT EXISTS load_order integer NOT NULL DEFAULT 0;

-- case_match.entity_id is SET NULL when a reindex drops the entity; the match id the UI uses for
-- selection/review must survive that, so it is kept as a plain snapshot column.
ALTER TABLE nav.case_match ADD COLUMN IF NOT EXISTS entity_ref text;
UPDATE nav.case_match SET entity_ref = coalesce(entity_id, '') WHERE entity_ref IS NULL;
ALTER TABLE nav.case_match ALTER COLUMN entity_ref SET NOT NULL;

INSERT INTO nav.schema_migrations(version) VALUES ('0002_index_order_and_match_ref') ON CONFLICT DO NOTHING;
COMMIT;
