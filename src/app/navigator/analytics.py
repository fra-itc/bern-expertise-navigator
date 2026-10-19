"""Recorded portfolio metrics. Suggestions are never counted as successful outcomes."""
import json
from collections import Counter
from datetime import datetime, timezone

from . import cases, knowledge, discovery


def progress():
    with knowledge.connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS lead_progress (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        return {row[0]: json.loads(row[1]) for row in conn.execute('SELECT id, body FROM lead_progress')}


def set_progress(entry_id, stage, evidence, actor):
    progress()
    body = {'stage': stage, 'evidence': evidence.strip(), 'actor': actor,
            'at': datetime.now(timezone.utc).isoformat()}
    with knowledge.connection() as conn:
        conn.execute('INSERT OR REPLACE INTO lead_progress VALUES (?, ?)', (entry_id, json.dumps(body)))
    return body


def build():
    entries = knowledge.list_entries()
    recorded = progress()
    leads = []
    for case in cases.list_cases():
        if not case.company.strip():
            continue
        update = recorded.get(case.id, {})
        contacted = case.status in ('contacted', 'call_scheduled') or any(e.kind == 'emailed' for e in case.events)
        leads.append({'id': case.id, 'name': case.company, 'summary': case.analysis.summary,
                      'contacted': contacted, 'pitch_ready': bool(case.outreach.get('brief')),
                      'selected_partners': sum(m.selected for m in case.matches),
                      'stage': update.get('stage', 'prospect'), 'evidence': update.get('evidence', ''),
                      'actor': update.get('actor', ''), 'updated_at': update.get('at', case.updated_at)})
    sectors = Counter(e.get('sector') or 'unclassified' for e in entries)
    topics = Counter(topic for e in entries for topic in {v.casefold() for v in e.get('topics', [])})
    suggested_topics = Counter(topic for e in entries for topic in {v.casefold() for v in (e.get('profile') or {}).get('keywords', [])})
    unique = lambda rows: len({row['name'].strip().casefold() for row in rows})
    return {'discovery': discovery.metrics(), 'generated_at': datetime.now(timezone.utc).isoformat(),
            'counts': {'knowledge_companies': len(entries), 'lead_companies': unique(leads),
                       'contacted': unique([row for row in leads if row['contacted']]),
                       'opportunities': unique([row for row in leads if row['stage'] == 'opportunity']),
                       'collaboration': unique([row for row in leads if row['stage'] in ('collaboration', 'established')]),
                       'established': unique([row for row in leads if row['stage'] == 'established'])},
            'sectors': dict(sectors), 'topics': dict(topics.most_common(12)),
            'suggested_topics': dict(suggested_topics.most_common(12)),
            'companies': [{'id': e['id'], 'name': e['name'], 'canton': e.get('canton', ''),
                           'sector': e.get('sector') or 'unclassified', 'topics': e.get('topics', []),
                           'summary': (e.get('profile') or {}).get('summary', ''), 'status': e['status'],
                           'source_count': len(e.get('sources', [])) + len(e.get('documents', [])) + bool(e.get('notes'))}
                          for e in entries], 'leads': leads}
