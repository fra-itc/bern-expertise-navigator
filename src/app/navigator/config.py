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
    record_only_weight: float = float(os.getenv("RECORD_ONLY_WEIGHT", "0.9"))
    use_llm_expansion: bool = os.getenv("USE_LLM_EXPANSION", "1") == "1"
    use_llm_explain: bool = os.getenv("USE_LLM_EXPLAIN", "1") == "1"
    # Cost on the dashboard: CHF per million tokens. Unset -> a placeholder, shown as such until the real price is known
    llm_price_in: float = float(os.getenv("LLM_PRICE_IN_CHF_PER_M", "0.50"))
    llm_price_out: float = float(os.getenv("LLM_PRICE_OUT_CHF_PER_M", "1.50"))
    llm_price_set: bool = bool(os.getenv("LLM_PRICE_IN_CHF_PER_M") or os.getenv("LLM_PRICE_OUT_CHF_PER_M"))


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
            seeds += _read_seeds_file(ROOT / s["seeds_file"])
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
