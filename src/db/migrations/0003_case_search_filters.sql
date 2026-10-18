-- 0003: the search-first request (main 1b29c80) and the end of the technical-review step (main f894742)
-- as seen by the app's Postgres backend (navigator/pgstore.py).
-- Apply as the owner (postgres), once:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0003_case_search_filters.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; no data is removed.
BEGIN;

-- New request filters: canton (only when the company is in Switzerland), medtech area and niche
-- (ids from config/medtech_areas.yaml). Empty string = not given, as in the file backend.
ALTER TABLE nav."case" ADD COLUMN IF NOT EXISTS canton text NOT NULL DEFAULT '',
                       ADD COLUMN IF NOT EXISTS area   text NOT NULL DEFAULT '',
                       ADD COLUMN IF NOT EXISTS niche  text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS case_area_niche_idx ON nav."case"(area, niche);

-- Databases that have not applied 0002_remove_technical_review still carry the review columns: the app
-- no longer writes them, so they become nullable and unused (dropping them is left to 0002_remove_*).
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT table_name, column_name FROM information_schema.columns
           WHERE table_schema = 'nav' AND is_nullable = 'NO'
             AND ((table_name = 'case'       AND column_name IN ('reviewer', 'review_note', 'review_comment'))
               OR (table_name = 'case_match' AND column_name = 'review_note'))
  LOOP
    EXECUTE format('ALTER TABLE nav.%I ALTER COLUMN %I DROP NOT NULL', c.table_name, c.column_name);
  END LOOP;
END $$;

INSERT INTO nav.schema_migrations(version) VALUES ('0003_case_search_filters') ON CONFLICT DO NOTHING;
COMMIT;
