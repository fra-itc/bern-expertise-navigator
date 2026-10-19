"""Resolve explicit staff approvals before any KB text enters an external pitch."""
from urllib.parse import urlsplit
from . import knowledge, complementarity


def build_approved_context(case, selected_sources):
    """Only current, exact, public web evidence can be approved for publication.

    Caller must protect approval endpoints. Never accepts client-written evidence,
    company names or generated explanations as facts; all are resolved from storage.
    """
    if len(selected_sources) > 20:
        raise ValueError('Select at most 20 evidence passages.')
    approved, seen = [], set()
    allowed = {'Bern'} if not case or getattr(case, 'match_scope', 'bern') == 'bern' else knowledge.NORTH_CANTONS
    for selection in selected_sources:
        record = knowledge.get(selection.get('id', ''))
        if not record or record.get('revision') != selection.get('revision'):
            raise ValueError('Knowledge source changed; review and approve the current version.')
        if record.get('canton') not in allowed:
            raise ValueError('The company is outside the lead search area.')
        source = next((p for p in complementarity.passages(record) if p['source_id'] == selection.get('source_id')), None)
        if not source:
            raise ValueError('Evidence passage no longer exists.')
        parsed = urlsplit(source.get('url') or '')
        if source['kind'] != 'web' or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Private notes and documents cannot be included in external pitches.')
        if source['source_id'] in seen:
            continue
        seen.add(source['source_id'])
        approved.append({'company': record['name'], 'canton': record.get('canton', ''),
                         'candidate_id': record.get('discovery_candidate_id'),
                         'contribution': 'Potential complementarity to explore together.',
                         'source_url': source['url'], 'evidence': source['snippet'],
                         'source_id': source['source_id'], 'revision': source['revision']})
    return approved
