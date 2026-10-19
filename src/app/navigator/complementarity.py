"""Private, passage-grounded complementary capability retrieval.

Embeddings are opt-in, use the existing local model and never send private text to a service.
Concept expansion is a transparent fallback, not a claim that collaboration is confirmed.
"""
from __future__ import annotations
import hashlib
import os
from functools import lru_cache
import numpy as np
from . import index, knowledge


@lru_cache(maxsize=1)
def _model(path):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(path, device='cpu', local_files_only=True)


@lru_cache(maxsize=2)
def _vectors(path, passages_tuple):
    return _model(path).encode(['passage: ' + text for text in passages_tuple], normalize_embeddings=True, show_progress_bar=False)


def semantic_scores(items, query):
    path = os.getenv('PRIVATE_EMBED_MODEL', '')
    if not path:
        raise RuntimeError('Private local model is not configured')
    vectors = _vectors(path, tuple(p['snippet'] for p in items))
    query_vector = _model(path).encode(['query: ' + query], normalize_embeddings=True, show_progress_bar=False)[0]
    return vectors @ query_vector

# Cross-domain capabilities, deliberately not only synonyms for the lead's product.
DOMAINS = [
    ({'diabetes', 'diabete', 'diabète', 'glucose', 'medical', 'medicale', 'medizin', 'sensor', 'sensors'},
     'clinical validation microfabrication materials biocompatibility manufacturing clinical trials validation clinique klinische studien materialien mikrofertigung'),
    ({'mechanical', 'mechanics', 'meccanica', 'manufacturing', 'machinery', 'mechanik', 'mécanique'},
     'materials metrology precision automation robotics additive manufacturing werkstoffe automatisierung robotique fabrication'),
    ({'energy', 'energia', 'énergie', 'energie', 'battery'},
     'materials storage testing power electronics simulation grid werkstoffe prüfung stockage'),
    ({'software', 'digital', 'ai', 'data', 'intelligence'},
     'validation cybersecurity infrastructure computing privacy data engineering sécurité datenschutz'),
]


def expanded_query(query):
    terms = set(index.tokenize(query))
    extra = [capabilities for triggers, capabilities in DOMAINS if terms & triggers]
    return query + ('\nComplementary capabilities: ' + ' '.join(extra) if extra else '')


def passages(record):
    """Stable IDs bind approval to an exact stored passage and record revision."""
    sources = [{'label': s['url'], 'text': s['text'], 'url': s['url'], 'kind': 'web'}
               for s in record.get('sources', [])]
    sources += [{'label': d['name'], 'text': d['text'], 'kind': 'document'} for d in record.get('documents', [])]
    if record.get('notes'):
        sources.append({'label': 'Staff notes', 'text': record['notes'], 'kind': 'notes'})
    for number, source in enumerate(sources):
        for offset in range(0, len(source['text']), 600):
            snippet = source['text'][offset:offset + 600]
            identifier = hashlib.sha256(f"{record['id']}:{record.get('revision', '')}:{number}:{offset}:{snippet}".encode()).hexdigest()
            yield {'id': record['id'], 'revision': record.get('revision'), 'source_id': identifier,
                   'company': record['name'], 'canton': record.get('canton', ''), 'source': source['label'],
                   'url': source.get('url'), 'kind': source['kind'], 'snippet': snippet}


def retrieve(query: str, limit=8, scope='bern'):
    allowed = {'Bern'} if scope == 'bern' else knowledge.NORTH_CANTONS
    items = [p for r in knowledge.list_entries() if r.get('canton') in allowed
             and r.get('status') in ('ready', 'partial') for p in passages(r)]
    if not items:
        return []
    expanded = expanded_query(query)
    direct = set(index.tokenize(query))
    related = set(index.tokenize(expanded)) - direct
    semantic = None
    if os.getenv('PRIVATE_SEMANTIC_EMBEDDINGS', '').lower() in ('1', 'true', 'yes'):
        try:
            semantic = semantic_scores(items, expanded)
        except Exception:
            # Clearly expose fallback; retrieval remains usable without the local model.
            semantic = None
    hits = []
    for number, item in enumerate(items):
        terms = set(index.tokenize(item['snippet']))
        common = direct & terms
        complementary = related & terms
        similarity = float(semantic[number]) if semantic is not None else 0
        if not common and not complementary and similarity < .82:
            continue
        score = len(common) + 1.5 * len(complementary) + max(0, similarity) * 4
        matched = sorted(complementary or common)
        hits.append({**item, 'score': score,
                     'method': 'local_embeddings_and_concepts' if semantic is not None else 'concept_expansion',
                     'explanation': 'Source mentions: ' + ', '.join(matched[:8]) if matched else 'Local semantic similarity; review the quoted evidence.',
                     'contribution': 'Possible complementary capability; operator review required.',
                     'confirmed': False})
    return sorted(hits, key=lambda h: h['score'], reverse=True)[:max(0, min(limit, 50))]
