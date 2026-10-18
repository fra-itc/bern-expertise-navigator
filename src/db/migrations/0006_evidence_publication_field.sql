-- 0006: let the Postgres backend index the team's OpenAlex source.
-- Its entities have extractor 'openalex' and one evidence per publication (field 'publication', url = the
-- openalex.org author). Without this migration `index` fails on the first OpenAlex entity with
-- "violates check constraint entity_extractor_check" / "evidence_field_check", and nothing is written.
-- Apply as the owner (postgres), once, after 0005:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0006_evidence_publication_field.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; it only widens two CHECKs.
BEGIN;

ALTER TABLE nav.entity DROP CONSTRAINT IF EXISTS entity_extractor_check;
ALTER TABLE nav.entity ADD CONSTRAINT entity_extractor_check CHECK (extractor IN ('apertus', 'rules', 'openalex'));

ALTER TABLE nav.evidence DROP CONSTRAINT IF EXISTS evidence_field_check;
ALTER TABLE nav.evidence ADD CONSTRAINT evidence_field_check CHECK (field IN (
  'name', 'role', 'unit', 'institute', 'email', 'expertise', 'projects', 'infrastructure', 'description',
  'publication'));

INSERT INTO nav.schema_migrations(version) VALUES ('0006_evidence_publication_field') ON CONFLICT DO NOTHING;
COMMIT;
