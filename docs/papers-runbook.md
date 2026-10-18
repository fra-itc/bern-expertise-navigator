# Papers on the server: runbook

How to fill the server's Postgres (`/opt/bern/db`, container `bern-db-db-1`, network `bern`, host `db`) with
the papers graph, starting from the data the live app uses **today**, without touching the app:

- the app (`/opt/bern/app`, compose project `bern-app`) keeps running on its files; nothing under
  `/opt/bern/app` is written, restarted or redeployed;
- the papers job works on a **copy** of the app data in `/opt/bern/papers/data`;
- it runs in **one-off containers** built from the branch image, on the `bern` network, as `bern_app`.

Everything below runs on the server as the `deploy` user. Replace `<sha>` with the commit you built.

## 0. Gates (read-only; stop if one fails)

```bash
# The app must be on the file backend: `index` replaces the whole Postgres index, so if the app already reads
# Postgres this runbook would change what it serves. Expected output: an empty value.
grep -E '^DATABASE_URL=' /opt/bern/app/.env

# Database up, and which migrations it already has
docker exec bern-db-db-1 psql -U postgres -d bern -tAc "SELECT version FROM nav.schema_migrations ORDER BY 1"

# Disk: PDFs + text can reach 10-20 GB for the whole UniBE perimeter (see src/README.md "Papers")
df -h /opt/bern
```

## 1. Read-only copy of the app data

`cp` only reads the source. The app writes `data/cases.db` and logs at run time, not these files.

```bash
install -d -m 0750 /opt/bern/papers /opt/bern/papers/data /opt/bern/papers/data/pages
cp -a /opt/bern/app/data/entities.jsonl /opt/bern/app/data/extracted.jsonl /opt/bern/papers/data/
cp -a /opt/bern/app/data/pages/. /opt/bern/papers/data/pages/
( cd /opt/bern/app/data && sha256sum entities.jsonl extracted.jsonl pages/*.jsonl ) > /opt/bern/papers/source.sha256
( cd /opt/bern/papers/data && sha256sum -c /opt/bern/papers/source.sha256 )     # all OK = faithful copy
```

`index` reads `extracted.jsonl` and `pages/`; `entities.jsonl` is kept next to them for comparison.

## 2. Image of the branch (separate directory, never `make deploy`)

`make deploy` rsyncs `src/` into `/opt/bern/app` with `--delete` and restarts the app: do not use it here.

```bash
# on a workstation, from the repository
git archive --format=tar.gz -o papers-src-<sha>.tar.gz <sha> src
scp papers-src-<sha>.tar.gz bern:/opt/bern/papers/

# on the server
mkdir -p /opt/bern/papers/src-<sha> && tar -xzf /opt/bern/papers/papers-src-<sha>.tar.gz -C /opt/bern/papers/src-<sha>
cd /opt/bern/papers/src-<sha>/src && docker build -f app/Dockerfile -t bern-papers:<sha> .
```

## 3. Migrations, as `postgres`, in order

Back up first (same command as `src/db/README.md`):

```bash
docker exec bern-db-db-1 pg_dump -U postgres -d bern -Fc > ~/bern_$(date +%F)_pre-papers.dump
```

Apply only what is missing, in this order. All four are additive and idempotent; `0004` and `0005` touch
disjoint objects, so a database that already has `0005` takes `0004` as-is.

```bash
cd /opt/bern/papers/src-<sha>/src/db/migrations
for v in 0002_index_order_and_match_ref 0003_case_search_filters 0004_papers 0005_case_company_sources; do
  have=$(docker exec bern-db-db-1 psql -U postgres -d bern -tAc "SELECT 1 FROM nav.schema_migrations WHERE version = '$v'")
  if [ "$have" = 1 ]; then echo "skip $v"; continue; fi
  docker exec -i bern-db-db-1 psql -U postgres -d bern -v ON_ERROR_STOP=1 < "$v.sql" || { echo "FAILED $v"; break; }
done
docker exec bern-db-db-1 psql -U postgres -d bern -tAc "SELECT version FROM nav.schema_migrations ORDER BY 1"
```

`0002_remove_technical_review` is not required by the app and drops columns: leave it out unless it is already
there. `0004` also widens `nav.entity.extractor` to accept `openalex`, without which the entities of the
team's OpenAlex source cannot be indexed into Postgres.

## 4. Environment of the job

One file, mode 600, outside any repository. The `bern_app` password is read from the DB stack's `.env`,
never typed or echoed (if it contains URL-reserved characters such as `@ : / ?`, percent-encode it in the URL).
The LLM settings are copied from the app's `.env`, so the job uses the same Apertus endpoint.

```bash
umask 077
{
  printf 'DATABASE_URL=postgresql://bern_app:%s@db:5432/bern\n' "$(sed -n 's/^APP_DB_PASSWORD=//p' /opt/bern/db/.env)"
  echo 'NAV_DATA_DIR=/work/data'
  echo 'HF_HUB_OFFLINE=1'
  grep -E '^(LLM_BASE_URL|LLM_NAME|LLM_API_KEY|LLM_STREAM|LLM_TIMEOUT|LLM_CONCURRENCY)=' /opt/bern/app/.env
  echo 'OPENALEX_API_KEY=<key from https://openalex.org/settings/api>'
  echo 'OPENALEX_MAILTO=<team contact address>'
  # bounds: works per person, full-text chunks per paper (4 halves the embedding time, see src/README.md)
  echo 'PAPERS_MAX_WORKS=30'
  echo 'PAPERS_MAX_CHUNKS=4'
} > /opt/bern/papers/papers.env
```

Then edit the two `OPENALEX_*` lines in place. Without a key OpenAlex shares $0.10/day per IP (about 90 people).

## 5. Run

```bash
IMG=bern-papers:<sha>
job() {
  docker run --rm --name bern-papers-job --network bern --cpus 4 --memory 8g \
    --env-file /opt/bern/papers/papers.env -v /opt/bern/papers/data:/work/data \
    "$IMG" python -m navigator.cli "$@"
}

job index                                               # entities + pages of the copy -> nav.* (the app's files are untouched)
job papers stats --limit-people 50 --max-pdfs 100       # dry run: no network, prints the upper bounds below
job papers all   --limit-people 50 --max-pdfs 100       # collect -> embed -> link for the next 50 people
```

`papers stats` (same as `--dry-run`) prints, before anything is spent:
`people.selected / known_openalex_id / to_search / already_decided_skipped`,
`openalex_requests_max.total` and `cost_usd_max`, `llm_calls_max.author_match` (and an upper bound for topic
labels), `works_max`, `pdf_downloads_max`, `chunks_max`. Check them against the OpenAlex budget ($1/day with a
free key) and the CPU time (e5 on CPU: ~3.7 chunks/s at 8 CPUs) before the real run.

Repeat the last line to go through everyone, 50 at a time. When `stats` shows `people.selected: 0`, everyone
has been decided; `job papers embed` and `job papers link` can be re-run alone at any time.

People from the team's OpenAlex source (`extractor: openalex`, exactly one OpenAlex author URL or id in their
`source_urls`/evidence) are matched by that id (`decided_by = known_id`): no author search, no LLM call. They show
up as `people.known_openalex_id` in `stats`.

## 6. Resume and idempotency

- A crashed or interrupted run is resumed by running the same command again.
- `collect` reads `data/papers/works.jsonl` and `author_matches.jsonl` from the previous runs: people already
  decided are skipped (a rules decision taken because the LLM was down is retried), PDFs with a final outcome
  are not fetched again, results merge by work id and entity id.
- Postgres writes are upserts (`nav.paper`, `paper_author`, `paper_chunk`: a chunk whose text did not change
  keeps its embedding); the `nav.author_match` audit does not repeat an unchanged decision.
- OpenAlex answers are cached in `data/cache/openalex/` for `OPENALEX_CACHE_DAYS` (30).
- `--redo` ignores the previous JSONL and decides every selected person again.

## 7. Check

```bash
docker exec bern-db-db-1 psql -U postgres -d bern -c "
  SELECT (SELECT count(*) FROM nav.entity) entities, (SELECT count(*) FROM nav.paper) papers,
         (SELECT count(*) FROM nav.paper_chunk) chunks,
         (SELECT count(*) FROM nav.paper_chunk WHERE embedding IS NULL) not_embedded,
         (SELECT count(*) FROM nav.research_profile) profiles"
docker exec bern-db-db-1 psql -U postgres -d bern -c "
  SELECT decided_by, count(*), count(chosen_author_id) chosen FROM nav.author_match GROUP BY 1"
cat /opt/bern/papers/data/papers/stats_all.json      # last run: OpenAlex usage and cost, LLM usage, PDF outcomes
```

## 8. Undo

The app never reads this data, so undoing is about the database only: restore the dump from step 3
(`pg_restore`, then `src/db/post-restore-age.sql`, see `src/db/README.md`), or empty the papers tables:

```bash
docker exec bern-db-db-1 psql -U postgres -d bern -v ON_ERROR_STOP=1 -c "
  TRUNCATE nav.similarity, nav.paper_topic, nav.topic_map, nav.author_match, nav.research_profile,
           nav.paper_chunk, nav.paper_author, nav.paper"
```

then `job index` once: a reindex re-projects the paper subgraph of AGE from the (now empty) tables.
`rm -rf /opt/bern/papers` removes the copy and the job's files.
