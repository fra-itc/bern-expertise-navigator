"""File backend (default, DATABASE_URL empty): entities.jsonl + BM25 pickle + NumPy matrix / Qdrant.

Behaviour is the historical index.py one. Paths are read from `index` at call time so that
`index.ENTITIES_PATH` & co. stay the single place to point the files elsewhere (tests do).
"""
from __future__ import annotations

import json
import pickle
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from . import graph, index
from .config import settings
from .schema import Entity
from .storage import IndexBundle


def _mtime(p) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@lru_cache(maxsize=1)
def qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.qdrant_url)


# The API process picks up a re-index done by the CLI without restarting (cache keyed on mtime)
@lru_cache(maxsize=1)
def _vectors_at(path: str, meta_path: str, _mt: float):
    from pathlib import Path
    if not Path(path).exists():
        return None, []
    return np.load(path), json.loads(Path(meta_path).read_text())


@lru_cache(maxsize=1)
def _entities_at(path: str, _mt: float) -> dict[str, Entity]:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return {}
    return {e.id: e for e in (Entity.model_validate_json(l) for l in p.open() if l.strip())}


@lru_cache(maxsize=1)
def _bm25_at(path: str, _mt: float):
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    with p.open("rb") as fh:
        return pickle.load(fh)


@lru_cache(maxsize=2)
def _graph_at(path: str, _mt: float) -> dict[str, list[str]]:
    return graph.adjacency(_entities_at(path, _mt).values())


class FileIndexStore:
    name = "file"
    persists_corpus = False

    def write_index(self, bundle: IndexBundle) -> dict:
        entities = bundle.entities
        index.ENTITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with index.ENTITIES_PATH.open("w") as fh:
            for e in entities:
                fh.write(e.model_dump_json() + "\n")

        docs = [e.search_text() for e in entities]
        with index.BM25_PATH.open("wb") as fh:
            pickle.dump({"ids": [e.id for e in entities],
                         "bm25": BM25Okapi([index.tokenize(d) for d in docs])}, fh)

        meta = [{"entity_id": p["entity_id"], "source": p["source"], "type": p["type"]} for p in bundle.passages]
        vecs = bundle.vectors
        if settings.qdrant_url:
            from qdrant_client.models import Distance, PointStruct, VectorParams
            q = qdrant()
            if q.collection_exists(settings.collection):
                q.delete_collection(settings.collection)
            q.create_collection(settings.collection,
                                vectors_config=VectorParams(size=vecs.shape[1], distance=Distance.COSINE))
            for i in range(0, len(meta), 512):
                q.upsert(settings.collection, points=[
                    PointStruct(id=j, vector=vecs[j].tolist(), payload=meta[j]) for j in range(i, min(i + 512, len(meta)))])
        np.save(index.VEC_PATH, vecs)
        index.VEC_META_PATH.write_text(json.dumps(meta))
        store = "Qdrant" if settings.qdrant_url else "local NumPy store"
        return {"entities": len(entities), "vectors": len(meta), "store": f"{store} + BM25"}

    def load_entities(self) -> dict[str, Entity]:
        return _entities_at(str(index.ENTITIES_PATH), _mtime(index.ENTITIES_PATH))

    def version(self) -> str:
        return str(_mtime(index.ENTITIES_PATH))

    def vector_search(self, qvec, limit, sources=None, types=None):
        """(entity_id, cosine) for the best `limit` points (several points may share an entity)."""
        if settings.qdrant_url:
            from qdrant_client.models import FieldCondition, Filter, MatchAny
            must = []
            if sources:
                must.append(FieldCondition(key="source", match=MatchAny(any=sources)))
            if types:
                must.append(FieldCondition(key="type", match=MatchAny(any=types)))
            flt = Filter(must=must) if must else None
            hits = qdrant().query_points(settings.collection, query=qvec.tolist(), limit=limit, query_filter=flt).points
            return [(h.payload["entity_id"], float(h.score)) for h in hits]
        vecs, meta = _vectors_at(str(index.VEC_PATH), str(index.VEC_META_PATH), _mtime(index.VEC_META_PATH))
        if vecs is None or not len(meta):
            return []
        scores = vecs @ qvec.astype(np.float32)
        if sources or types:
            mask = np.array([(not sources or m["source"] in sources) and (not types or m["type"] in types)
                             for m in meta])
            scores = np.where(mask, scores, -1.0)
        top = np.argsort(-scores)[:limit]
        return [(meta[i]["entity_id"], float(scores[i])) for i in top if scores[i] > -1]

    def lexical_rank(self, tokens, top=100):
        b = _bm25_at(str(index.BM25_PATH), _mtime(index.BM25_PATH))
        if not b or not tokens:
            return [], 0.0
        scores = b["bm25"].get_scores(tokens)
        order = np.argsort(-scores)[:top]
        return [b["ids"][i] for i in order if scores[i] > 0], float(scores[order[0]]) if len(order) else 0.0

    def neighbors(self, ids):
        g = _graph_at(str(index.ENTITIES_PATH), _mtime(index.ENTITIES_PATH))
        return {i: g.get(i, []) for i in ids}
