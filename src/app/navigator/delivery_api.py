from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from . import cases, delivery, knowledge_access, pitch_pdf
import os

router = APIRouter()

class Send(BaseModel):
    subject: str = Field(min_length=1,max_length=300)
    body: str = Field(min_length=1,max_length=20000)
    idempotency_key: str = Field(min_length=16,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')

@router.get('/cases/{cid}/delivery')
def status(cid: str, response: Response, user=Depends(knowledge_access.require_member)):
    response.headers['Cache-Control'] = 'no-store'
    case = cases.get(cid)
    if not case:
        raise HTTPException(404,'Unknown lead')
    b = (case.outreach or {}).get('brief')
    base = os.getenv('PITCH_PUBLIC_BASE_URL', '').rstrip('/')
    ready = delivery.configured() and base.startswith('https://')
    return {'configured': ready, 'public_link': base + '/#/b/' + b['token'] if ready and b else None, 'history': delivery.history(cid)}

@router.get('/briefs/{token}/pdf')
def pdf(token: str):
    from . import published_pitch
    from .api import _brief_case
    case = _brief_case(token)   # same rules as the page: 404 unknown, 410 disabled or expired
    data = published_pitch.get(token) or case.outreach['brief']['data']
    return Response(pitch_pdf.render(data), media_type='application/pdf', headers={'Content-Disposition':'attachment; filename="Bern-pitch.pdf"','Cache-Control':'no-store'})

@router.post('/cases/{cid}/delivery')
def send(cid: str, body: Send, user=Depends(knowledge_access.require_representative)):
    case = cases.get(cid)
    if not case:
        raise HTTPException(404,'Unknown lead')
    b = (case.outreach or {}).get('brief')
    if not b:
        raise HTTPException(400,'Prepare the pitch first')
    if not delivery.configured():
        raise HTTPException(503,'SMTP delivery is not configured.')
    base = os.environ['PITCH_PUBLIC_BASE_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise HTTPException(503,'Configure an HTTPS public pitch URL before sending.')
    link = base + '/#/b/' + b['token']
    if link not in body.body:
        raise HTTPException(422,'Include the published pitch link in the message.')
    try:
        result = delivery.send(case,body.subject,body.body,body.idempotency_key,pitch_pdf.render(b['data']))
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if not result['duplicate']:
        cases.log(case,user['email'],'email_delivery',result['status'])
        if result['status'] == 'sent':
            case.status = 'contacted'
        cases.save(case)
    return result
