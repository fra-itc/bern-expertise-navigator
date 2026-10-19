"""Isolated demo chain: real application stages, controlled source and SMTP boundaries."""
from fastapi.testclient import TestClient
from navigator import api, cases, knowledge, knowledge_access, company, llm, vault, discovery, published_pitch, delivery, analytics


def test_demo_company_sources_lead_match_pitch_pdf_email(tmp_path, monkeypatch):
    for module in (cases, knowledge, discovery, published_pitch, delivery):
        monkeypatch.setattr(module, 'DB', tmp_path / (module.__name__.split('.')[-1] + '.db'))
    monkeypatch.setattr(vault, 'ROOT', tmp_path / 'originals')
    monkeypatch.setattr(knowledge_access, 'member', lambda request: {'email':'demo@example.test','role':'representative'})
    monkeypatch.setattr(llm, 'available', lambda *a, **kw:False)
    monkeypatch.setattr(cases, 'find_matches', lambda *a, **kw:([],None))
    monkeypatch.setattr(cases.showcase, 'build', lambda:{})
    monkeypatch.delenv('DISCOVERY_SEARXNG_URL', raising=False)
    page=company.CompanyWebsite(url='https://example.org/lab', name='Fictional Materials Lab', text='This fictional Bern laboratory offers microfabrication and biocompatibility testing for medical devices.')
    monkeypatch.setattr(company, 'read', lambda url:page)
    client=TestClient(api.app)
    original=b'Fictional private client document about glucose sensors and plans for clinical validation. Not for publication.'
    upload=client.post('/kb/documents?name=client.txt',content=original)
    assert upload.status_code==200
    doc=upload.json()
    lead=client.post('/cases',json={'company':'Fictional Sensor Company','need':'Clinical validation of glucose sensors','request_text':'Develop medical sensors','documents':[doc],'contact_email':'ceo@example.test','actor':'Demo'})
    assert lead.status_code==200
    cid=lead.json()['id']
    run=client.post('/discovery/runs',json={'lead_id':cid,'seed_urls':['https://example.org/lab']}).json()
    candidate=client.get('/discovery/runs/'+run['id']).json()['candidates'][0]
    assert candidate['fields']['canton']['status']=='review_required'
    assert client.get('/kb/companies').json()==[]
    approval=client.patch('/discovery/candidates/'+candidate['id'],json={'decision':'approved','fields':{'name':'Fictional Materials Lab','canton':'Bern','contribution':'Explore medical device materials testing'}})
    assert approval.status_code==200
    draft=client.get('/discovery/candidates/'+candidate['id']+'/export').json()
    assert client.get('/kb/companies').json()==[]
    saved=client.post('/kb/companies',json=draft)
    assert saved.status_code==202
    results=client.get('/kb/leads/'+cid+'/sources').json()
    source=next(x for x in results if x['kind']=='web')
    selection={key:source[key] for key in ('id','revision','source_id')}
    pitch=client.post('/cases/'+cid+'/brief',json={'actor':'Demo','knowledge_sources':[selection]} )
    assert pitch.status_code==200
    token=pitch.json()['token']
    shared=client.get('/briefs/'+token).json()
    assert shared['items'][0]['quote']['text']==page.text
    assert 'Fictional private client document' not in str(shared)
    pdf=client.get('/briefs/'+token+'/pdf')
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert client.get('/kb/originals/'+doc['original_id']).content==original
    assert client.delete('/kb/originals/'+doc['original_id']).status_code==409
    assert client.get('/discovery/metrics').json()['used_in_pitch']==1
    for key,val in {'SMTP_HOST':'smtp.example.test','SMTP_FROM':'bern@example.test','PITCH_PUBLIC_BASE_URL':'https://pitch.example.test'}.items():
        monkeypatch.setenv(key,val)
    messages=[]
    class MailSink:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def starttls(self,**kw):pass
        def send_message(self,message):messages.append(message)
    monkeypatch.setattr(delivery.smtplib,'SMTP',MailSink)
    link='https://pitch.example.test/#/b/'+token
    email=client.post('/cases/'+cid+'/draft',json={'actor':'Demo','link':link}).json()
    assert 'Fictional Materials Lab' in email['body'] and link in email['body']
    payload={**email,'idempotency_key':'demo-pipeline-12345678'}
    sent=client.post('/cases/'+cid+'/delivery',json=payload)
    assert sent.status_code==200 and sent.json()['status']=='sent'
    assert client.post('/cases/'+cid+'/delivery',json=payload).json()['duplicate']
    assert len(messages)==1
    attachment=next(messages[0].iter_attachments())
    assert attachment.get_content_type()=='application/pdf' and attachment.get_payload(decode=True)==pdf.content
    assert client.get('/cases/'+cid).json()['status']=='contacted'
