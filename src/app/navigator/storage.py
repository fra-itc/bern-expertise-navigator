"""Storage interface: where the index and the cases live.

Backend choice (one place, no scattered ifs):

    DATABASE_URL empty  -> FileIndexStore  (entities.jsonl + BM25 pickle + NumPy/Qdrant) + SqliteCaseStore
    DATABASE_URL set    -> PgIndexStore    (nav.* tables + pgvector + FTS + AGE graph)  + PgCaseStore

Capability matrix
    capability                     | file                         | postgres
    -------------------------------|------------------------------|----------------------------------------
    entities                       | data/entities.jsonl          | nav.entity + nav.evidence
    vector search (best per entity)| NumPy dot / Qdrant           | pgvector HNSW, hnsw.iterative_scan
    lexical ranking for RRF        | BM25Okapi pickle             | BM25Okapi in memory, same documents (per version)
    graph neighbours               | adjacency from graph.py      | Cypher on expertise_graph (same rules)
    pages / rejected claims stored | no (files written by extract)| nav.page / nav.rejected_claim
    partial (per-source) reindex   | no: always full rebuild      | yes: one transaction per call
    cases                          | SQLite data/cases.db         | nav."case" / case_match / case_event
    papers: `cli papers collect`   | yes: data/papers/*.jsonl,    | yes: + nav.paper / paper_author /
      (OpenAlex, OA PDFs, text)    |   pdf/, text/                |   author_match / paper_chunk
    papers: embed + link (kNN,     | no (StorageError             | nav.paper_chunk / research_profile /
      SIMILAR_TO, ABOUT, CITES)    |   "unsupported")             |   similarity / topic_map + AGE projection
    papers as search evidence,     | no: file search ignores      | yes (supports_papers): paper ranking in
      SIMILAR_TO propagation       |   papers                     |   RRF, paper sources, SIMILAR_TO via
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .config import settings
from .schema import Entity, Page


class StorageError(RuntimeError):
    """Structured storage failure: `code` is stable and machine-readable, `detail` is for humans."""

    def __init__(self, code: str, detail: str, *, backend: str, cause: BaseException | None = None):
        self.code, self.detail, self.backend = code, detail, backend
        super().__init__(f"[{backend}:{code}] {detail}" + (f" ({type(cause).__name__}: {cause})" if cause else ""))


@dataclass
class IndexBundle:
    """Everything `index.build` computed; each store persists what it supports."""
    entities: list[Entity]
    passages: list[dict]          # {"entity_id","source","type","kind","text","snippet"} per vector row
    vectors: np.ndarray           # float32, one row per passage
    embed_model: str
    pages: list[Page] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    scope: list[str] | None = None  # sources being replaced; None = everything


@dataclass(frozen=True)
class PaperHit:
    """Best paper chunk of one entity for a query (search evidence)."""
    entity_id: str
    cos: float
    paper_id: str
    title: str
    year: int | None
    url: str
    kind: str          # abstract / fulltext
    text: str
    relation: str      # author / page_link
    fetched_at: str | None


class IndexStore(Protocol):
    name: str
    persists_corpus: bool  # stores pages / rejected claims (build only loads them if True)
    supports_papers: bool  # paper_hits / paper_best_for / similar_neighbors available

    def write_index(self, bundle: IndexBundle) -> dict: ...
    def load_entities(self) -> dict[str, Entity]: ...
    def version(self) -> str: ...
    def vector_search(self, qvec: np.ndarray, limit: int, sources: list[str] | None = None,
                      types: list[str] | None = None) -> list[tuple[str, float]]: ...
    def lexical_rank(self, tokens: list[str], top: int = 100) -> tuple[list[str], float]: ...
    def neighbors(self, ids: list[str]) -> dict[str, list[str]]: ...


class CaseStore(Protocol):
    """Works on cases.Case objects (imported lazily by the implementations)."""
    name: str

    def save(self, case) -> None: ...
    def get(self, cid: str): ...
    def list(self) -> list: ...
    def delete(self, cid: str) -> None: ...


def backend() -> str:
    return "postgres" if settings.database_url else "file"


def index_store() -> IndexStore:
    if backend() == "postgres":
        from .pgstore import PgIndexStore
        return PgIndexStore.for_url(settings.database_url)
    from .filestore import FileIndexStore
    return FileIndexStore()


def case_store() -> CaseStore:
    if backend() == "postgres":
        from .pgstore import PgCaseStore
        return PgCaseStore.for_url(settings.database_url)
    from .cases import SqliteCaseStore
    return SqliteCaseStore()
