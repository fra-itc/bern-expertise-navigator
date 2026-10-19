"""Settings (env vars) and source configuration (config/sources.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(os.getenv("NAV_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = Path(os.getenv("NAV_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.getenv("NAV_DATA_DIR", ROOT / "data"))


def _load_dotenv(path: Path) -> None:
    """Local runs (no Docker): read .env without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)


_load_dotenv(ROOT / ".env")


def _env(*names: str, default: str = "") -> str:
    for n in names:
        if os.getenv(n):
            return os.environ[n]
    return default


@dataclass
class Settings:
    # Hack Apertus convention: LLM_NAME / LLM_BASE_URL / LLM_API_KEY (LLM_MODEL kept as an alias)
    llm_base_url: str = _env("LLM_BASE_URL", default="http://vllm:8000/v1").rstrip("/")
    llm_model: str = _env("LLM_NAME", "LLM_MODEL", default="swiss-ai/Apertus-v1.5-8B")
    # the manager dashboard's written analysis: a small, fast model on the same gateway
    insight_model: str = os.getenv("INSIGHT_LLM_MODEL", "apertus-v1-5-8b")
    llm_api_key: str = _env("LLM_API_KEY", default="not-needed")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "120"))
    llm_concurrency: int = int(os.getenv("LLM_CONCURRENCY", "8"))
    llm_stream: bool = os.getenv("LLM_STREAM", "1") == "1"   # stream completions (gateways time out silent requests)
    embed_model: str = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")
    # Empty -> in-process NumPy store (data/vectors.npy, see filestore.py); set -> Qdrant server at this URL
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    collection: str = os.getenv("QDRANT_COLLECTION", "expertise")
    # Set -> Postgres backend (nav schema + pgvector + AGE graph), see storage.py. Empty -> files.
    database_url: str = os.getenv("DATABASE_URL", "")
    pg_pool_max: int = int(os.getenv("PG_POOL_MAX", "8"))
    pg_ef_search: int = int(os.getenv("PG_HNSW_EF_SEARCH", "100"))
    # Abstention: below these scores we say "no verifiable source"
    # Abstain when BOTH the best semantic match is weak AND few query words occur in the best matches
    min_vector_score: float = float(os.getenv("MIN_VECTOR_SCORE", "0.825"))
    min_coverage: float = float(os.getenv("MIN_COVERAGE", "0.5"))
    # Fairness: max results from the same unit in the top-k
    max_per_unit: int = int(os.getenv("MAX_PER_UNIT", "3"))
    # a researcher known only from publication records (OpenAlex: no role, no lab page) ranks slightly below
    # the institutes' own profiles at equal relevance
    # (0.8: best recall on the 46-query golden set with the UniBE websites indexed; 0.7 starts losing UniBE experts)
    record_only_weight: float = float(os.getenv("RECORD_ONLY_WEIGHT", "0.8"))
    use_llm_expansion: bool = os.getenv("USE_LLM_EXPANSION", "1") == "1"
    use_llm_explain: bool = os.getenv("USE_LLM_EXPLAIN", "1") == "1"
    # Ground the expansion in the index vocabulary (the model picks from the labels the query already reaches).
    # Off by default: on the golden set it lowered recall@10 (81-90% vs 93%) though it raised held-out twin overlap.
    ground_expansion: bool = os.getenv("GROUND_EXPANSION", "0") == "1"
    # Cost on the dashboard: CHF per million tokens. Unset -> a placeholder, shown as such until the real price is known
    llm_price_in: float = float(os.getenv("LLM_PRICE_IN_CHF_PER_M", "0.50"))
    llm_price_out: float = float(os.getenv("LLM_PRICE_OUT_CHF_PER_M", "1.50"))
    llm_price_set: bool = bool(os.getenv("LLM_PRICE_IN_CHF_PER_M") or os.getenv("LLM_PRICE_OUT_CHF_PER_M"))

    # ---- papers (navigator.papers, `cli papers`) -------------------------------------
    openalex_base_url: str = os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/")
    openalex_mailto: str = os.getenv("OPENALEX_MAILTO", "")
    # free key = $1/day budget and 30 req/s; without it OpenAlex shares $0.10/day per IP (see README)
    openalex_api_key: str = os.getenv("OPENALEX_API_KEY", "")
    openalex_rps: float = float(os.getenv("OPENALEX_RPS", "5"))
    openalex_cache_days: float = float(os.getenv("OPENALEX_CACHE_DAYS", "30"))
    # Bern institutions as ROR ids, resolved to OpenAlex ids at run time (University of Bern, Inselspital).
    papers_rors: tuple[str, ...] = tuple(x.strip() for x in os.getenv(
        "PAPERS_RORS", "https://ror.org/02k7v4d05,https://ror.org/01q9sj412").split(",") if x.strip())
    papers_max_works: int = int(os.getenv("PAPERS_MAX_WORKS", "30"))       # per author, newest first
    papers_years: int = int(os.getenv("PAPERS_YEARS", "10"))               # ... and not older than this
    papers_max_candidates: int = int(os.getenv("PAPERS_MAX_CANDIDATES", "8"))
    papers_pdf: bool = os.getenv("PAPERS_PDF", "1") == "1"
    papers_pdf_max_mb: float = float(os.getenv("PAPERS_PDF_MAX_MB", "20"))
    papers_pdf_timeout: float = float(os.getenv("PAPERS_PDF_TIMEOUT", "30"))
    papers_pdf_max_pages: int = int(os.getenv("PAPERS_PDF_MAX_PAGES", "40"))
    papers_pdf_delay: float = float(os.getenv("PAPERS_PDF_DELAY", "1.0"))  # per host
    papers_chunk_words: int = int(os.getenv("PAPERS_CHUNK_WORDS", "200"))  # median ~360 e5 tokens on a real paper
    papers_chunk_overlap: int = int(os.getenv("PAPERS_CHUNK_OVERLAP", "30"))
    papers_max_chunks: int = int(os.getenv("PAPERS_MAX_CHUNKS", "8"))      # full-text chunks per paper
    # embedding-derived graph edges (cli papers link)
    similar_k: int = int(os.getenv("SIMILAR_K", "5"))
    similar_quantile: float = float(os.getenv("SIMILAR_QUANTILE", "0.9"))  # threshold = this quantile of kNN cosines
    similar_min: float = float(os.getenv("SIMILAR_MIN", "0.80"))          # ... but never below this
    similar_person_threshold: str = os.getenv("SIMILAR_PERSON_THRESHOLD", "auto")  # 'auto' or a cosine
    similar_paper_threshold: str = os.getenv("SIMILAR_PAPER_THRESHOLD", "auto")
    topic_shortlist: int = int(os.getenv("TOPIC_SHORTLIST", "8"))         # topic candidates shown to the LLM
    # search: papers as evidence (Postgres backend only)
    use_papers: bool = os.getenv("USE_PAPERS", "1") == "1"
    paper_weight: float = float(os.getenv("PAPER_WEIGHT", "0.8"))         # RRF weight of the paper ranking
    similar_damping: float = float(os.getenv("SIMILAR_DAMPING", "0.6"))   # score passed along SIMILAR_TO


settings = Settings()


@dataclass
class Source:
    name: str
    label: str
    domains: list[str]
    seeds: list[str]
    max_pages: int
    max_depth: int
    delay_seconds: float
    user_agent: str
    priority_keywords: list[str]
    skip_keywords: list[str]
    page_types: dict[str, list[str]] = field(default_factory=dict)
    type: str = "web"                                   # "web" (crawl a website) or "openalex" (scholarly API)
    options: dict = field(default_factory=dict)         # type-specific settings (e.g. institution, subfields)

    def allows(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)


def _resolve(rel: str) -> Path:
    """Paths in sources.yaml are relative to ROOT ("config/x.txt"); with NAV_CONFIG_DIR pointing
    elsewhere, fall back to the same file name inside that config dir."""
    p = Path(rel)
    if p.is_absolute() or (ROOT / p).exists():
        return p if p.is_absolute() else ROOT / p
    return CONFIG_DIR / p.name


def _read_seeds_file(path: Path) -> list[str]:
    hosts = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [h if h.startswith("http") else f"https://{h}/" for h in hosts]


def load_sources(only: str | None = None) -> list[Source]:
    cfg = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    d = cfg.get("defaults", {})
    out: list[Source] = []
    for s in cfg["sources"]:
        if only and s["name"] != only:
            continue
        seeds = list(s.get("seeds", []))
        if s.get("seeds_file"):
            seeds += _read_seeds_file(_resolve(s["seeds_file"]))
        domains = list(s.get("domains", []))
        if s.get("domains_from_seeds"):
            domains += [urlparse(u).hostname for u in seeds if urlparse(u).hostname]
        out.append(Source(
            name=s["name"], label=s.get("label", s["name"]),
            domains=sorted({x.lower().removeprefix("www.") for x in domains} | {x.lower() for x in domains}),
            seeds=seeds,
            max_pages=s.get("max_pages", d.get("max_pages", 400)),
            max_depth=s.get("max_depth", d.get("max_depth", 3)),
            delay_seconds=s.get("delay_seconds", d.get("delay_seconds", 0.5)),
            user_agent=s.get("user_agent", d.get("user_agent", "ExpertiseNavigator")),
            priority_keywords=s.get("priority_keywords", d.get("priority_keywords", [])),
            # extra_skip_keywords adds to the defaults instead of replacing them
            skip_keywords=s.get("skip_keywords", d.get("skip_keywords", [])) + s.get("extra_skip_keywords", []),
            page_types=s.get("page_types", {}),
            type=s.get("type", "web"),
            options=s.get("openalex", {}),
        ))
    if only and not out:
        raise SystemExit(f"Unknown source '{only}' in sources.yaml")
    return out


def load_glossary() -> dict[str, list[str]]:
    p = CONFIG_DIR / "glossary.yaml"
    if not p.exists():
        return {}
    return {k.lower(): [v.lower() for v in vs] for k, vs in (yaml.safe_load(p.read_text()) or {}).items()}
