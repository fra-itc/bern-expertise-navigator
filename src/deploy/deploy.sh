#!/usr/bin/env bash
# Sync src/ to the team server and (re)start the app. Run from src/: `make deploy`.
#   DEPLOY_HOST  ssh target (default: bern, see docs/server-handoff.md for the ~/.ssh/config entry)
# Never copied: .env (the server keeps its own), the venv, the DB stack (deployed separately in /opt/bern/db),
# and the server's case database and logs (data/cases.db*, data/*.log).
# WARNING: rsync runs with --delete. Everything else under the server's app directory is overwritten or DELETED
# to match your local tree, including data/ (entities.jsonl, extracted.jsonl, bm25.pkl, vectors.npy, pages/,
# eval_report.json, ...), config/, eval/ and the code. data/ is git-ignored, so deploying from a clean clone
# empties the server's corpus and index. Only cases.db*, data/*.log, .env and /opt/bern/db survive.
# Also deleted: any extra files on the server such as .env.bak-* (only .env itself is excluded).
set -euo pipefail

HOST="${DEPLOY_HOST:-bern}"
DEST=/opt/bern/app

cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .env --exclude .venv/ --exclude .pytest_cache/ --exclude __pycache__/ \
  --exclude db/ --exclude 'data/cases.db*' --exclude 'data/*.log' \
  ./ "$HOST:$DEST/"

ssh "$HOST" "set -e
  cd $DEST
  cp -n .env.example .env
  docker network inspect bern >/dev/null 2>&1 || docker network create bern
  cd deploy
  docker compose up -d --build
  docker compose ps"
