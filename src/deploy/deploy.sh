#!/usr/bin/env bash
# Sync src/ to the team server and (re)start the app. Run from src/: `make deploy`.
#   DEPLOY_HOST  ssh target (default: bern, see docs/server-handoff.md for the ~/.ssh/config entry)
# Never copied: .env (the server keeps its own), the venv, the DB stack (deployed separately in /opt/bern/db),
# and the server's case database, logs, Apertus usage log and staff login hash (data/cases.db*, data/*.log,
# data/usage.jsonl, caddy.env), nor the Knowledge Base, discovery, delivery and published-pitch databases and the
# private originals (data/knowledge.db*, discovery.db*, delivery.db*, published-pitches.db*, private-originals/).
# WARNING: rsync runs with --delete. Everything else under the server's app directory is overwritten or DELETED
# to match your local tree, including data/ (entities.jsonl, extracted.jsonl, bm25.pkl, vectors.npy, pages/,
# eval_report.json, ...), config/, eval/, deploy/ (Caddyfile, compose file) and the code. data/ is git-ignored, so
# deploying from a clean clone empties the server's corpus and index. Only .env, caddy.env, cases.db*, data/*.log,
# data/usage.jsonl and /opt/bern/db survive. Also deleted: any extra files on the server such as .env.bak-*.
set -euo pipefail

HOST="${DEPLOY_HOST:-bern}"
DEST=/opt/bern/app

cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .env --exclude caddy.env --exclude .venv/ --exclude .pytest_cache/ --exclude __pycache__/ \
  --exclude db/ --exclude 'data/cases.db*' --exclude 'data/*.log' --exclude data/usage.jsonl \
  --exclude 'data/knowledge.db*' --exclude 'data/discovery.db*' --exclude 'data/delivery.db*' \
  --exclude 'data/published-pitches.db*' --exclude data/private-originals/ \
  ./ "$HOST:$DEST/"

ssh "$HOST" "set -e
  cd $DEST
  cp -n .env.example .env
  docker network inspect bern >/dev/null 2>&1 || docker network create bern
  cd deploy
  docker compose up -d --build
  docker compose ps"
