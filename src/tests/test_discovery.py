from navigator import discovery as d, company, llm
import pytest

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'DB',tmp_path/'discovery.db')
    monkeypatch.setattr(d.knowledge,'list_entries',lambda:[])
    return monkeypatch

def test_unconfigured_reports_no_fake_results(isolated):
    isolated.delenv('DISCOVERY_SEARXNG_URL',raising=False)
    r=d.create('lead','bern','operator')
    d.execute(r['id'],'confidential lead')
    out=d.detail(r['id'])
    assert out['status']=='unavailable' and out['candidates']==[]
    assert 'DISCOVERY_SEARXNG_URL' in out['message']

def test_evidence_and_operator_approval(isolated):
    isolated.setenv('DISCOVERY_SEARXNG_URL','https://search.example/search')
    isolated.setattr(d,'plan',lambda ctx:(['clinical validation'],'apertus'))
    isolated.setattr(d,'search_public',lambda query:[{'url':'https://partner.example'}])
    isolated.setattr(company,'read',lambda url:company.CompanyWebsite(url=url,text='Acme is based in Bern and develops sensors.'))
    profile=d.Profile(name=d.Fact(value='Acme',quote='Acme'),canton=d.Fact(value='Bern',quote='Bern'),sector=d.Fact(value='medical',quote='NOT IN SOURCE'),contribution='Explore sensor validation')
    isolated.setattr(llm,'available',lambda:True)
    isolated.setattr(llm,'chat_json',lambda *a,**kw:profile)
    r=d.create('lead','bern','operator'); d.execute(r['id'],'sensor goals')
    c=d.detail(r['id'])['candidates'][0]
    assert c['fields']['name']['status']=='source_supported'
    assert c['fields']['sector']['status']=='review_required'
    with pytest.raises(ValueError): d.review(c['id'],{},'approved','op')
    out=d.review(c['id'],{'contribution':'Explore validation'},'approved','op')
    assert out['decision']=='approved'
    assert d.export(c['id'])['sector']==''
    assert d.metrics()['approved']==1
    assert d.metrics()['used_in_pitch']==0
    d.mark_used(c['id']); assert d.metrics()['used_in_pitch']==1

def test_outside_region_not_approvable(isolated):
    r=d.create('lead','bern','operator')
    fields={k:{'value':'x','status':'operator_confirmed','evidence':[],'reason':''} for k in d.FIELDS}
    fields['canton']['value']='Zurich'
    d.put('candidates',{'id':'c','run_id':r['id'],'fields':fields,'decision':'draft'})
    with pytest.raises(ValueError,match='outside'): d.review('c',{},'approved','op')
