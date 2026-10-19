"""Private approvals, resolved afresh before generating public pitch content."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from . import cases, knowledge, complementarity, private_pitch, knowledge_access, brief as pitch_builder

router = APIRouter()


class SourceSelection(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    source_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: str = Field(min_length=1, max_length=100)


def resolve(case, selections):
    return private_pitch.build_approved_context(case, selections)


def enrich(output, case, sources):
    if not sources:
        return
    brief = output['brief']
    added = []
    for entry in sources:
        reference = next((n for n, source in enumerate(brief['sources'], 1) if source['url'] == entry['source_url']), None)
        if reference is None:
            brief['sources'].append({'url': entry['source_url'], 'label': entry['company'], 'kind': 'page'})
            reference = len(brief['sources'])
        benefit = {'en': 'Explore the documented capabilities below as a possible complement to your development objectives.',
                   'de': 'Die unten belegten Kompetenzen als mögliche Ergänzung zu Ihren Entwicklungszielen erkunden.',
                   'fr': 'Explorer les compétences documentées ci-dessous comme complément possible à vos objectifs.'}[brief['lang']]
        identifier = 'kb-' + entry['source_id']
        item = {'id': identifier, 'name': entry['company'], 'type': 'company', 'role': None, 'unit': None,
                'institution': entry['canton'], 'page': entry['source_url'], 'page_ref': reference, 'group': 'company',
                'benefit': benefit, 'basis': 'knowledge_base', 'topics': [],
                'quote': {'text': entry['evidence'], 'ref': reference, 'url': entry['source_url'], 'via': None},
                'technical': [], 'publications': []}
        brief['items'].append(item)
        added.append({'name': item['name'], 'benefit': benefit, 'url': item['page'], 'evidence': item['quote'], 'topics': []})
        brief['ecosystem']['nodes'].append({'id': identifier, 'name': item['name'], 'topics': [], 'url': item['page']})
    lang = brief['lang']
    t = pitch_builder.T.get(lang, pitch_builder.T['en'])
    # the companies join the pitch's "company" group of strategic opportunities, and lead the featured partners
    kb = [{'name': i['name'], 'ref': i['page_ref']} for i in brief['items'] if i.get('basis') == 'knowledge_base']
    group = next((o for o in brief['opportunities'] if o['title'] == t['o.company']), None)
    if group:
        group['items'] += [x for x in kb if x not in group['items']]
    else:
        brief['opportunities'].append({'title': t['o.company'], 'items': kb})
    brief['featured'] = (added + brief.get('featured', []))[:3]
    output['stats']['claims'] += len(sources)
    output['stats']['sources'] = len(brief['sources'])
    connections = [{'name': i['name'], 'reason': i['quote']['text'][:150], 'source': i['page']} for i in brief['items'] if i.get('basis') == 'knowledge_base']
    output['summary']['connections'] += connections
    text = pitch_builder.COMMERCIAL[lang]['summary'].format(company=case.company, n=len(brief['items']))
    output['summary']['text'] = text
    # the officer's preface (in the officer's language): its second part, what was found, names the companies too
    output['explainer'][1]['lines'] += [{'text': c['name'] + ': ' + c['reason']} for c in connections]


@router.get('/kb/leads/{lead_id}/sources')
def sources(lead_id: str, response: Response, user=Depends(knowledge_access.require_member)):
    case = cases.get(lead_id)
    if not case:
        raise HTTPException(404, 'Lead not found')
    response.headers['Cache-Control'] = 'no-store'
    return complementarity.retrieve(case.analysis.search_query or case.analysis.summary, scope=case.match_scope)
