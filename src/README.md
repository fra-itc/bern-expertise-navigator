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

Built on **Apertus v1.5**, the Swiss open LLM. Fully self-hosted, so no data leaves Switzerland. Without an Apertus
endpoint everything still works, using a reviewed glossary and deterministic rules, and the UI says so.

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

**Without Docker** (Python 3.11): `make setup-local`, then add `LOCAL=1` to any target, e.g.
`make demo LOCAL=1` and `make serve LOCAL=1`.

**Crawling is always explicit.** `make crawl SOURCE=<name>` fetches one source. Sources already saved in
`data/pages/` are skipped unless you add `RECRAWL=1`. No other target touches the network.

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
| 5 Search | `search.py` | Query analysis (synonyms, lay terms, DE/EN/FR, person names) and match explanations written only from the cited evidence |
| Requests | `plain.py`, `cases.py` | Plain-language summary of a company request plus explanations of terms the glossary lacks (labelled *AI explanation – check*). Emails are a deterministic template: no generated claims |
| Pitch | `brief.py` | none in the claims: the brief and the officer's explanation are assembled only from the chosen partners, verbatim snippets, verified proof points and DOIs found on the institutions' pages |
| Showcase | `showcase.py` | none: live counts from the index, and proof points re-verified against the saved pages at startup |

## Storage backends

`navigator/storage.py` picks the backend from `DATABASE_URL` (capability matrix in its docstring):

- empty (default): files in `data/` (entities.jsonl, BM25 pickle, NumPy or Qdrant, SQLite cases), as before;
- set: Postgres from `db/` (`nav` tables, pgvector, FTS, AGE graph `expertise_graph`). `index --source X`
  then replaces only source X, in one transaction. Requires the migrations in `db/migrations/`.

Postgres tests: `TEST_DATABASE_URL=postgresql://bern_app:<pw>@127.0.0.1:<port>/bern pytest -q tests/test_pg_backend.py`
(wipes that database; use a throwaway container).

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

1. Add a block to `config/sources.yaml` (name, label, domains, seeds; optional `page_types` URL patterns).
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
| `POST /cases` · `GET /cases` · `GET /cases/{id}` | Company requests (staff actions carry `actor` + `role`) |
| `POST /cases/{id}/selection` · `/details` · `/brief` · `/draft` · `/outcome` | Workflow steps |
| `GET /briefs/{token}` | The executive brief behind a private link (read-only); 410 once disabled or expired |
| `POST /briefs/{token}/reply` | The company's reply from the brief (visit, call or question) |
| `POST /cases/{cid}/brief/revoke` | Disable the brief's private link |
| `GET /cases/{id}/invite.ics` | Calendar invite |
| `GET /glossary?lang=` · `GET /health` · `GET /stats` | Support |

## Repository layout

```
config/        sources.yaml · unibe_subdomains.txt · glossary.yaml · plain_glossary.yaml · showcase.yaml · medtech_areas.yaml · example_requests.yaml
app/navigator/ config · schema · llm · crawl · openalex · classify · extract · rules_extract · index · search · plain · cases · showcase · api · cli
app/navigator/static/  index.html · app.css · app.js   (no build step, no CDN: works air-gapped)
eval/          golden_set.yaml · run_eval.py
tests/         verifier, robots.txt, rules extractor, offline search, LLM client, request workflow
data/          (generated, git-ignored) pages/, entities.jsonl, vectors.npy, bm25.pkl, cases.db, eval_report.json
```

## Sovereignty, cost and scale

- **Model:** Apertus v1.5 8B (Apache 2.0) on one ~16 GB GPU in FP8. 70B is optional for better extraction.
- **No external services:** local embeddings (`multilingual-e5-base`, baked into the image), local vectors, local
  SQLite for requests. The UI loads nothing from the internet.
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
- nDSG / GDPR: no tracking and no query logging. Company requests stay in the local database and can be deleted from
  the UI. Example requests are fictional.
- Open source (Apache-2.0); outputs Open Commons (Hack Apertus T&C §6).
