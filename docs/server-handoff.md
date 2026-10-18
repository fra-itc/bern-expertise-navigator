# Team server handoff

Operating guide for the shared server of the Bern Expertise Navigator: what
runs there today, how to access it, how a deploy works, and what can lose data.

> No secrets live in this repo. The SSH private key, its passphrase and the
> staff basic-auth password are handed over out of band, on separate channels.
> Database passwords are only on the server, in `/opt/bern/db/.env`; the LLM key
> is only in `/opt/bern/app/.env`.

State described here was verified on **2026-10-18** (read-only audit
16:20–16:30 UTC, plus checks up to 17:01 UTC). See [Verified state](#verified-state-2026-10-18).

> **Update, 2026-10-18 20:55 UTC.** What changed since the audit:
>
> - **Code is in git.** The server runs commit `f5b2ce1` of `main`. An `rsync -c --dry-run` comparison shows
>   no content difference under `src/`, excluding `data/` and `db/`. `openalex.py` is committed (`05fce96`).
>   The code part of issue #7 is resolved; backups are still open.
> - **PR #6 is merged** (`168a218`). `deploy.sh` excludes `caddy.env` and the new `data/usage.jsonl`.
> - **Second exposure.** At about 20:10 UTC, a deploy from a tree that did not yet contain PR #6 replaced the
>   Caddyfile and compose file and deleted `caddy.env`.
>   - From about 20:10 to 20:40 UTC, `/cases`, `/documents` and the API docs were reachable without credentials.
>   - The old hash could not be recovered. A **new staff password** (user `staff`) was generated and its hash
>     written to `caddy.env` at 20:38 UTC, then the app was redeployed.
>   - The old password no longer works. The new one is handed out of band.
>   - Verified from outside: 401 without credentials on `/cases`, `/dashboard`, `/documents/types` and
>     `/openapi.json`; 200 with them. The 29 cases are intact.
> - **New:** a staff dashboard at `/dashboard`, behind the staff login. Each web request that calls Apertus is
>   logged in `data/usage.jsonl` (route, case id, tokens, latency; never the request text). The log is kept
>   across deploys.
> - **Still open:**
>   - no backups;
>   - no record of the deployed commit;
>   - a deploy still overwrites `data/` from the deployer's tree;
>   - no host firewall.

## Data-loss warnings (read first)

1. ~~**The code running in production is not in git.**~~ Resolved at 20:40 UTC: the server runs `f5b2ce1` of
   `main`, and `openalex.py` is committed. `/opt/bern/app` is still not a repository, and nothing on the server
   records which commit is deployed.
2. **`make deploy` deletes the search index and corpus.** `deploy.sh` runs
   `rsync --delete` and protects only `.env`, `caddy.env`, `data/cases.db*`, `data/*.log`,
   `data/usage.jsonl` (plus venv/caches/`db/`). Everything else under `data/` is overwritten or
   deleted: `entities.jsonl`, `extracted.jsonl`, `bm25.pkl`, `vectors.npy`,
   `vectors_meta.json`, `pages/*`, `eval_report.json`, `extract_stats*`
   (about 42 MB). `data/*` is in `.gitignore`, so a deploy from a clean clone
   leaves the app **with an empty index**. `config/`, `eval/`, `tests/` and the
   code are overwritten too.
3. **A deploy from a tree older than `168a218` removes the staff authentication.** The basic auth needs three
   changes: the Caddyfile, the compose `env_file`, and `deploy.sh` excluding `caddy.env`. They are in `main`
   since PR #6 (`168a218`). A deploy from a working tree without them overwrites the Caddyfile and compose file
   **and deletes `/opt/bern/app/caddy.env`**, which makes cases and documents public again. This happened at
   about 20:10 UTC on 2026-10-18 (see the update above). Always `git pull` before deploying.
4. **There are no data backups.** No cron job or systemd timer exists. The
   SQLite case database (8 cases with company contact data at audit time) and
   the corpus exist in one copy only. Hetzner snapshots could not be verified.
5. **Leftover `.env.bak-*` files are gone.** The `.env` backups mentioned in
   issue #2 no longer exist; most likely deleted by `rsync --delete`
   (inference, strong). Anything you park in `/opt/bern/app` that is not
   excluded will be deleted by the next deploy.

**Rule: deploy only from a pushed, up-to-date commit of `main`** (it contains
the production code and the auth changes), and only after taking a copy of
`/opt/bern/app/data/` and `cases.db` (see [Backups](#backups)). Record the
deployed commit on the server (for example a `SOURCE_SHA` file in
`/opt/bern/app`); today there is no such record.

## Overview

| | |
|---|---|
| Host | `116.203.127.208` (Hetzner vServer, hostname `ai`, location `nbg1-dc3`, Nuremberg, **Germany**) |
| OS | Ubuntu 26.04.1 LTS, 8 vCPU, 15 GiB RAM, no swap, 75 GB disk (about 17 GB used), no GPU |
| DNS | `https://bern-expertise.ch` (app) and `https://www.bern-expertise.ch` (301 to the apex) → `116.203.127.208` |
| Wildcard DNS | `*.bern-expertise.ch` is **not** set: add an `A *` record to `116.203.127.208` if subdomains are needed |
| TLS | Let's Encrypt via Caddy, apex + www, expires 2027-01-16 (auto-renewed by Caddy) |
| Docker | Docker CE 29.9.1, Compose v5.6.0, json-file logs (max 5 × 20 MB per container) |
| Stacks | `bern-app` (`/opt/bern/app/deploy`: `api` + `caddy`), `bern-db` (`/opt/bern/db`: Postgres), one-off crawl container in `/opt/bern/crawl`, one-off papers containers in `/opt/bern/papers` (image `bern-papers:<sha>`, [runbook](papers-runbook.md)) |

### Real state

| Component | Status | Notes |
|---|---|---|
| `api` container | Running | Image `bern-app-api:latest`, built on the server; Python 3.11 / uvicorn; `restart: unless-stopped`; **no healthcheck**; `127.0.0.1:8080` only |
| `caddy` container | Running | Caddy 2.8.4; apex → `api:8080`; `www` → 301; staff basic auth on protected paths (see [Security](#security)) |
| Running code | Not versioned | Code in the image equals `/opt/bern/app/app/navigator` on the host, which matches no commit (issue #7) |
| Entities (`data/entities.jsonl`) | INSTALLED · POPULATED · CONNECTED TO APP · USED IN REQUESTS | 1015 entities, 11274 evidence items |
| BM25 (`data/bm25.pkl`) | INSTALLED · POPULATED · CONNECTED · USED | `rank-bm25` pickle |
| Vectors (`data/vectors.npy`) | INSTALLED · POPULATED · CONNECTED · USED | NumPy matrix (10493 × 768, float32); `QDRANT_URL` is empty |
| Cases (`data/cases.db`) | INSTALLED · POPULATED · CONNECTED · USED | SQLite, 8 cases at audit time, owner `root`; written by `POST /cases` and also by `GET /cases/{id}` (summary refresh) |
| Qdrant | NOT INSTALLED | Only the Python client library; no container, no data |
| PostgreSQL (`/opt/bern/db`) | INSTALLED · NOT CONNECTED · NOT USED by the app | At audit time empty (only `0001_initial`, 0 rows, 0 graph vertices). Since then the papers pilots (PR #11) filled it from a copy of the app data: index + papers of 100 people ([pilot report](papers-pilot-report.md)). `DATABASE_URL` is still absent from the app `.env` |
| Postgres backend code | On `main` (PR #3, `d77de8e`) | **Not active on the server**; activation blocked by issue #7 (see [Database](#database)) |
| LLM | Remote, used | `apertus-v1-5-70b` via `https://gateway.keera.ch/api/v1` |
| Embeddings | Local CPU | `intfloat/multilingual-e5-base`, dim 768, model baked into the image, `HF_HUB_OFFLINE=1` |
| Crawl (`/opt/bern/crawl`) | Exists, NOT USED by the app | Separate crawl, see [Directory layout](#directory-layout) |
| Backups | NONE | See [Backups](#backups) |
| Host firewall | NONE | `ufw` inactive, iptables INPUT ACCEPT |

### Where the corpus comes from

- `artorg` (373 pages) and `dcb` (54 pages) are rule-extracted web sources:
  396 `rules` entities (ARTORG 293, DCB 103).
- `unibe` **on the server** is an OpenAlex source (`type: openalex` in
  `config/sources.yaml`, institution `I118564535`, works since 2023-01-01):
  600 openalex.org author records, not unibe.ch web pages. It yields 619
  `openalex` entities (556 persons + 63 units) and 8838 evidence items. It was
  most likely generated on a developer machine and copied up by rsync
  (inference).
- The name `unibe` means something else on branch `feat/papers-graph` and in
  `/opt/bern/crawl`: there it is a web crawl of unibe.ch pages.
- `data/eval_report.json` (recall@10 88%, synonyms 71%, traceability and
  abstention 100%, 30 queries) is a **rules-only** baseline (0 LLM calls per
  query, default 8B model name), with no commit or corpus recorded. It is not
  an evaluation of the 70B setup.

## Access

### SSH

You get two files: the private key `deploy_ed25519` and its passphrase
(separately).

```bash
chmod 600 deploy_ed25519
ssh -i deploy_ed25519 deploy@116.203.127.208
```

`~/.ssh/config` entry (required by `make deploy`, which uses the host alias `bern`):

```
Host bern
    HostName 116.203.127.208
    User deploy
    IdentityFile ~/path/to/deploy_ed25519
    IdentitiesOnly yes
```

Accounts:

| User | Access | Notes |
|---|---|---|
| `deploy` | SSH key only; `sudo` without password; `docker` group | Owns `/opt/bern/` and the deployments |
| `simone` | SSH key only; **no** sudo, **no** docker | Analyst. Read access to `/opt/bern/app/data`; Postgres role `simone` (read-only on `nav` and the graph, own schema `sandbox_simone`), credentials in `~/.pgpass`; guide in `~/CLAUDE.md` |
| `root` | SSH key only | No password login |

To add another person to `deploy`, append their **public** key to
`/home/deploy/.ssh/authorized_keys`, one key per line. To revoke someone,
delete their line. Prefer a separate unprivileged account (like `simone`) for
people who only need to read data.

### SSH hardening (already applied)

`/etc/ssh/sshd_config.d/00-hardening.conf`:

```
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
```

**Fragile:** `/etc/ssh/sshd_config.d/50-cloud-init.conf` contains
`PasswordAuthentication yes`. It has no effect today only because sshd uses
the first value it reads and `00-hardening.conf` sorts first. Renaming or
removing `00-hardening.conf` would re-enable password login. Consider setting
`PasswordAuthentication no` in `50-cloud-init.conf` as well, and check the
effective value with `sudo sshd -T | grep -i passwordauthentication`.

Before changing sshd config, keep an open session and run `sudo sshd -t`.
After `sudo systemctl reload ssh`, test from a **new** terminal before closing
the old one. If you lock yourself out, the fallback is the Hetzner web console.

### Staff basic auth (web)

Active since 16:45 UTC on 2026-10-18. User `staff`; the password is handed
over out of band and is never written in the repo or in issues. The password
was replaced at 20:38 UTC, after a deploy deleted the hash; the earlier one no
longer works. To change it: `caddy hash-password` (for example inside the
`caddy` container), write `STAFF_AUTH_HASH='<hash>'` to
`/opt/bern/app/caddy.env` (mode `600`; single quotes keep the `$` signs
literal), then run `make deploy` or recreate the `caddy` container.

## Directory layout

| Path | Owner | Under `make deploy` rsync? | Contents |
|---|---|---|---|
| `/opt/bern/app` | `deploy` | **Yes**, target of `rsync --delete` | Copy of `src/`: `app/` (code), `config/`, `eval/`, `tests/`, `deploy/` (compose + Caddyfile), `data/` |
| `/opt/bern/app/.env` | `deploy`, `600` | No (excluded) | App settings, `LLM_*`, LLM key; `DATABASE_URL` absent |
| `/opt/bern/app/caddy.env` | `deploy`, `600` | No (excluded since PR #6, `168a218`); a tree older than that deletes it | Bcrypt hash for the staff user, read by Caddy as `{$STAFF_AUTH_HASH}` |
| `/opt/bern/app/data/usage.jsonl` | `root` (written by the `api` container) | No (excluded) | Apertus usage per web request, read by `/dashboard`; created on the first request that calls Apertus |
| `/opt/bern/app/data/cases.db*` | `root` | No (excluded) | SQLite case database |
| `/opt/bern/app/data/*.log` | | No (excluded) | Logs |
| `/opt/bern/app/data/` (everything else) | `deploy` | **Yes: overwritten or deleted** | Corpus, pages, index, vectors, eval report |
| `/opt/bern/db` | `deploy` | No (deployed separately from `src/db/`) | Postgres compose, `Dockerfile`, `initdb/`, `.env` with DB passwords; volume `pgdata` |
| `/opt/bern/papers` | `deploy` | No | Papers job (PR #11): copy of the app data in `data/`, source tarballs and `bern-papers:<sha>` images; writes only to Postgres. See [`papers-runbook.md`](papers-runbook.md) |
| `/opt/bern/crawl` | `root` | No | Separate crawl run with image `bern-crawl:ac849ed` (branch `feat/papers-graph`, not merged), exited 0 at 15:36 UTC. Web pages: unibe 1500 (22 medtech domains), artorg 373, dcb 54, with links. **Not used by the app** |
| `/root/backups/` | `root` | No | Copies of Caddyfile / compose / `deploy.sh` taken while adding the auth. **Not data backups** |

## Deploy

Source: [`src/deploy/`](../src/deploy/). Run from `src/`:

```bash
cd src && make deploy        # = ./deploy/deploy.sh, uses DEPLOY_HOST (default: bern)
```

What `deploy.sh` actually does:

1. `rsync -az --delete ./ bern:/opt/bern/app/` from **your local working tree**
   (committed or not), excluding only `.env`, `caddy.env`, `.venv/`, `.pytest_cache/`,
   `__pycache__/`, `db/`, `data/cases.db*`, `data/*.log`, `data/usage.jsonl`.
2. On the server: `cp -n .env.example .env` (only if `.env` is missing),
   creates the Docker network `bern` if missing, then
   `cd deploy && docker compose up -d --build && docker compose ps`.

Consequences:

- What runs is whatever was in the deployer's directory, including untracked
  files and local `data/`. Nothing records which commit was deployed.
- Overwritten or deleted: all code, `config/`, `eval/`, `tests/`,
  `deploy/Caddyfile`, `deploy/docker-compose.yml`, and `data/` except
  `cases.db*` and `*.log`. Files on the server that are not in your tree are
  **deleted** (this is how `openalex.py`, `caddy.env` and the `.env.bak-*`
  files are at risk or gone).
- Kept: `.env`, `caddy.env`, `data/cases.db*`, `data/*.log`, `data/usage.jsonl`, `/opt/bern/db`, `/opt/bern/crawl`, `/opt/bern/papers`.
- The `api` container mounts `../data`, `../config` and `../eval` from the host.

Before every deploy:

1. Deploy only from a **pushed commit**, checked out clean and up to date with
   `main` (`git pull` first), so it contains the auth changes (PR #6).
2. If your tree has no `data/` corpus, the deploy empties the index: either
   bring the current `data/` into your tree first, or agree on one deployer
   who owns the data. Excluding `data/` from rsync is the structural fix.
3. Copy `/opt/bern/app/data/` and `cases.db` aside first (see [Backups](#backups)).
4. After the deploy, check `https://bern-expertise.ch/health` and that
   `https://bern-expertise.ch/cases` and `/dashboard` answer **401** without credentials.

Logs: `ssh bern 'cd /opt/bern/app/deploy && docker compose logs -f'`. Only the
HTTP access log is there, and it is lost when the container is recreated. LLM
usage per web request (calls, tokens, latency) is appended to
`data/usage.jsonl` on the host and shown on `/dashboard`; failed LLM calls are
still not logged.

## Database

Source: [`src/db/`](../src/db/README.md). Deployed copy: `/opt/bern/db` on the
server.

- PostgreSQL 18.6 with:
  - **Apache AGE 1.8.0**, graph `expertise_graph`;
  - **pgvector 0.8.6**, embeddings `vector(768)` for `intfloat/multilingual-e5-base`, cosine distance, HNSW index;
  - `pg_trgm` 1.6 and `unaccent` 1.1, for full-text search that replaces the BM25 pickle.
- Relational schema `nav`: `source`, `page`, `entity`, `evidence`,
  `rejected_claim`, `passage` (embeddings), `"case"`, `case_match`,
  `case_event`, `schema_migrations`.
- Graph vertices: `Person`, `Unit`, `Project`, `Infrastructure`, `Source`, `Topic`.
- Graph edges: `MEMBER_OF`, `WORKS_ON`, `PART_OF`, `OPERATES`, `FROM_SOURCE`, `HAS_EXPERTISE`.
- Roles:
  - `postgres` is the owner and runs DDL and migrations.
  - `bern_app` is the application role: DML only, no DDL. Its `search_path` is `nav, ag_catalog, public`.
  - `simone` is read-only on `nav` and the graph, with its own schema `sandbox_simone`.
- The port is bound to **`127.0.0.1:5432` only**. It is not reachable from the internet.
- App containers on the server join the Docker network `bern` and connect to
  host `db`, port `5432`.

### What it contains today

Nothing. Verified at 17:01 UTC: only migration `0001_initial`, every `nav`
table has 0 rows (`n_tup_ins` 0), the graph has 0 vertices and 0 edges, and
there are no client connections. The 1015 entities reported by `/health` come
from `data/entities.jsonl`, not from Postgres. The `pgdata` volume (about
66 MB) holds no application data.

Update: the papers pilots (PR #11, [runbook](papers-runbook.md)) have since
written an index and the papers of 100 people to this database, from a copy
of the app data in `/opt/bern/papers/data`; counts in the
[pilot report](papers-pilot-report.md). The app still does not read it.

### How it will be activated

The Postgres backend (PR #3) is on `main` since 16:31:58 UTC (`d77de8e`). The
app switches backend on `DATABASE_URL`: empty means files + SQLite, set means
Postgres. The blocker (production code not committed, issue #7) is resolved:
the server runs `main` (`f5b2ce1`). Then:

1. Deploy from a pushed, up-to-date commit of `main`.
2. Take a `pg_dump` (see below), even if the database is empty.
3. Apply the migrations, in this order, as `postgres` (from `/opt/bern/db`,
   with the files from `src/db/migrations/` of the deployed commit):

   ```bash
   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0002_index_order_and_match_ref.sql
   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0003_case_search_filters.sql
   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0004_papers.sql
   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0005_case_company_sources.sql
   docker compose exec -T db psql -U postgres -d bern -v ON_ERROR_STOP=1 < migrations/0006_evidence_publication_field.sql
   ```

   (`0004_papers` is required once PR #11 is merged; skip any file already
   listed in `nav.schema_migrations`, e.g. applied by the papers pilots.)
   All are required: the app checks `nav.schema_migrations` at connect
   time and refuses to start with `schema_outdated` if one is missing.
   `0002_remove_technical_review` is **optional and destructive** (it drops
   the technical-review columns); it is not required by the app. Take a backup
   before running it.
4. Add `DATABASE_URL=postgresql://bern_app:<APP_DB_PASSWORD>@db:5432/bern` to
   `/opt/bern/app/.env` (password from `/opt/bern/db/.env`) and restart the stack.
5. Load the index into Postgres (`navigator.cli index` with `DATABASE_URL` set).
6. Carry over **all** SQLite cases to `nav."case"` / `case_match` /
   `case_event`. There is no SQLite → Postgres case import tool on `main`
   today; this has to be written or done by hand before switching.
7. Verify: row counts in `nav.entity` and `nav."case"`, a client in
   `pg_stat_activity`, a test search, `/cases` behind auth.

### Connect from your laptop (SSH tunnel)

```bash
ssh -i deploy_ed25519 -N -L 5432:127.0.0.1:5432 deploy@116.203.127.208
# in another terminal:
psql "postgresql://bern_app@127.0.0.1:5432/bern"
```

The passwords are in `/opt/bern/db/.env` on the server (`APP_DB_PASSWORD` for
`bern_app`, `POSTGRES_PASSWORD` for `postgres`):

```bash
ssh bern 'grep APP_DB_PASSWORD /opt/bern/db/.env'
```

### Operate

```bash
cd /opt/bern/db
docker compose ps                  # status / health
docker compose logs -f db          # logs
docker compose up -d --build       # rebuild after changing Dockerfile
docker exec -it bern-db-db-1 psql -U postgres -d bern
```

The `initdb/` scripts run **only on the first start**, when the volume is
empty. Schema changes made after that must be migrations: apply them as
`postgres` and record them in `nav.schema_migrations`.

### Dump and restore

```bash
docker exec bern-db-db-1 pg_dump -U postgres -d bern -Fc > ~/bern_$(date +%F).dump
```

Restoring: `pg_restore`, then **always** run `src/db/post-restore-age.sql` as
`postgres`. Without it, the graph queries (Cypher) fail after a restore with
`graph with oid NNNNN does not exist`. See `src/db/README.md` → *Backup and restore*.

`src/db/README.md` has example queries for vector search, FTS, Cypher 1-hop,
and hybrid graph + vector search.

## LLM and embeddings

- **LLM:** `apertus-v1-5-70b` through an OpenAI-compatible gateway at
  `https://gateway.keera.ch/api/v1` (streaming, 120 s timeout), configured with
  `LLM_BASE_URL` / `LLM_API_KEY` in `/opt/bern/app/.env`. There is no GPU and
  no local model server on this host.
  - Where the gateway runs (Switzerland / CSCS) is **declared by the provider,
    not verified**.
  - Who owns the API key is **still to be decided** (issue / PR #4).
- The LLM is called **at runtime**, on user requests: query expansion (after
  the glossary), match explanations (`_llm_why`, LRU-cached, deterministic
  fallback) and case analysis (`plain.analyze_company`).
- **`llm_available` / `llm_used` do not mean a call succeeded.** They only
  report that `GET /models` on the gateway answered (cached 60 s, 3 s timeout).
  A failed call (`LLMError`) is swallowed silently. Successful calls are
  counted per web request (calls, tokens, latency, route, case id) in
  `data/usage.jsonl` and priced on `/dashboard`; failures are not logged.
- **Embeddings:** `intfloat/multilingual-e5-base` (768 dimensions) on CPU
  with torch, model baked into the image, `HF_HUB_OFFLINE=1`.
- Search pipeline: BM25 + e5 vectors fused with RRF (weight 0.9 for OpenAlex
  records), then propagation, abstention and fairness rules.

## Security

- **Staff basic auth (Caddy)**, active since 16:45 UTC on 2026-10-18, on:
  `/cases`, `/cases/*`, `/documents`, `/documents/*`, `/dashboard`, `/docs`, `/docs/*`,
  `/redoc`, `/redoc/*`, `/openapi.json`.
  - The bcrypt hash is in `/opt/bern/app/caddy.env` (`600`, owner `deploy`),
    loaded by the compose `caddy` service via `env_file: ../caddy.env` and used
    in the Caddyfile as `{$STAFF_AUTH_HASH}`. `deploy.sh` excludes `caddy.env`.
  - These three changes are in `main` since PR #6 (`168a218`). A deploy from a
    tree without them removes the auth (see the warnings above); it happened
    once, from about 20:10 to 20:40 UTC on 2026-10-18.
  - Public on purpose: `/`, `/search`, `/stats`, `/health`, and
    `/briefs/{token}` (protected by a 12-byte random token compared in
    constant time; an unknown token returns 404).
  - The FastAPI app itself has no authentication: anyone who reaches
    `127.0.0.1:8080` on the host bypasses Caddy.
- **Personal data:** cases contain company contact names and emails, request
  text, shared documents and outreach history. Do not copy `cases.db` or dumps
  off the server unencrypted, and do not paste case content into issues.
  Public search results include the institutional contact emails of
  researchers (156 ARTORG entities have one).
- **Ports:** public 22, 80, 443. `5432` (Postgres) and `8080` (api) listen on
  loopback only.
- **No host firewall:** `ufw` is inactive and iptables INPUT is ACCEPT; the
  loopback binding is the only protection for 5432 and 8080. A Hetzner cloud
  firewall could not be checked.
- **Location:** the server is in Germany (Hetzner `nbg1-dc3`), not in a Swiss
  cloud.
- **Side effect:** `GET /cases/{id}` can write to the case database (summary
  refresh).

## Backups

**None yet.** No cron job, no systemd timer, no dump on disk. The files in
`/root/backups/` are copies of deploy files, not data. Configuring backups is
assigned to the team (issue #7). What they must cover:

| What | Where | Why |
|---|---|---|
| Case database | `/opt/bern/app/data/cases.db*` | Only copy of the cases, with personal data |
| Corpus and index | `/opt/bern/app/data/` (`entities.jsonl`, `extracted.jsonl`, `bm25.pkl`, `vectors*`, `pages/`) | Deleted by a deploy from a tree without `data/` |
| App settings | `/opt/bern/app/.env`, `/opt/bern/app/caddy.env` | Not in git; contain secrets: store encrypted |
| Postgres | `pg_dump -Fc` of `bern` | Holds the papers pilots (reproducible from the runbook); required once `DATABASE_URL` is active |
| Crawl output | `/opt/bern/crawl` | Optional; reproducible but slow |

Keep copies off the server and encrypted, test a restore (for Postgres:
`pg_restore` + `post-restore-age.sql`), and check whether Hetzner snapshots
are enabled for this server.

Manual copy before a deploy (on the server):

```bash
sudo tar czf ~/data-$(date +%F-%H%M).tgz -C /opt/bern/app data
```

## Known issues and open items

| Item | Reference |
|---|---|
| ~~Production code (`openalex.py` + 16 files) not committed~~ Resolved: the server runs `f5b2ce1` | issue #7 |
| No data backups; configure and test them | issue #7 |
| ~~Staff basic auth not yet in `main`~~ Merged (`168a218`); a deploy from an older tree still removes it | PR #6 |
| `make deploy` deletes `data/` corpus and index; exclude `data/` from rsync or designate one data owner | |
| No record of the deployed commit (`SOURCE_SHA`) | |
| Postgres backend merged (PR #3) but not active; SQLite → Postgres case import missing | issue #7 |
| Postgres case store does not persist `Case.offer`: on that backend every `GET /cases/{id}` rebuilds the offer and resets the partner selection (`tests/test_pg_backend.py::test_cases_roundtrip_and_api` fails) | |
| LLM key owner to be decided | issue / PR #4 |
| Failed LLM calls not logged (successful ones are, in `data/usage.jsonl`); `llm_used` only means "endpoint reachable" | |
| Eval report is rules-only and unversioned; rerun with the 70B model, recording commit and corpus | |
| No healthcheck on the `api` container | |
| No host firewall | |
| `50-cloud-init.conf` contains `PasswordAuthentication yes` (neutralized, fragile) | |
| `GET /cases/{id}` has a write side effect | |

## Verified state (2026-10-18)

Read-only audit 16:20–16:30 UTC; later checks by the coordinator as noted.

| Time (UTC) | Check | Result |
|---|---|---|
| 16:20–16:30 | `docker ps`, `docker inspect` | `api` and `caddy` up; `api` no healthcheck, `127.0.0.1:8080`; `bern-db-db-1` healthy on `127.0.0.1:5432` |
| 16:20–16:30 | `sha256sum` host vs `docker exec`, git blob SHA vs `git rev-list --all` | Running code = host copy; matches no commit (34/52 files equal to `main`) |
| 16:20–16:30 | `test -d /opt/bern/app/.git` | Not a git repository |
| 16:26 | `docker inspect` | `api` recreated by a deploy during the audit (code changed, `data/` unchanged) |
| 16:20–16:30 | `pg_extension` | `age 1.8.0`, `pg_trgm 1.6`, `unaccent 1.1`, `vector 0.8.6` |
| 16:20–16:30 | `ss -tlnp`, `ufw status`, `iptables -L INPUT` | Public 22/80/443; 5432 and 8080 loopback; ufw inactive |
| 16:20–16:30 | `sshd -T`, `sudo -l` | Password auth off; root key only; `deploy` sudo NOPASSWD; `simone` no sudo/docker |
| 16:20–16:30 | `crontab -l`, `systemctl list-timers`, `find` for dumps | No backups |
| 16:20–16:30 | Hetzner metadata, `lspci` | `nbg1-dc3`; no GPU |
| 16:20–16:30 | `llm.ping()` in the container | `apertus-v1-5-70b` served by the gateway |
| 16:31:58 | `gh pr view 3` | PR #3 merged (`d77de8e`) |
| 16:45+ | `curl -o /dev/null -w '%{http_code}'` from outside | Without credentials: 401 on all protected paths; 200 on `/`, `/search`, `/stats`, `/health`; 404 on `/briefs/<unknown>`; 301 on `www` |
| 17:01 | `psql`: `nav.schema_migrations`, `pg_stat_user_tables`, Cypher count, `pg_stat_activity` | Only `0001_initial`; 0 rows everywhere; 0 vertices / 0 edges; no clients |
| 17:01 | `grep -c '^DATABASE_URL=' /opt/bern/app/.env` | Absent |
| ~20:35 | `ls /opt/bern/app/caddy.env`, `docker inspect bern-app-caddy-1` | `caddy.env` missing, no `STAFF_AUTH_HASH` in the container; `/cases` answered 200 without credentials |
| 20:38 | `caddy hash-password` (new password), write `caddy.env` (`600`) | Hash written; `make deploy` of `f5b2ce1` |
| 20:41 | `curl` from outside, with and without credentials | Without: 401 on `/cases`, `/dashboard`, `/documents/types`, `/openapi.json`; 200 on `/`, `/health`. With: 200; 29 cases |
| 20:50 | `rsync -anci --delete` of `git archive f5b2ce1` against `/opt/bern/app` (excluding `data/`, `db/`) | Timestamps differ only; no content difference |

Not verifiable from the server: where the LLM gateway runs and who operates
it; LLM call counts and errors; Hetzner snapshots and cloud firewall; the
contents of developers' local `data/`.
