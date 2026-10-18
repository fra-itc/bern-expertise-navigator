-- 0006: evidence field 'publication', used by the team's OpenAlex source (extractor 'openalex': one evidence
-- per publication of an author, url = the openalex.org author). Without it `index` on the Postgres backend fails
-- with "violates check constraint evidence_field_check" on the first OpenAlex entity, and nothing is written.
-- Apply as the owner (postgres), once, after 0005:
--   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0006_evidence_publication_field.sql
-- Fresh volumes get it automatically through initdb/06-migrations.sh. Idempotent; it only widens a CHECK.
BEGIN;

ALTER TABLE nav.evidence DROP CONSTRAINT IF EXISTS evidence_field_check;
ALTER TABLE nav.evidence ADD CONSTRAINT evidence_field_check CHECK (field IN (
  'name', 'role', 'unit', 'institute', 'email', 'expertise', 'projects', 'infrastructure', 'description',
  'publication'));

INSERT INTO nav.schema_migrations(version) VALUES ('0006_evidence_publication_field') ON CONFLICT DO NOTHING;
COMMIT;
