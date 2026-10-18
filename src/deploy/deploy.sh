#!/usr/bin/env bash
# Sync src/ to the team server and (re)start the app. Run from src/: `make deploy`.
#   DEPLOY_HOST  ssh target (default: bern, see docs/server-handoff.md for the ~/.ssh/config entry)
# Never copied: .env (the server keeps its own), the venv, the DB stack (deployed separately in /opt/bern/db),
# and the server's case database, logs and Apertus usage log, so a redeploy doesn't wipe what the server recorded.
set -euo pipefail

HOST="${DEPLOY_HOST:-bern}"
DEST=/opt/bern/app

cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .env --exclude caddy.env --exclude .venv/ --exclude .pytest_cache/ --exclude __pycache__/ \
  --exclude db/ --exclude 'data/cases.db*' --exclude 'data/*.log' --exclude data/usage.jsonl \
  ./ "$HOST:$DEST/"

ssh "$HOST" "set -e
  cd $DEST
  cp -n .env.example .env
  docker network inspect bern >/dev/null 2>&1 || docker network create bern
  cd deploy
  docker compose up -d --build
  docker compose ps"
