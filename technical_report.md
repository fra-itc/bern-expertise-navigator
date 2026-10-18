# Technical report — Bern Expertise Navigator, TODO(team): team name

A deeper write-up than the README: what we built, how it works, and what the numbers say.

- **Challenge:** Bern Economic Development Agency — Research & Expertise Navigator
- **Event:** On-site Liebefeld
- **Team:** TODO(team): team name — TODO(team): members
- **Demo:** TODO(team): link to the demo video (max. 2 min)
- **Commit:** TODO(team): commit SHA of the submitted version

## 1. Summary

The canton wants companies to invest in Bern. Its business-development officers receive requests from companies
across many domains, often full of jargon ("needle-free CGM patch, AID integration, CE marking under the MDR"), and
must then find out who in Bern's research landscape could help. We built a navigator for that job:

1. explain the request in plain language, with every technical word explained;
2. match it to researchers, labs, projects and facilities in Bern, each backed by a verbatim sentence on a public
   page;
3. draft the invitation (email in EN/DE/FR or a calendar invite) with only the chosen partners and verified
   "why Bern" facts.

Step 3 produces **two outputs**: a plain explanation for the officer of what she is sending and why, and an
interactive **executive brief** for the company's CEO (shareable private link, one-click PDF). The brief's single goal
is a visit to Bern. It avoids overselling: every statement is a verbatim quote from a public institutional page or a
publication (DOI) listed there, numbered and linked; nothing about money; no claim that anyone has agreed to meet.
The app separates its users clearly: a **public navigator** (the challenge's search deliverable), a **staff
workspace** for the business-development team, and the **brief** the CEO receives.

Numbers so far are all from the **rules baseline** (no LLM calls), on our golden set `src/eval/golden_set.yaml`
(30 queries). There are two runs, on different corpora, and **neither recorded its commit**:

| Run (rules baseline) | Corpus | recall@10 | Synonym twins | Traceability | Abstention | Reproducible |
|---|---|---|---|---|---|---|
| Development laptop, crawl of 2026-10-18 | 396 entities (ARTORG + DCB, rules extractor) | 96% | 71% | 100% | 100% | No: no `eval_report.json` committed, commit not recorded |
| Team server, `eval_report.json` of 2026-10-18 15:46 UTC | 1015 entities (396 rules + 619 OpenAlex) | 88% | 71% | 100% | 100% | No: the report records neither commit nor corpus (corpus read from the server state) |

Median latency 0.11 s on CPU was measured on the development-laptop run only. TODO(team): regenerate the eval with
the commit, corpus and model recorded (rules baseline and Apertus), and report one recall@10 per configuration.
Apertus numbers: TODO(team) (see §5).

## 2. Architecture

```
public websites ─► crawl ─► classify ─► extract (Apertus | rules) ─► verify ─► index ─► search / explain
                                                                         │
company request ─► plain language (glossary | Apertus) ─► matches ─► pitch & invitation (brief, mailto / .ics)
```

| Component | Module (`src/app/navigator/`) | What it does |
|---|---|---|
| Crawl | `crawl.py` | Config-driven, bounded best-first crawl; robots.txt including wildcard rules; polite delay; content-hash dedup. Text is article extraction, or boilerplate-stripped DOM text when that keeps more, because team grids and member cards are dropped by article extractors. Truncates "more recent projects" teaser blocks. Runs only on explicit command. |
| Classify | `classify.py` | URL rules per source; Apertus only for pages the rules can't place. |
| Extract | `extract.py` | Apertus with JSON-schema output; every value quotes a snippet. |
| Rules baseline | `rules_extract.py` | No-LLM extractor: profile headers, directory cards, contact blocks, team lines, research sentences. Same output format, same verifier. Used when Apertus is unreachable, and as the comparison baseline. |
| Verify | `extract.verify` | Snippet must occur in the page text and contain the value, or the claim is dropped and logged. A relation (person → lab/project) is accepted when the lab/project is the page's own heading and the person's verbatim line is on it. |
| Link | `extract.link_site_structure`, `derive_units` | Site hierarchy as evidence (pages under `/research/aihn/` belong to that lab). Labs that exist only as headings on team pages become lab entities, cited by that heading. |
| Index | `index.py` | BM25 plus `multilingual-e5-base` vectors for each entity profile and each evidence snippet. File backend: in-process NumPy store when `QDRANT_URL` is empty (as on the team server), Qdrant when it is set (`src/docker-compose.yml`). Postgres backend (pgvector + FTS + AGE graph) when `DATABASE_URL` is set: on `main`, not active on the team server. |
| Search | `search.py` | Glossary and Apertus query analysis; RRF of BM25(query), BM25(expansions) and vectors; matching labs/projects surface their people, with the head of the lab first; fairness cap; cited explanations; abstention. |
| Requests | `plain.py`, `cases.py` | Plain-language analysis, matching (niche filters, senior contacts first), request status (SQLite), email template, `.ics`. |
| Pitch | `brief.py` | Output 1 (officer explanation) and Output 2 (executive brief): chosen partners only; quotes chosen from the partner's or linked project's verbatim sentences that name a topic from the request; publications matched by author surname from 143 DOIs on the institutions' pages; numbered sources. |
| Showcase | `showcase.py` | Research themes with live counts, verified proof points, lab and facility directories. |
| UI | `static/` | Vanilla HTML/CSS/JS, no CDN or build step, EN/DE/FR, light/dark, responsive. |

**Abstention** uses two signals, and both must be weak. The best cosine to the original query must be below 0.825,
**and** at most half the query's words may occur in the top candidates, with no expansion term occurring verbatim.
A person name in the query that matches no indexed entity also triggers abstention. On the golden set,
single-signal thresholds could not separate out-of-scope queries from hard in-scope ones; the combined rule does.

### Deployment modes

There are two compose files and two very different deployments. We describe both as they are.

**a) Self-hosted, air-gapped after the crawl** (`src/docker-compose.yml`, `make up` / `make up-gpu`)

- API/UI and Qdrant, plus, with the `gpu` profile, Apertus 8B served locally by the Swiss AI vLLM image
  (`ghcr.io/swiss-ai/vllm_apertus_1.5_release`, one NVIDIA GPU with >= 16 GB).
- **Build time** (network): images, Python wheels, the e5 model (baked into the image), Apertus weights, and the
  crawl of the public websites.
- **Runtime:** no network in rules mode or with the local vLLM. Pages, entities, vectors, BM25 and the request
  database are local files; the API runs with `HF_HUB_OFFLINE=1`; the UI loads no external resources; emails go
  out through the officer's own mail client. Exception: a company request with a **website link** fetches that
  site (the linked page plus up to 5 key pages) at runtime; leave the link empty to stay offline.
- This mode can run on-premise or with any hosting provider; we have not deployed it on Swiss infrastructure.

**b) The team server (the live demo at `https://bern-expertise.ch`)** (`src/deploy/`, `make deploy`)

- Hetzner vServer in Nuremberg, Germany (`nbg1`), 8 vCPU, 15 GiB, **no GPU**. Caddy (HTTPS) in front of the API.
- **LLM:** Apertus v1.5 **70B** (`apertus-v1-5-70b`) through a remote OpenAI-compatible gateway
  (`gateway.keera.ch`). Its location in Switzerland is declared by the provider, not verified by us.
- **Runtime network:** yes. Query expansion, match explanations and request summaries send the search query or
  the company request to the gateway; company websites are fetched when a link is given.
- **Storage:** file backend: `entities.jsonl`, BM25 pickle, NumPy vectors (no Qdrant), SQLite for requests.
  PostgreSQL 18 + pgvector + AGE runs on the same host and the Postgres backend is on `main`, but the app is not
  connected to it (`DATABASE_URL` is empty).
- **Exposure:** search results are public and include the work emails the institutions publish. Until 2026-10-18
  16:45 UTC the request API (including `DELETE` and company contact fields) was reachable without authentication;
  since then basic auth protects the staff API on the server (PR #6, not yet merged into `main`).
- **Backups:** none for the request database or the corpus. `make deploy` runs `rsync --delete`, which overwrites
  or deletes the server's `data/` except `cases.db*` and logs.

Hosting is outside the Canton of Bern's ICT, as the brief requires. We do not claim that no data leaves
Switzerland: mode (b) runs in Germany and calls a remote LLM.

## 3. Use of Apertus

- **Model:** code default `swiss-ai/Apertus-v1.5-8B` (mode a); the team server uses `apertus-v1-5-70b` (mode b).
  Switching is a change of `LLM_NAME` / `LLM_BASE_URL`.
- **How it is used:** inference: structured extraction, query understanding, plain-language explanation
- **Where it runs:** mode a: vLLM (`ghcr.io/swiss-ai/vllm_apertus_1.5_release`) on one GPU; mode b: the remote
  gateway `gateway.keera.ch` (location declared by the provider, not verified).
- **What the API reports:** `/health` → `llm_available` means only that `GET {LLM_BASE_URL}/models` answered
  within 3 s (cached for 60 s). `/search` → `llm_used` is `llm_available` combined with the expansion/explain flags;
  it does not record whether a call succeeded (an `LLMError` falls back to the glossary and templates). LLM calls
  are not logged.

| Use | Why AI here | Guard-rail |
|---|---|---|
| Extraction (main use) | Heterogeneous pages (DE/EN, cards, prose); rules alone miss most expertise phrasing | JSON schema; verbatim snippet per value; verifier drops the rest; rules baseline measures the gain |
| Plain-language request summary | The officer is not a domain expert | Sees only the request text; labelled "Summary by Apertus" |
| Explaining jargon | Endless medtech vocabulary | Reviewed glossary first; AI explanations only for missing terms, labelled "AI explanation – check" |
| Query analysis | Lay ↔ technical ↔ DE/FR terms; detecting person names | Only adds search terms; an unknown person leads to abstention |
| Match explanation | Readable "why" | Numbered evidence only; rejected if it cites other evidence; deterministic fallback |

Not AI: the invitation email (template with the chosen partners and verified quotes only), the showcase, ranking.
Temperature 0. The client degrades from `json_schema` to `json_object` to prompt-only JSON, and detects an
unreachable endpoint in about 3 s, so the UI keeps working in rules mode.

## 4. Data

- Public pages of `www.artorg.unibe.ch` (373 pages) and `www.dcberne.com` (54 pages), crawled on 2026-10-18.
  robots.txt was checked for every URL; an audit found 0 disallowed fetches.
- Extracted (rules baseline, development laptop): 396 entities (282 people, 21 labs, 82 projects, 11 facilities)
  with 2,414 verbatim snippets. TODO(team): recount snippets and DOIs (143) on the submitted corpus.
- **UniBE** means two different things today:
  - on `main`, `unibe` is a web source whose seed list `config/unibe_subdomains.txt` is still a 3-host placeholder,
    and the golden set has no UniBE query yet;
  - on the team server, `unibe` is 619 records (556 people, 63 units, 8,838 evidence snippets) built from
    openalex.org author profiles by code that is not committed yet (`openalex.py`). The server corpus is 1015
    entities with 11,274 evidence snippets (396 rules + 619 OpenAlex);
  - a separate web crawl of 1,500 unibe.ch pages exists on the server but is not used by the app.
  - TODO(team): commit the OpenAlex code (issue #7), fill `unibe_subdomains.txt`, add UniBE queries to the golden set.
- Personal data: only what the institutions publish on public team/profile pages (names, roles, work emails).
  Company requests are stored locally and can be deleted. All example requests are fictional.
- Copyright stays with the institutions; `data/` is not in the repository.

## 5. Limitations

- **No Apertus numbers yet.** The development laptop (6 GB GPU) cannot host Apertus 8B; the team server reaches
  Apertus 70B, but no eval has been run with it, so all reported numbers use the rules baseline. Apertus extraction and expansion should improve
  expertise coverage and lay-term twins (71%). The one recall miss ("tiny robots steered by sound waves") needs
  expansion.
- **Golden set bias.** We built the 30 queries ourselves from the same pages and tuned the abstention thresholds on
  them; the numbers are optimistic until others add queries.
- **Rules extractor** heuristics occasionally mistake headings for names or miss relations. The verifier keeps every
  claim traceable but not necessarily complete.
- **Plain language without Apertus** is extractive: the summary repeats the request's own sentences, with glossary
  explanations alongside. Match explanations are English-only in this mode.
- **Authentication:** roles and names are chosen in the browser. On the team server, basic auth on the staff API
  was added on 2026-10-18 (PR #6, not yet merged); before that the request API was public. Search is public.
- **No backups** of the request database or the corpus on the team server; a redeploy overwrites `data/`.
- **The deployed code is not fully committed:** the team server runs files that differ from `main`, including
  `openalex.py`. TODO(team): commit and push before every deploy and record the deployed commit.
- JavaScript-rendered pages, PDFs and images are not read.

## 6. Reproducibility

```bash
cd src && cp .env.example .env       # set LLM_BASE_URL / LLM_API_KEY (or: make up-gpu)
make crawl SOURCE=artorg && make crawl SOURCE=dcb   # network; data/pages/ is not in the repository
make up && make demo                 # from the saved pages: extract -> index -> eval
make test                            # tests, no network / GPU / model download
```

Without Docker: `make setup-local && make demo LOCAL=1 && make serve LOCAL=1`. Reported numbers: CPU only (WSL2,
22 cores, 31 GB RAM), `EXTRACTOR=rules`, e5-base, golden set `src/eval/golden_set.yaml`, crawl of 2026-10-18,
commit TODO(team): not recorded. `make demo` needs `data/pages/*.jsonl`, which are not in the repository: run
`make crawl` first. The server's OpenAlex records cannot be reproduced from `main` yet (see §4).

## License

Per the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions) §6 "What you build is open source":
code: Apache-2.0 ([`LICENSE`](LICENSE)); this report and the other documentation: CC-BY-4.0.
