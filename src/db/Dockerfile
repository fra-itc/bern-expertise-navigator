# Bern Expertise Navigator - PostgreSQL 18 + Apache AGE 1.8.0 + pgvector 0.8.6
FROM apache/age:release_PG18_1.8.0

# Pinned pgvector (the pgdg repo is already configured in the base image).
# We remove the base image's initdb script: extension creation lives in ./initdb (one thing, one place).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-18-pgvector=0.8.6-1.pgdg13+1; \
    apt-mark hold postgresql-18-pgvector; \
    rm -rf /var/lib/apt/lists/* /docker-entrypoint-initdb.d/00-create-extension-age.sql

# First-start scripts (empty volume only). Later changes = migrations, not initdb.
COPY --chmod=0755 initdb/ /docker-entrypoint-initdb.d/
# Versioned migrations (0002+), applied on first start by initdb/06-migrations.sh.
COPY --chmod=0755 migrations/ /migrations/

LABEL org.opencontainers.image.title="bern-pg" \
      org.opencontainers.image.description="PostgreSQL 18.6 + Apache AGE 1.8.0 + pgvector 0.8.6"
