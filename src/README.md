# Bern Expertise Navigator

**Hack Apertus 2026 · Bern Economic Development Agency challenge**

One search across the University of Bern's medtech researchers (from OpenAlex publication records) and the public
websites of ARTORG and Diabetes Center Berne, plus a workspace that helps the canton **bring companies to Bern**. Every result is structured and linked to the page and the verbatim sentence that
supports it.

The app has three clearly separated areas:

| Area | Who | What |
|---|---|---|
| **Public navigator** (`#/`) | anyone | The challenge's deliverable: natural-language and keyword search with structured, source-backed results (person, role, affiliation, expertise, projects, infrastructure/services, why it matches, source link), a labs & facilities directory, and "How it works" with the measured success criteria |
| **Staff workspace** (`#/staff`, dark header) | the canton's business-development team, who enter their name | Company request (search field + filters) → plain-language explanation → choose Bern partners → **pitch & invite** |
| **Executive brief** (`#/b/<private link>`) | the company's CEO | A short, interactive brief whose only goal is a visit to Bern; saved as PDF with one click |

**The two outputs of a request** (step 3, once partners are chosen):

1. **For the officer:** a plain explanation of what was prepared and why: what she is sending, why each partner fits
   (with the jargon explained), what the CEO can check, and what we deliberately do not say.
2. **For the CEO:** the executive brief. A plain hook, "who you would meet" (each with a plain explanation, a verbatim
   quote and **Technical details** on demand, including publications with DOI), "Bern in numbers", a proposed
   half-day visit and "Plan your visit". **No overselling:** every statement is a verbatim quote from a public
   institutional page or a publication listed there, numbered and linked. The brief never claims anyone has agreed
   to meet and says nothing about money.

Built on **Apertus v1.5**, the Swiss open LLM. It can run fully self-hosted (`docker-compose.yml` with the `gpu`
profile: Apertus 8B on local vLLM, no network at runtime after the crawl). The team server runs differently (Germany,
Apertus 70B through a remote gateway, network at runtime): see [Deployment modes](#deployment-modes). Without an
Apertus endpoint everything still works, using a reviewed glossary and deterministic rules, and the UI says so.

---

## Quick start

All commands run from this `src/` directory. Apertus is reached through an OpenAI-compatible endpoint set with
`LLM_NAME`, `LLM_BASE_URL` and `LLM_API_KEY` in `.env`.

```bash
cp .env.example .env            # set LLM_BASE_URL / LLM_API_KEY, or use make up-gpu
make up                         # API + UI on http://localhost:8080 (Apertus at $LLM_BASE_URL)
make up-gpu                     # same, plus Apertus 8B served locally by vLLM (NVIDIA GPU, >= 16 GB)
make demo                       # from the saved pages: extract -> index -> eval (never crawls)
make bench                      # Apertus vs the no-LLM baseline on the golden set, as a Markdown table
                                #   (saved runs in data/eval/; make eval TAG=x saves one, make compare shows them)
make test                       # unit tests: no GPU, no network, no model download
```

`make demo` needs saved pages in `data/pages/*.jsonl`, which are **not** in the repository (`data/` is git-ignored).
Fetch them once with `make crawl SOURCE=artorg`, `make crawl SOURCE=dcb`, `make crawl SOURCE=unibe_web` and
`make crawl SOURCE=unibe` (network; robots.txt is checked for every URL, and `unibe_web` is limited to 22 medtech /
biomedical institute sites, 1,500 pages, 1 s delay). Pages matching a source's `skip_keywords` (e.g. former staff)
are skipped by the crawl and, for pages saved earlier, by `extract` too.
`unibe` is the OpenAlex source (`openalex.py`): University of Bern researchers with medtech publications since 2023,
from the public OpenAlex API, so a new fetch can differ from the team server's records.
`config/unibe_subdomains.txt` is still a placeholder seed list for a future web crawl of unibe.ch.

`make test` collects 234 tests (`pytest --collect-only -q`, 2026-10-18 after the papers merge: 217 pass); the 17 in
`tests/test_pg_backend.py` and `tests/test_pg_papers.py` are skipped unless `TEST_DATABASE_URL` is set.

## Deployment modes

| | Self-hosted (`src/docker-compose.yml`) | Team server (`src/deploy/docker-compose.yml`) |
|---|---|---|
| Start | `make up` / `make up-gpu` | `make deploy` (rsync + `docker compose up` on the server) |
| Services | api, Qdrant, optional vLLM (`gpu` profile) | api, Caddy (HTTPS) |
| Vectors | Qdrant (`QDRANT_URL=http://qdrant:6333` set by the compose file) | NumPy (`QDRANT_URL` empty) |
| Requests DB | SQLite `data/cases.db` | SQLite `data/cases.db` |
| `DATABASE_URL` | empty unless you set it | empty: the Postgres in `/opt/bern/db` is running but not connected |
| LLM | Apertus 8B on local vLLM, or `LLM_BASE_URL` | Apertus 70B via `gateway.keera.ch` (location declared by the provider, not verified) |
| Location | wherever you run it | Hetzner, Nuremberg, Germany |
| Runtime network | none in rules mode or with local vLLM, except fetching a company website when a link is given | LLM gateway calls (queries and company requests) and company websites |

`make deploy` uses `rsync --delete`: it overwrites or deletes the server's `data/` (corpus, index, pages,
`eval_report.json`) except `data/cases.db*` and `data/*.log`. See the header of `deploy/deploy.sh` and
`docs/server-handoff.md` before deploying.

**Without Docker** (Python 3.11): `make setup-local`, then add `LOCAL=1` to any target, e.g.
`make demo LOCAL=1` and `make serve LOCAL=1`.

**Crawling is always explicit.** `make crawl SOURCE=<name>` fetches one source. Sources already saved in
`data/pages/` are skipped unless you add `RECRAWL=1`. No other target touches the network.
A re-crawl writes to `pages/<name>.jsonl.partial` and replaces the saved file only when it finishes, so an
interrupted run keeps the previous pages. Each page also stores its outgoing `links` (`internal` / `external` /
`paper`); paper links (DOI, PubMed, PMC, arXiv, BORIS, `.pdf`) carry a normalised `paper_ref` and are recorded,
never fetched. To crawl into another data directory, set it as a real environment variable (it is read at import,
before `.env`): `cd app && NAV_DATA_DIR=/path/to/data python -m navigator.cli crawl --source <name> [--recrawl]`
(`NAV_CONFIG_DIR` likewise selects another `sources.yaml`).

**University of Bern comes from OpenAlex** (`type: openalex` in `config/sources.yaml`), not from crawling unibe.ch:
`make crawl SOURCE=unibe` reads the open OpenAlex API (CC0 data) for authors who signed medtech-field papers as
University of Bern since 2023. A person counts only through papers where *their own* authorship lists UniBE (OpenAlex's
"last known institution" mixes up namesakes). Each researcher becomes one record (name, ORCID, department as written on
their papers, research topics, recent publications with DOI), linked to their openalex.org page. Researchers who also
have an ARTORG or DCB profile are merged into that profile, which gains their publications. Without a key, OpenAlex
allows the first 10,000 matching papers; set `OPENALEX_API_KEY` (free, openalex.org/settings/api) for more.

## Using it

1. Open **Staff workspace** → choose *Business development*, enter your name → **New request**: paste the
   company's **website link** and/or information about the company (an email, a description), optionally say what
   they are looking for, set the company's country (Switzerland → canton) and a medtech area → niche (e.g.
   *Diabetes → Glucose sensing*), or click a fictional example → **Find partners in Bern**. The navigator reads the
   linked page plus up to 5 key pages of the same site (About, Products, Technology; robots.txt respected), explains
   the company in plain words, and lists the matching people, labs and facilities in Bern → tick the partners to
   propose. Links to private or internal network addresses are refused.
2. In **Pitch & invite**, add the company name and contact (asked only now) → **Prepare the pitch** → read *For you*,
   open the **executive brief**, *Save as PDF*, then **Prepare the email** (it links the brief) or download a
   calendar invite → **Mark as sent**.
3. The CEO answers from the brief itself: *I'd like to visit Bern*, *Let's talk first* or *I have a question*, with
   an optional message. The request moves to **Company replied**, a column at the top of the board, and the reply
   appears at the top of the request. The request page also shows how often the company opened the brief (time
   only, nothing about the reader; the officer's own preview doesn't count). The link works for 90 days after the
   pitch is prepared (`BRIEF_LINK_DAYS`) and can be disabled at any time; preparing the pitch again renews it.

Names are self-declared and stored only in the browser (prototype, no passwords); every action is recorded in the
request's activity log with that name.

Emails are never sent by the server: **Open in email app** uses `mailto:` and the officer sends from their own mail
client. **Calendar invite** downloads a standard `.ics` file.

## Pipeline

```
public websites ─► 1 crawl ─► 2 classify ─► 3 extract ─────────────► 4 index ─► 5 search & explain
 sources.yaml       robots.txt   URL rules +   Apertus (JSON schema)     BM25 +      hybrid RRF, lab→people,
                    (explicit)   Apertus       or rules baseline;        e5 vectors  fairness cap, cited "why",
                                               verbatim snippet or drop  (per snippet) honest abstention
                                                                                 │
             company request ─► plain language (glossary / Apertus) ─► matches ─► pitch & invitation
```

| Stage | Module | Where Apertus is used, and why |
|---|---|---|
| 1 Crawl | `crawl.py`, `openalex.py` | none (deterministic, polite, bounded; robots.txt incl. wildcards; directory pages kept via DOM text). UniBE: OpenAlex API records, affiliation checked per paper |
| 2 Classify | `classify.py` | only for pages the URL rules can't classify |
| 3 Extract | `extract.py`, `rules_extract.py` | **Main use.** Page → entities as constrained JSON; each value must quote the page verbatim or it is dropped. `rules_extract.py` is the no-LLM baseline that passes through the same verifier |
| 4 Index | `index.py` | none (local multilingual embeddings + BM25) |
| 6 Papers | `papers.py`, `openalex_client.py` | Chooses the OpenAlex author profile of each person among the given candidates (or none), and maps paper topics onto existing Topics; validated against the whitelist, rules when the LLM is down |
| 5 Search | `search.py` | Query analysis (synonyms, lay terms, DE/EN/FR, person names) and match explanations written only from the cited evidence |
| Requests | `plain.py`, `cases.py` | Plain-language summary of a company request plus explanations of terms the glossary lacks (labelled *AI explanation – check*). Emails are a deterministic template: no generated claims |
| Pitch | `brief.py` | none in the claims: the brief and the officer's explanation are assembled only from the chosen partners, verbatim snippets, verified proof points and DOIs found on the institutions' pages |
| Showcase | `showcase.py` | none: live counts from the index, and proof points re-verified against the saved pages at startup |

## Storage backends

`navigator/storage.py` picks the backend from `DATABASE_URL` (capability matrix in its docstring):

- empty (default, and what the team server uses today): files in `data/` (entities.jsonl, BM25 pickle, NumPy
  vectors when `QDRANT_URL` is empty or Qdrant when it is set, SQLite cases);
- set: Postgres from `db/` (`nav` tables, pgvector, FTS, AGE graph `expertise_graph`). `index --source X`
  (`make index SOURCE=X`) then replaces only source X, in one transaction. Requires the migrations in
  `db/migrations/`. The code is on `main` (PR #3); it is not active on the team server.

Postgres tests: `TEST_DATABASE_URL=postgresql://bern_app:<pw>@127.0.0.1:<port>/bern pytest -q tests/test_pg_backend.py tests/test_pg_papers.py`
(wipes that database; use a throwaway container).

## Papers (OpenAlex): richer graph, better matching

The academic papers of the indexed people become citable evidence and new graph edges. Network access happens
only on this explicit command (like `crawl`):

```bash
cd app
python -m navigator.cli papers collect   # OpenAlex + OA PDFs -> data/papers/ (+ nav.paper* with DATABASE_URL)
python -m navigator.cli papers embed     # e5 vectors of abstracts + full-text chunks (Postgres only)
python -m navigator.cli papers link      # SIMILAR_TO (kNN), ABOUT (topics), CITES -> AGE graph (Postgres only)
python -m navigator.cli papers           # all three; options: --limit-people N --max-pdfs N --no-pdf --no-llm --workers N
python -m navigator.cli papers stats     # dry run (= --dry-run): max OpenAlex requests/cost, LLM calls, PDFs, chunks
make papers [PAPERS_STEP=collect]        # same through make
```

| Step | What happens | Decision rule |
|---|---|---|
| Institutions | `PAPERS_RORS` (default University of Bern `https://ror.org/02k7v4d05`, Inselspital `https://ror.org/01q9sj412`, both checked on ror.org) resolved to OpenAlex ids at run time | a ROR that does not resolve is printed as a warning, never dropped silently |
| Candidates | one OpenAlex author search per person, filtered to Bern affiliations (child institutes through `lineage`), at most `PAPERS_MAX_CANDIDATES` | no candidates → no match, no LLM call |
| Author match | **Apertus chooses one id among the candidates it was given, or `none`** (person card: name, role, unit, institute, expertise; candidate cards: names, affiliations with years, topics, works count) | an id outside the list is discarded. **LLM down → rules**: identical normalised name **and** Bern affiliation **and** exactly one such candidate, otherwise no match. Every decision (candidates, choice, reason, llm/rules, model) is audited in `nav.author_match` / `data/papers/author_matches.jsonl` |
| Works | the newest `PAPERS_MAX_WORKS` (30) works of the last `PAPERS_YEARS` (10) years, no paratext; plus works linked on the entity's **own** page (`paper_ref` DOI/PubMed: page type = entity type and the page belongs to exactly one entity of that type) | co-authors matched to other people get their own link; BORIS/arXiv/PMC/PDF links are counted as `unsupported_scheme` |
| Full text | **only open-access works** (`open_access.is_oa`) and only the `pdf_url` of OA locations; robots.txt per host, 1 s per host, max `PAPERS_PDF_MAX_MB` (20 MB, header and stream), `PAPERS_PDF_TIMEOUT` (30 s), content type + `%PDF-` magic checked, first `PAPERS_PDF_MAX_PAGES` (40) pages | kept in `data/papers/pdf/<sha1(pdf_url)>.pdf`, text in `data/papers/text/<sha1>.txt`; status per work in `fulltext_status` |
| Chunks | `title. abstract` + windows of `PAPERS_CHUNK_WORDS` (200 words: median 357 e5 tokens on a real paper, p90 567, e5 truncates at 512) with `PAPERS_CHUNK_OVERLAP` (30), at most `PAPERS_MAX_CHUNKS` (8) per paper (the beginning of the paper; references at the end are left out) | e5 `passage: ` prefix; embeddings kept when the text is unchanged |
| Vectors | paper = normalise(mean(abstract) + mean(full text)); a person's **research profile** = normalised mean of its papers | `nav.paper.embedding`, `nav.research_profile` |
| SIMILAR_TO | kNN through HNSW, `SIMILAR_K` (5) neighbours per node, threshold `auto` = quantile `SIMILAR_QUANTILE` (0.9) of the kNN cosines but never below `SIMILAR_MIN` (0.80), or a fixed cosine | the distribution (min, p10…p99, max) and the threshold are printed and stored with each edge |
| ABOUT | each OpenAlex topic is decided once: identical normalised label of an existing Topic → that Topic (rules, no LLM); otherwise the `TOPIC_SHORTLIST` (8) existing Topics nearest by embedding are the whitelist, numbered with key and label, and **Apertus answers one key or `NEW`** (reuse only for the same research concept; subfield/field of the OpenAlex topic in the prompt) | the answer is resolved only within the shortlist (key, label or number, exact after normalising case/accents/punctuation); anything else → new Topic (`origin: 'openalex'`), audited as `invalid choice`. LLM down → new Topic. `papers topics --remap` decides every topic again on a populated DB (no collect/embed) |

**Search** (Postgres backend, `USE_PAPERS=1`): the nearest paper chunks give each author its best paper for the
query. That ranking enters RRF with weight `PAPER_WEIGHT` (0.8); the chunk's cosine counts as semantic evidence
under the **same** abstention and result-floor thresholds; the fairness cap is unchanged. A matched person also
surfaces people linked by `SIMILAR_TO` (score × `SIMILAR_DAMPING` 0.6 × similarity, `via` = that person). The
result format is unchanged: a paper is one more `sources[]` entry with `field: "publication"`, the DOI (or OpenAlex)
URL and a verbatim sentence of the chunk, and `why_match` quotes it (“Author of “<title>” (2024), which says: …”).
The file backend can run `papers collect` (JSONL only); its search ignores papers (capability matrix in `storage.py`).

**Costs and time** (measured on 3 people, extrapolated to ~700):

| | per person | ~700 people |
|---|---|---|
| OpenAlex calls | 1 author search ($0.001) + 1 works list ($0.0001), page-linked DOIs 50 per call | ~1,400 calls + a few dozen, **≈ $0.78**: needs `OPENALEX_API_KEY` (free key: $1/day); without a key the IP's $0.10/day stops after ~90 people (429, then the circuit breaker) |
| LLM (Apertus) | 1 match call ≈ 790 prompt + 80 completion tokens (only with ≥ 1 candidate) | ~700 calls ≈ 0.6 M tokens; topics: 1 call per distinct OpenAlex topic (~1–2k, ≈ 0.6 M tokens) |
| Works / PDFs | ≤ 30 works; ~80% OA, ~40% with an OA `pdf_url` | ≤ 21k works, ≤ ~8k PDF downloads (live: 2.6 MB, 109k chars of text): **≈ 10–20 GB on disk** for `data/papers/pdf/`; `--max-pdfs N` bounds a run |
| Chunks | ≤ 30 abstracts + ≤ 8 per OA PDF (live: 30 + 8 for 90 works) | ≤ ~21k abstracts + ~70k full-text chunks ≈ 90k (co-authored works are stored once, so fewer) |
| Embedding (e5-base, CPU) | measured in the app image with `--cpus=8`: **3.7 chunks/s** | ≈ 90k / 3.7 ≈ **7 h**; `PAPERS_MAX_CHUNKS=4` ≈ 4 h; abstracts only (`--no-pdf`) ≈ 1.5 h. Incremental afterwards |

Re-runs are cheap: OpenAlex responses are cached in `data/cache/openalex/` (`OPENALEX_CACHE_DAYS`, 30), PDFs and texts are
kept, `papers embed` only embeds chunks without a vector. Set `OPENALEX_API_KEY` / `OPENALEX_MAILTO` in `.env`.
`papers collect` resumes from `data/papers/*.jsonl`: people already decided are skipped (a rules decision taken
because the LLM was down is retried), final PDF outcomes are kept, results merge by work id and entity id, so a
re-run never duplicates; `--limit-people N` processes the next N people, `--redo` starts over. Entities that come
from OpenAlex (`extractor: openalex` with exactly one OpenAlex author URL/id) are matched by that id
(`decided_by: known_id`): no author search, no LLM call. Server runbook: [`docs/papers-runbook.md`](../docs/papers-runbook.md).

## How we meet the success criteria

| # | Criterion | Mechanism | Check |
|---|---|---|---|
| 1 | ≥ 80% expected experts in top 10 | Hybrid BM25 + vectors, RRF, lab → head-of-lab propagation | `make eval` → `recall_at_k` |
| 2 | Synonyms / lay terms | `config/glossary.yaml` + Apertus expansion + multilingual embeddings | `synonym_twins_consistent` |
| 3 | 100% traceable | Snippet must occur verbatim on the crawled page or OpenAlex record, else dropped (`data/rejected.jsonl`) | `traceability`, `tests/` |
| 4 | Structured results | `SearchResult`: person/unit, role, affiliation, institution, expertise, projects, infrastructure, contact, why, related, sources, confidence | `/docs` |
| 5 | All three sources | `sources.yaml`: `unibe`, `artorg`, `dcb` | `/stats` |
| 6 | Easy to extend | One YAML block, then `make crawl SOURCE=<name> && make pipeline` | live |
| — | Honest when unsure | Weak semantic match **and** low word coverage → "no verifiable source"; unknown person name → "no such person" | out-of-domain queries in the golden set |
| — | Fair discoverability | Max `MAX_PER_UNIT` people and `MAX_PER_UNIT` labs/projects per unit in the top k | config |
| — | Profiles first | At equal relevance, people known only from publication records rank slightly below institute profiles (`RECORD_ONLY_WEIGHT`, 0.9) | config |

## Adding a new institution

1. Add a block to `config/sources.yaml` (name, label, domains, seeds; optional `page_types` URL patterns;
   optional `extra_skip_keywords`, URL substrings never fetched, added to `defaults.skip_keywords`).
2. `make crawl SOURCE=<name>`, then `make pipeline`. No code changes.

Proof points, research themes and engagement routes are in `config/showcase.yaml`. Each quote is checked verbatim
against the saved page, and anything unverifiable is dropped automatically. The plain-language glossary is
`config/plain_glossary.yaml` (EN/DE).

## API (selection)

| Endpoint | Purpose |
|---|---|
| `GET /search?q=&k=&source=&type=` | Search; every result has `sources[{url, snippet, field}]` |
| `GET /entity/{id}` | Full entity with all evidence and linked people/labs |
| `GET /showcase` | Landing data: themes (live), verified proof points, labs, facilities |
| `POST /cases` · `GET /cases` · `GET /cases/{id}` · `DELETE /cases/{id}` | Company requests (staff actions carry `actor` + `role`) |
| `POST /cases/{id}/selection` · `/details` · `/matches` · `/rematch` · `/brief` · `/draft` · `/outcome` | Workflow steps |
| `POST /companies/suggest` | Broad search without a company: up to three companies proposed by Apertus, each checked on its own homepage |
| `POST /documents` · `GET /documents/types` | Extract text from a document shared by the company (the file is not stored) |
| `GET /briefs/{token}` | The executive brief behind a private link (read-only); 410 once disabled or expired |
| `POST /briefs/{token}/reply` | The company's reply from the brief (visit, call or question) |
| `POST /cases/{cid}/brief/revoke` | Disable the brief's private link |
| `GET /dashboard` | Staff dashboard: Apertus cost per request and per action, re-extraction cost, recall of saved eval runs |
| `GET /cases/{id}/invite.ics` | Calendar invite |
| `GET /understand` · `GET /archetypes` · `GET /medtech-areas` · `GET /examples` | Live request parsing (place, area, niche; no AI), filters, fictional examples |
| `GET /glossary?lang=` · `GET /health` · `GET /stats` | Support |

`/health` → `llm_available` only means that `GET {LLM_BASE_URL}/models` answered within 3 s (cached for 60 s).
`/search` → `llm_used` is `llm_available` combined with `USE_LLM_EXPANSION` / `USE_LLM_EXPLAIN`: it does not say
whether an LLM call succeeded (an `LLMError` falls back to the glossary and templates). The calls that do succeed are
counted per web request in `data/usage.jsonl` (see *Dashboard* below).

## Repository layout

```
config/        sources.yaml · unibe_subdomains.txt · glossary.yaml · plain_glossary.yaml · showcase.yaml · medtech_areas.yaml · example_requests.yaml
app/navigator/ config · schema · llm · crawl · openalex · classify · extract · rules_extract · index · search · plain · cases · showcase · api · cli
               storage · filestore · pgstore · graph · brief · company · documents · understand · archetypes · suggest · reply · dashboard
               papers · papers_links · openalex_client   (papers graph: OpenAlex publications in Postgres, see docs/papers-runbook.md)
db/            PostgreSQL 18 + pgvector + AGE stack and migrations (see db/README.md)
deploy/        team server: deploy.sh, docker-compose.yml, Caddyfile
tools/         replay_topics.py (re-run the papers topic mapping offline)
app/navigator/static/  index.html · app.css · app.js   (no build step, no CDN: works air-gapped)
eval/          golden_set.yaml · run_eval.py · compare.py
tests/         verifier, robots.txt, rules extractor, offline search, LLM client, request workflow, brief, company web,
               documents, request understanding, company suggestions, replies, match gate, dashboard, Postgres backend,
               papers (collect, dedupe, links, resume, Postgres store, topic replay)
data/          (generated, git-ignored) pages/, entities.jsonl, vectors.npy, bm25.pkl, cases.db, eval_report.json,
               eval/, usage.jsonl, papers/ (works.jsonl, author_matches.jsonl, pdf/, text/), cache/openalex/
```

## Sovereignty, cost and scale

- **Model:** self-hosted: Apertus v1.5 8B (Apache 2.0) on one ~16 GB GPU in FP8; 70B is optional for better
  extraction. Team server: Apertus 70B through a remote gateway (see [Deployment modes](#deployment-modes)).
- **No other external services:** local embeddings (`multilingual-e5-base`, baked into the image), local vectors,
  local SQLite for requests. The UI loads nothing from the internet. The only runtime network calls are the LLM
  endpoint (if remote) and company websites linked in a request. The explicit `crawl` and `papers` commands also go
  to the network (`papers`: the public OpenAlex API and open-access PDFs).
- **Cost:** LLM work at indexing time is one call per page, cached per page. A search costs at most one expansion
  call plus short explanation calls, and both can be switched off. Token usage is written to
  `data/extract_stats*.json` and `data/eval_report.json`.
- **Dashboard** (staff workspace, *Dashboard* tab; `GET /dashboard`, staff login): every web request that calls
  Apertus is logged to `data/usage.jsonl` (route, request id, tokens, latency; never the request text), priced with
  `LLM_PRICE_IN_CHF_PER_M` / `LLM_PRICE_OUT_CHF_PER_M`. It shows cost per request and per action, response time
  (median, 95th percentile), the cost of re-extracting every saved page (measured after an Apertus extraction,
  estimated from page length before), and recall@10 with the other metrics of each saved eval run
  (`make eval TAG=…`, `make bench`).

## Compliance

- Public pages only; robots.txt (with wildcard rules) respected; polite delay; identifiable user agent; crawling only
  on explicit command. OpenAlex: public API, CC0 data, paced below its rate limit.
- Only what the institutions already publish; every record points to its source page. Copyright stays with them.
- nDSG / GDPR: no tracking. The app does not store search queries (the Apertus usage log keeps only the route,
  request id, tokens and latency), but the HTTP access logs (uvicorn, and the
  reverse proxy if it logs) record request URLs, including `/search?q=`. With a remote LLM endpoint, queries and
  company requests are sent to that provider. Company requests stay in the local database and can be deleted from
  the UI. Example requests are fictional. Search results show the work emails the institutions publish.
- Access: roles and names are chosen in the browser; the app itself has no authentication. On the team server the
  staff API (`/cases`, `/documents`, `/dashboard`, API docs) is behind basic auth (`deploy/Caddyfile`, hash in the
  server-only `caddy.env`, which `deploy.sh` never touches). Without it, the request API (including `DELETE`) is
  open to anyone who can reach the server. Deploy only from an up-to-date `main`: an older tree removes the auth
  (see `docs/server-handoff.md`).
- Open source (HackApertus T&C §6): code Apache-2.0; documentation CC-BY-4.0; submitted datasets
  CDLA-Permissive-2.0.
