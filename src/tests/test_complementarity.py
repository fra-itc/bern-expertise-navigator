"""Grounding, complementary retrieval and private/public sharing boundaries."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from navigator import knowledge, complementarity, private_pitch

@pytest.fixture
def record(monkeypatch):
    r = {'id': 'a', 'revision': 'r1', 'name': 'Materials Lab', 'canton': 'Bern', 'status': 'ready',
         'sources': [{'url': 'https://example.org/materials', 'text': 'Microfabrication and biocompatibility materials testing.'}],
         'documents': [{'name': 'private.txt', 'text': 'Private glucose product roadmap'}], 'notes': 'Confidential diabetes funding discussions.'}
    monkeypatch.setattr(knowledge, 'list_entries', lambda: [r])
    monkeypatch.setattr(knowledge, 'get', lambda key: r if key == 'a' else None)
    monkeypatch.delenv('PRIVATE_SEMANTIC_EMBEDDINGS', raising=False)
    return r


def test_complementary_capability_without_product_keyword(record):
    hits = complementarity.retrieve('glucose diabetes')
    web = next(h for h in hits if h['kind'] == 'web')
    assert web['method'] == 'concept_expansion'
    assert web['confirmed'] is False
    assert web['snippet'] == record['sources'][0]['text']
    assert 'biocompatibility' in web['explanation']
    assert complementarity.retrieve('glucose', scope='bern')
    record['canton'] = 'Zurich'
    assert not complementarity.retrieve('glucose', scope='bern')
    assert complementarity.retrieve('glucose', scope='north')


def test_public_approval_resolves_stored_evidence_and_rejects_private(record):
    hits = list(complementarity.passages(record))
    approved = private_pitch.build_approved_context(None, [hits[0]])
    assert approved[0]['evidence'] == record['sources'][0]['text']
    assert not private_pitch.build_approved_context(None, [])
    for hit in hits[1:]:
        with pytest.raises(ValueError, match='Private'):
            private_pitch.build_approved_context(None, [hit])
    with pytest.raises(ValueError, match='changed'):
        private_pitch.build_approved_context(None, [{**hits[0], 'revision': 'stale'}])
    with pytest.raises(ValueError, match='no longer'):
        private_pitch.build_approved_context(None, [{**hits[0], 'source_id': 'invented'}])


def test_semantic_failure_is_explicit_fallback(record, monkeypatch):
    monkeypatch.setenv('PRIVATE_SEMANTIC_EMBEDDINGS', '1')
    monkeypatch.setattr(complementarity, 'semantic_scores', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    assert all(h['method'] == 'concept_expansion' for h in complementarity.retrieve('glucose'))
