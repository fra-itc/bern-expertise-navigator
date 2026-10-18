#!/usr/bin/env bash
# First start only: apply the versioned migrations shipped in the image (/migrations, see Dockerfile),
# so a fresh volume ends at the same schema as an upgraded one. Each file records itself in
# nav.schema_migrations; existing databases get them by hand (see README "Migrations").
set -euo pipefail
shopt -s nullglob
for f in /migrations/*.sql; do
  echo "[initdb] migration $(basename "$f")"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
