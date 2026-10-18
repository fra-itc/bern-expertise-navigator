# Docker (default):  make up / make pipeline / make eval
# Without Docker:    make setup-local, then add LOCAL=1 to any target (e.g. make pipeline LOCAL=1)
SOURCE ?=
SRC_ARG := $(if $(SOURCE),--source $(SOURCE),)
ifeq ($(LOCAL),1)
PY := cd app && ../.venv/bin/python
PY_ROOT := .venv/bin/python
PY_ENV = env $(1) .venv/bin/python
else
PY := docker compose run --rm api python
PY_ROOT := docker compose run --rm api python
PY_ENV = docker compose run --rm $(addprefix -e ,$(1)) api python
endif

.PHONY: up up-gpu down setup-local serve crawl extract index pipeline stats papers eval compare bench test logs demo deploy

up:            ## API/UI on :8080 + Qdrant; Apertus at $$LLM_BASE_URL
	cp -n .env.example .env || true
	docker compose up -d --build

up-gpu:        ## same, plus Apertus served locally by vLLM
	cp -n .env.example .env || true
	docker compose --profile gpu up -d --build

down:
	docker compose --profile gpu down

setup-local:   ## Python venv for running without Docker (uses uv if available)
	cp -n .env.example .env || true
	command -v uv >/dev/null && uv venv -q --python 3.11 .venv || python3.11 -m venv .venv
	(command -v uv >/dev/null && uv pip install -q --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
	   || .venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch==2.5.1)
	(command -v uv >/dev/null && uv pip install -q --python .venv/bin/python -r app/requirements.txt \
	   || .venv/bin/pip install -q -r app/requirements.txt)

serve:         ## LOCAL=1 only: API/UI on :8080
	cd app && ../.venv/bin/uvicorn navigator.api:app --host 0.0.0.0 --port 8080

crawl:         ## explicit only: make crawl SOURCE=artorg (skips if already saved; RECRAWL=1 to fetch again)
	@test -n "$(SOURCE)" || { echo "Name the source: make crawl SOURCE=<name>"; exit 1; }
	$(PY) -m navigator.cli crawl $(SRC_ARG) $(if $(RECRAWL),--recrawl,)

EXTRACTOR ?= auto
extract:       ## Apertus structured extraction + snippet verification (EXTRACTOR=auto|apertus|rules)
	$(PY) -m navigator.cli extract $(SRC_ARG) --extractor $(EXTRACTOR)

index:         ## SOURCE=x: the Postgres backend replaces only source x; the file backend always rebuilds all
	$(PY) -m navigator.cli index $(SRC_ARG)

pipeline: extract index   ## from saved pages (never crawls); SOURCE=x re-extracts only x (index: see above)

demo:          ## from the SAVED pages (no network): extract (Apertus if reachable, else rules), index, eval
	@ls data/pages/*.jsonl >/dev/null 2>&1 || { echo "No saved pages in data/pages — run 'make crawl' once first."; exit 1; }
	$(MAKE) extract
	$(MAKE) index
	$(MAKE) eval
	@echo "Open http://localhost:8080  (LOCAL=1: run 'make serve LOCAL=1')"

stats:
	$(PY) -m navigator.cli stats

PAPERS_STEP ?= all
papers:        ## explicit only (network: OpenAlex + OA PDFs): make papers [PAPERS_STEP=collect|embed|link|topics|stats] (embed/link: Postgres)
	$(PY) -m navigator.cli papers $(PAPERS_STEP)

TAG ?=
eval:          ## recall@10, synonym twins, traceability, abstention (TAG=name also saves data/eval/<name>.json)
	$(PY_ROOT) eval/run_eval.py $(if $(TAG),--tag $(TAG),)

TAGS ?=
compare:       ## saved eval runs side by side, as Markdown (all runs, or TAGS="rules apertus")
	$(PY_ROOT) eval/compare.py $(TAGS)

define BENCH_PING
from navigator import llm
try:
    print('Apertus:', llm.ping())
except llm.LLMError as e:
    raise SystemExit(f'{e}\nSet LLM_BASE_URL and LLM_API_KEY in .env first.')
endef
export BENCH_PING

# Apertus vs the no-LLM baseline on the golden set. Explanations are off in all three runs: they don't
# change ranking, and would add ~10 calls per query on the shared endpoint. Leaves the Apertus index in place.
bench:         ## rules | rules + Apertus query terms | Apertus extraction + query terms, then compare
	@$(PY) -c "$$BENCH_PING"
	$(MAKE) pipeline EXTRACTOR=rules
	$(call PY_ENV,USE_LLM_EXPANSION=0 USE_LLM_EXPLAIN=0) eval/run_eval.py --tag rules
	$(call PY_ENV,USE_LLM_EXPANSION=1 USE_LLM_EXPLAIN=0) eval/run_eval.py --tag rules+query
	$(MAKE) pipeline EXTRACTOR=apertus
	$(call PY_ENV,USE_LLM_EXPANSION=1 USE_LLM_EXPLAIN=0) eval/run_eval.py --tag apertus
	$(PY_ROOT) eval/compare.py rules rules+query apertus

test:
	$(PY_ROOT) -m pytest -q tests

logs:
	docker compose logs -f api

deploy:        ## sync src/ to the team server and start it on https://bern-expertise.ch (DEPLOY_HOST=bern)
	./deploy/deploy.sh
