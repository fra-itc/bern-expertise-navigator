# Team server handoff

Shared server for the Bern Expertise Navigator: SSH access, Docker, and the
PostgreSQL database (pgvector + Apache AGE).

> No secrets live in this repo. The SSH private key and its passphrase are
> handed over in person, on separate channels. Database passwords are only on
> the server, in `/opt/bern/db/.env`.

## Server

| | |
|---|---|
| Host | `116.203.127.208` (Hetzner, hostname `ai`) |
| OS | Ubuntu 26.04.1 LTS, 8 vCPU, 15 GB RAM, 75 GB disk |
| DNS | `https://bern-expertise.ch` and `https://www.bern-expertise.ch` → `116.203.127.208` |
| Wildcard DNS | `*.bern-expertise.ch` is **not** set yet: add an `A *` record to `116.203.127.208` if subdomains are needed |
| Docker | Docker CE 29.9.1, Compose v5.6.0, json-file logs (max 5 × 20 MB per container) |

## SSH access

You get two files: the private key `deploy_ed25519` and its passphrase
(separately).

```bash
chmod 600 deploy_ed25519
ssh -i deploy_ed25519 deploy@116.203.127.208
```

Optional `~/.ssh/config` entry:

```
Host bern
    HostName 116.203.127.208
    User deploy
    IdentityFile ~/path/to/deploy_ed25519
    IdentitiesOnly yes
```

The `deploy` user:

- logs in with the SSH key only. Its system password is locked and password
  login is disabled server-wide.
- has `sudo` without a password.
- is in the `docker` group, so `docker` and `docker compose` work without `sudo`.
- owns `/opt/bern/`, which is where the deployments live.

To add another person, append their **public** key to
`/home/deploy/.ssh/authorized_keys`, one key per line. To revoke someone,
delete their line.

## SSH hardening (already applied)

`/etc/ssh/sshd_config.d/00-hardening.conf`:

```
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
```

Before changing sshd config, keep an open session and run `sudo sshd -t`.
After `sudo systemctl reload ssh`, test from a **new** terminal before closing
the old one. If you lock yourself out, the fallback is the Hetzner web console.

## Database

Source: [`src/db/`](../src/db/README.md). Deployed copy: `/opt/bern/db` on the
server.

- PostgreSQL 18.6 with:
  - **Apache AGE 1.8.0**, graph `expertise_graph`;
  - **pgvector 0.8.6**, embeddings `vector(768)` for `intfloat/multilingual-e5-base`, cosine distance, HNSW index;
  - `pg_trgm` and `unaccent`, for full-text search that replaces the BM25 pickle.
- Relational schema `nav`: `source`, `page`, `entity`, `evidence`,
  `rejected_claim`, `passage` (embeddings), `"case"`, `case_match`,
  `case_event`, `schema_migrations`.
- Graph vertices: `Person`, `Unit`, `Project`, `Infrastructure`, `Source`, `Topic`.
- Graph edges: `MEMBER_OF`, `WORKS_ON`, `PART_OF`, `OPERATES`, `FROM_SOURCE`, `HAS_EXPERTISE`.
- Roles:
  - `postgres` is the owner and runs DDL and migrations.
  - `bern_app` is the application role: DML only, no DDL. Its `search_path` is `nav, ag_catalog, public`.
- The port is bound to **`127.0.0.1:5432` only**. It is not reachable from the internet.
- App containers on the server join the Docker network `bern` and connect to
  host `db`, port `5432`.

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

### Backup

```bash
docker exec bern-db-db-1 pg_dump -U postgres -d bern -Fc > ~/bern_$(date +%F).dump
```

Restoring: `pg_restore`, then **always** run `src/db/post-restore-age.sql` as `postgres`. Without it, the graph queries
(Cypher) fail after a restore. See `src/db/README.md` → *Backup and restore*.

No automatic backup is scheduled yet.

### Wiring the app (next step, not done in this PR)

The app still reads `data/*.jsonl`, `bm25.pkl`, and Qdrant/NumPy vectors, plus
SQLite for cases. To switch it to Postgres:

1. Add a `DATABASE_URL` setting, for example
   `postgresql://bern_app:...@db:5432/bern`.
2. Write `index` into `nav.entity`, `nav.evidence`, and `nav.passage`, and the
   graph edges into `expertise_graph`.
3. Move `cases.py` from SQLite to `nav."case"`, `nav.case_match`, and
   `nav.case_event`.

`src/db/README.md` has example queries for vector search, FTS, Cypher 1-hop,
and hybrid graph + vector search.

## App deployment

Source: [`src/deploy/`](../src/deploy/). Deployed copy: `/opt/bern/app` on the
server. It needs the `bern` entry in `~/.ssh/config` (see above).

```bash
cd src && make deploy        # rsync src/ to /opt/bern/app, then docker compose up -d --build
```

- `api` runs the navigator as `make serve LOCAL=1` does: NumPy vectors from
  `data/`, rules mode unless `LLM_BASE_URL` is set in `/opt/bern/app/.env`.
- `caddy` serves `https://bern-expertise.ch` (Let's Encrypt) and redirects
  `www`. Ports 80 and 443 must be free on the server.
- The server keeps its own `.env` and `data/cases.db`; a redeploy never
  overwrites them.
- Logs: `ssh bern 'cd /opt/bern/app/deploy && docker compose logs -f'`.

## Verified state (2026-10-18)

| Check | Result |
|---|---|
| SSH `deploy` with key + passphrase, `sudo -n true` | OK |
| Root login with password | `Permission denied (publickey)` |
| `docker compose ps` | `bern-db-db-1 Up (healthy) 127.0.0.1:5432->5432/tcp` |
| `pg_extension` | `age 1.8.0`, `pg_trgm 1.6`, `unaccent 1.1`, `vector 0.8.6` |
| `nav.schema_migrations` | `0001_initial` |
| `bern_app` | `rolsuper = f`; `CREATE TABLE` → `permission denied for schema nav` |
| `bern_app` Cypher on `expertise_graph` | OK (0 vertices; the database is empty) |
