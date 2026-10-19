-- 0007: the "what Bern offers" paragraph of a request (navigator/cases.py Offer, main) in the Postgres case store.
-- Without it the backend drops Case.offer on save, so GET /cases/{id} rebuilds the paragraph on every read and
-- the rebuild resets the partner selection the officer made.
-- Apply as the owner (postgres), once, after 0006:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0007_case_offer.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; additive only, no data is removed.
BEGIN;

-- Case: cases.Offer as JSON. NULL = not written yet (older rows): the app builds it on the next read, as before.
ALTER TABLE nav."case" ADD COLUMN IF NOT EXISTS offer jsonb;

INSERT INTO nav.schema_migrations(version) VALUES ('0007_case_offer') ON CONFLICT DO NOTHING;
COMMIT;
