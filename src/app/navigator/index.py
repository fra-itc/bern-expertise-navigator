"""Stage 4 — indexing: local multilingual embeddings + BM25 (keyword).

Vectors: one point per entity "profile" plus one per evidence snippet, so a short expertise
sentence is matched on its own instead of being diluted in a long profile. Search keeps the
best-scoring point per entity.

Storage is chosen in storage.py: files (Qdrant when QDRANT_URL is set, otherwise an in-process
NumPy matrix in data/) when DATABASE_URL is empty, Postgres (pgvector + FTS + AGE) when it is set.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

import numpy as np

from .config import DATA_DIR, settings
from .schema import Entity

BM25_PATH = DATA_DIR / "bm25.pkl"
ENTITIES_PATH = DATA_DIR / "entities.jsonl"
VEC_PATH = DATA_DIR / "vectors.npy"
VEC_META_PATH = DATA_DIR / "vectors_meta.json"

_STOP = set("""the and for with von und der die das des den dem ein eine einer im in of on to at by
a an or oder zu zur zum mit für fur bei aus le la les de du et en un une des dans au aux pour sur
non""".split())


def tokenize(s: str) -> list[str]:
    return [t for t in re.findall(r"\w{2,}", s.lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def embedder():
    from sentence_transformers import SentenceTransformer  # lazy: heavy import
    return SentenceTransformer(settings.embed_model, device="cpu")


def embed(texts: list[str], query: bool = False) -> np.ndarray:
    # e5 models expect "query: " / "passage: " prefixes
    prefix = ("query: " if query else "passage: ") if "e5" in settings.embed_model else ""
    return embedder().encode([prefix + t for t in texts], normalize_embeddings=True,
                             batch_size=32, show_progress_bar=not query and len(texts) > 64)


def entity_passages(e: Entity) -> list[str]:
    head = f"{e.name}. {e.role or ''} {e.unit or ''} {e.institute or ''}".strip()
    profile = head + ". " + "; ".join(e.expertise + e.projects + e.infrastructure)
    snippets = dict.fromkeys(ev.snippet for ev in e.evidence if ev.field not in ("name", "email"))
    return [profile, *(f"{e.name}: {s}" for s in snippets)]


def _passages(entities: list[Entity]) -> list[dict]:
    out: list[dict] = []
    for e in entities:
        snippets = list(dict.fromkeys(ev.snippet for ev in e.evidence if ev.field not in ("name", "email")))
        for j, t in enumerate(entity_passages(e)):
            out.append({"entity_id": e.id, "source": e.source, "type": e.entity_type,
                        "kind": "profile" if j == 0 else "evidence", "snippet": None if j == 0 else snippets[j - 1],
                        "text": t})
    return out


def _rejected(sources: list[str] | None) -> list[dict]:
    p = DATA_DIR / "rejected.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    return [r for r in rows if not sources or r.get("source") in sources]


def build(entities: list[Entity], sources: list[str] | None = None) -> dict:
    """Embed and hand everything to the configured store (storage.index_store()).

    `sources`: only these sources are replaced (Postgres backend); None = full rebuild.
    The file backend always rebuilds everything from `entities`, as before.
    """
    from . import crawl
    from .storage import IndexBundle, index_store

    st = index_store()
    if sources and st.persists_corpus:
        entities = [e for e in entities if e.source in sources]
    passages = _passages(entities)
    vecs = embed([p["text"] for p in passages]).astype(np.float32) if passages         else np.zeros((0, 0), dtype=np.float32)
    bundle = IndexBundle(entities=entities, passages=passages, vectors=vecs, embed_model=settings.embed_model,
                         scope=sources if st.persists_corpus else None)
    if st.persists_corpus:
        bundle.pages = [p for p in crawl.load_pages() if not sources or p.source in sources]
        bundle.rejected = _rejected(sources)
    stats = st.write_index(bundle)
    print(f"[index] {stats.get('entities', len(entities))} entities, {stats.get('vectors', len(passages))} vectors "
          f"({stats.get('store', st.name)}, {settings.embed_model})"
          + "".join(f", {k}={v}" for k, v in stats.items() if k not in ("entities", "vectors", "store")))
    return stats


# ---- read side: delegated to the configured store (kept for callers) ----
def load_entities() -> dict[str, Entity]:
    from .storage import index_store
    return index_store().load_entities()
