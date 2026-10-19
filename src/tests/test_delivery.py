import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from navigator import delivery, pitch_branding
from types import SimpleNamespace
import pytest

class SMTP:
    count=0
    def __init__(self,*a,**k): pass
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def starttls(self,**k): pass
    def send_message(self,m):
        SMTP.count += 1
        assert next(m.iter_attachments()).get_content_type() == 'application/pdf'

def test_delivery_idempotency_and_uncertain(tmp_path,monkeypatch):
    monkeypatch.setattr(delivery,'DB',tmp_path/'mail.db')
    for key,val in {'SMTP_HOST':'smtp.test','SMTP_FROM':'bern@example.com','PITCH_PUBLIC_BASE_URL':'https://pitch.test'}.items():
        monkeypatch.setenv(key,val)
    monkeypatch.setattr(delivery.smtplib,'SMTP',SMTP)
    case=SimpleNamespace(id='c',contact_email='ceo@example.com')
    SMTP.count=0
    assert delivery.send(case,'Pitch','Body','unique-key',b'pdf')['status']=='sent'
    assert delivery.send(case,'Pitch','Body','unique-key',b'pdf')['duplicate']
    assert SMTP.count==1
    with pytest.raises(ValueError): delivery.send(case,'Changed','Body','unique-key',b'pdf')
    def fail(self,m): raise OSError('Connection lost')
    monkeypatch.setattr(SMTP,'send_message',fail)
    assert delivery.send(case,'Pitch','Body','second-key',b'pdf')['status']=='uncertain'
    assert delivery.send(case,'Pitch','Body','second-key',b'pdf')['duplicate']

def test_branding_rejects_active_content():
    with pytest.raises(ValueError): pitch_branding.validate_logo('data:image/svg+xml;base64,PHN2Zz4=')

def test_apertus_curation_only_accepts_selected_ids(monkeypatch):
    from navigator import brief, llm
    case=SimpleNamespace(company='Sensors',need='Clinical validation',request_text='Wearable sensors')
    items=[{'id':i,'name':i,'topics':[], 'quote':{'text':'Verified expertise'}} for i in ('one','two')]
    monkeypatch.setattr(llm,'available',lambda: True)
    monkeypatch.setattr(llm,'chat_json',lambda *a,**k: brief._Curation(partner_ids=['two']))
    chosen,by=brief.curate(case,items)
    assert chosen[0]['id']=='two' and by=='apertus'
    monkeypatch.setattr(llm,'chat_json',lambda *a,**k: brief._Curation(partner_ids=['invented']))
    assert brief.curate(case,items)==(items,'rules')

def test_build_commercial_pitch_in_three_languages(monkeypatch):
    from navigator import brief, cases, plain
    from navigator.schema import Entity, Evidence
    partner=Entity(id='p',name='Clinical Lab',entity_type='unit',source='test',source_label='Bern',source_urls=['https://example.org/lab'],retrieved_at='2026',evidence=[Evidence(field='expertise',value='sensors',snippet='This laboratory develops advanced wearable sensors for clinical research.',url='https://example.org/lab')])
    monkeypatch.setattr(brief.index,'load_entities',lambda: {'p':partner})
    monkeypatch.setattr(brief.search,'neighbors',lambda *a: {})
    monkeypatch.setattr(brief.showcase,'build',lambda: {})
    monkeypatch.setattr(brief,'pubs_for',lambda *a: [])
    monkeypatch.setattr(brief.llm,'available',lambda: False)
    case=cases.Case(id='case',created_at='2026',updated_at='2026',company='Example',need='Advance sensors',analysis=plain.RequestAnalysis(original='sensors',summary='sensors',search_query='sensors'),matches=[cases.Match(id='p',name='Clinical Lab',entity_type='unit',selected=True)])
    for lang in ('en','de','fr'):
        output=brief.build(case,lang,{'name':'Officer'})
        assert output['brief']['curation_by']=='rules'
        assert output['brief']['featured'][0]['name']=='Clinical Lab'
        assert output['summary']['connections'][0]['source']=='https://example.org/lab'
        assert len(output['explainer'])==5
