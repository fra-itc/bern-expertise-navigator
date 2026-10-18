# Papers graph — pilot report and full-run proposal (2026-10-18)

For: Prachi / the team. Branch: `feat/papers-graph`. Runbook: [`papers-runbook.md`](papers-runbook.md).

## TL;DR

- Each indexed person's publications (OpenAlex metadata + abstracts, open-access PDFs only) are now in Postgres:
  pgvector chunks and an AGE graph (`Paper`, `AUTHORED`, `CITES`, `ABOUT`, `SIMILAR_TO`).
- **Apertus 70B makes every judgement call** (author matching, topic mapping), always choosing from a whitelist
  passed in the prompt. Embeddings: multilingual-e5-base on CPU. No proprietary model anywhere.
- Two pilots ran on the server (100 people). They caught three bugs that would have broken the full run; all
  three are fixed and tested.
- **Ask: go / no-go for the full overnight run** (788 people left, ≤ $0.32 OpenAlex, est. 3–5 h).

## Why it helps the navigator

Web pages describe people thinly; their papers say what they actually work on. Search on Postgres can now cite
papers (DOI) as evidence for an expert, and `SIMILAR_TO` / `ABOUT` connect people through shared research even
when their web pages use different words.

## Where Apertus is used

| Decision | Input given to Apertus | Output | Guard |
|---|---|---|---|
| Author match | the person (name, unit, role) + OpenAlex author candidates affiliated to Bern | one candidate id or none | answer must be one of the listed ids |
| Topic mapping | an OpenAlex topic + 8 nearest Topics of our graph (key, label, field) | a listed key or `NEW` | key/label/number parsed only within the list; anything else → `NEW` (logged) |

Deterministic shortcuts skip the LLM when the answer is certain: a person from the team's OpenAlex source is
matched by its known id (`known_id`); an OpenAlex topic whose normalised label already is a Topic key is reused
(`identical_key`).

## What ran (all on a copy of the app data, writing only to Postgres)

Backup before the first write: `/root/backups/…pre-papers.dump`. Image per commit: `bern-papers:<sha>`; the app
(`/opt/bern/app`) was never touched.

| Step | Result |
|---|---|
| `index` | 1015 entities, 11273 evidences, 10493 vectors (~8 min) |
| Pilot 1: 50 web-extracted people (ARTORG) | Apertus matched 32, 18 had no Bern-affiliated candidate; 646 papers, 51 OA PDFs |
| Topic fix + `topics --remap` | see below |
| Pilot 2: 50 people with a known OpenAlex id (`--people known`) | 50/50 matched by id, 0 searches, 0 author LLM calls; +1128 papers, 37 new OA PDFs (cap 100) |

### Postgres after both pilots

| | count |
|---|---|
| papers | 1774 (1754 with DOI) |
| chunks embedded (pgvector) | 2397 |
| research profiles | 82 |
| author decisions (audit) | 100 |
| graph | 1774 `Paper`, 2662 `AUTHORED`, 561 `CITES`, 5313 `ABOUT`, `SIMILAR_TO` 438 paper↔paper / 21 person↔person |

### Cost

| | Pilot 1 | Remap | Pilot 2 |
|---|---|---|---|
| OpenAlex | 83 requests, $0.053 | — | 51 requests (cached on re-run), ≤ $0.005 |
| Apertus calls | 474 | 210 | 152 |
| Apertus tokens (prompt / completion) | ~161k / 16k | 77k / 10k | 55k / 7k |
| e5 embedding | — | — | 1548 chunks in 318 s (7 CPUs) |

## Bugs found by the pilots (fixed, with tests)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | 262/442 topic answers "invalid choice" | Apertus answered with the label, the parser accepted only the key | `2f5c8a8`: whitelist-bound parsing (key, label or number), identity rule, strict JSON prompt, `papers topics --remap` |
| 2 | Store write failed: `UniqueViolation paper_doi_key` | OpenAlex has duplicate work records for one DOI (3 of 1754) | `788a190`: merge works sharing a DOI before the store, authorships/citations remapped; DOI already stored under another id keeps the stored id |
| 3 | Store write failed: `text fields cannot contain NUL` | 11/119 extracted PDF texts contain NUL bytes | `a922a10`: `clean_text` at extraction, chunking and store |

Both failed writes rolled back cleanly (DB unchanged); the re-run used the cached OpenAlex data.

Topic remap of pilot 1:

| | before | after |
|---|---|---|
| reused existing Topics | 10 | 232 |
| new Topics | 432 | 210 |
| invalid answers | 262 | 0 |
| Apertus calls needed | 442 | 210 |

The strict prompt rejects near-miss merges (e.g. "MRI in cancer diagnosis" no longer collapses into "Medical
Imaging Techniques"): fewer wrong edges, somewhat less connectivity. A `BROADER` hierarchy is the natural next
step if more connectivity is needed.

Tests: 180 passed / 16 skipped without a DB; the Postgres suites pass on a fresh database with migrations 0001–0006.

## Full overnight run — proposal

```bash
IMG=bern-papers:a922a10
job papers stats --max-pdfs 1500      # dry run first, numbers attached to this PR before starting
job papers all   --max-pdfs 1500      # everyone left; resumable with the same command
```

| | upper bound (`stats`, no network) | expected (scaled from the pilots) |
|---|---|---|
| people | 788 left (550 known id, 238 to search) | — |
| OpenAlex | 1027 requests, **$0.32** | well under the $1/day free-key budget |
| Apertus author match | 238 calls | ≤ 238 |
| Apertus topics | one call per OpenAlex topic not yet decided | ~1–2k calls (pilot 2: 152 for 1128 papers, decreasing) |
| papers | 23,640 | ~15k |
| OA PDFs | capped at 1500 | ~600–900 |
| chunks to embed | 118k | ~20k → ~70 min of e5 on 7 CPUs |
| total time | — | ~3–5 h |
| disk | 51 GB free | pilots used 528 MB → a few GB |

Safety:
- touches only `/opt/bern/papers` and Postgres; the app, its data and the deploy flow are untouched;
- CPU/memory capped container (`--cpus 7 --memory 8g`), Apertus via the same Keera gateway as the app;
- resumable: a crash is resumed by running the same command; each store write is one transaction;
- rollback: restore the pre-papers dump, or drop the paper tables and `job index` (runbook §7).

## What the run does not do yet

- **The app does not read Postgres.** After the run the RAG is complete in Postgres, but the frontend keeps
  using JSONL/SQLite until `DATABASE_URL` is set for the app. That waits on committing the server-only code
  (`openalex.py`, the case flow — issue #7) and importing the cases from SQLite.

## Asks

1. **Go / no-go for the full overnight run** (reply on this PR). It starts only after your go.
2. Review: `papers.py` (prompts, `dedupe_by_doi`, `clean_text`), `0004_papers.sql`.
3. Merge PR #6 (basic auth) before the next `make deploy`: `rsync --delete` removes `caddy.env` and the
   protection on `/cases` is lost.
