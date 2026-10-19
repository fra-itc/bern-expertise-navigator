"""Private knowledge: membership, persistence, processing and source-backed retrieval."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from navigator import knowledge, knowledge_access, llm, cases, company
from navigator.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(knowledge_access, "attempts", {})
    configured = {
        "officer@example.test": {"name": "Officer", "organization": "kanton-bern", "active": True,
                                 "password_hash": knowledge_access.password_hash("test-password")},
        "external@example.test": {"organization": "external", "active": True,
                                  "password_hash": knowledge_access.password_hash("test-password")},
    }
    monkeypatch.setattr(knowledge_access, "accounts", lambda: configured)
    monkeypatch.setenv("KB_ACCOUNTS_FILE", str(tmp_path / "accounts.json"))   # the operator configured accounts
    return TestClient(app)


def login(client):
    return client.post("/staff/session", json={"email": "officer@example.test", "password": "test-password"})


def test_membership_is_not_a_browser_field_or_email_domain(client):
    assert client.get("/staff/session").json() == {"can_manage_knowledge": False}
    assert client.get("/kb/companies", headers={"X-Email": "officer@be.ch"}).status_code == 403
    assert client.post("/kb/companies", json={"name": "X", "actor": "officer@be.ch"}).status_code == 403
    assert client.post("/staff/session", json={"email": "external@example.test", "password": "test-password"}).status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/staff/session").json()["can_manage_knowledge"] is True
    assert client.get("/kb/companies").headers["cache-control"] == "no-store"
    assert client.delete("/staff/session").status_code == 200
    assert client.get("/kb/companies").status_code == 403


def test_process_notes_documents_and_delete(client, monkeypatch):
    login(client)
    monkeypatch.setattr(cases, "find_matches", lambda profile: ([cases.Match(id="p", name="Bern lab", entity_type="unit", url="https://example.org")], None))
    body = {"name": "Sensor Company", "canton": "Bern", "notes": "We develop glucose monitoring sensors for clinical studies.",
            "documents": [{"name": "client.txt", "kind": "Text", "text": "Clinical validation of glucose sensors."}]}
    response = client.post("/kb/companies", json=body)
    assert response.status_code == 202
    entry_id = response.json()["id"]
    record = client.get("/kb/companies").json()[0]
    assert record["status"] == "ready"
    assert record["actor"] == "officer@example.test"
    assert record["profile"]["summary"] and record["matches"] == []
    hits = client.get("/kb/search", params={"q": "glucose sensors"}).json()
    assert any(hit["source"] == "client.txt" for hit in hits)
    assert all(hit["snippet"] in body["notes"] or hit["snippet"] in body["documents"][0]["text"] for hit in hits)
    assert client.put("/kb/companies/" + entry_id, json={"name": "Changed", "notes": "Different robotics expertise"}).status_code == 202
    assert client.get("/kb/search", params={"q": "glucose"}).json() == []
    assert client.delete("/kb/companies/" + entry_id).status_code == 200
    assert client.get("/kb/companies").json() == []


def test_failed_links_do_not_discard_notes(client, monkeypatch):
    login(client)
    def fail(url):
        raise company.FetchError("Source unavailable")
    monkeypatch.setattr(company, "read", fail)
    response = client.post("/kb/companies", json={"name": "X", "canton": "Bern", "links": ["https://example.org"], "notes": "Robotics research and innovation."})
    assert response.status_code == 202
    record = client.get("/kb/companies").json()[0]
    assert record["status"] == "partial" and record["errors"][0]["url"] == "https://example.org"
    assert client.get("/kb/search", params={"q": "Robotics"}).json()


def test_stale_jobs_cannot_restore_deleted_or_edited_content(client):
    first = knowledge.save(knowledge.KnowledgeInput(name="Old", notes="Old text"), "officer")
    newer = knowledge.save(knowledge.KnowledgeInput(name="New", notes="New text"), "officer", first["id"])
    knowledge.process(first["id"], first["revision"])
    assert knowledge.get(first["id"])["revision"] == newer["revision"]
    knowledge.delete(first["id"])
    assert knowledge._update(newer) is False
    assert knowledge.get(first["id"]) is None


def test_document_upload_and_cross_origin_protection(client):
    assert client.post("/kb/documents?name=notes.txt", content=b"Private notes").status_code == 403
    login(client)
    doc = client.post("/kb/documents?name=notes.txt", content=b"Clinical sensors and private notes for a glucose monitoring validation study.")
    assert doc.status_code == 200 and "Clinical sensors" in doc.json()["text"]
    assert client.post("/kb/companies", json={"name": "X"}, headers={"Origin": "https://external.test"}).status_code == 403
    assert client.post("/kb/companies", json={"name": " "}).status_code == 422
    assert client.post("/kb/companies", json={"name": "X", "links": ["javascript:alert(1)"]}).status_code == 422


def test_internal_preview_requires_explicit_flag_and_loopback(monkeypatch):
    from starlette.requests import Request
    local = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    remote = Request({"type": "http", "client": ("192.0.2.1", 1234), "headers": []})
    monkeypatch.delenv("KB_INTERNAL_PREVIEW", raising=False)
    assert knowledge_access.member(local) is None
    monkeypatch.setenv("KB_INTERNAL_PREVIEW", "1")
    assert knowledge_access.member(local)["can_manage_knowledge"]
    assert knowledge_access.member(remote) is None


def test_lead_geographic_scope_excludes_unknown_and_southern_companies(client):
    login(client)
    for canton in ("Bern", "Zurich", "Ticino", ""):
        client.post('/kb/companies', json={"name": canton or "Unknown", "canton": canton, "notes": "Glucose sensors for clinical research and innovation."})
    bern = client.get('/kb/search', params={"q": "glucose", "scope": "bern"}).json()
    north = client.get('/kb/search', params={"q": "glucose", "scope": "north"}).json()
    assert {hit['canton'] for hit in bern} == {'Bern'}
    assert {hit['canton'] for hit in north} == {'Bern', 'Zurich'}
    assert client.get('/kb/search', params={"q": "glucose", "scope": "all"}).status_code == 422


def test_analytics_counts_recorded_sectors_and_evidenced_outcomes(client, monkeypatch):
    from types import SimpleNamespace
    from navigator import analytics
    assert client.get('/kb/analytics').status_code == 403
    login(client)
    knowledge.save(knowledge.KnowledgeInput(name='Tech company', canton='Bern', sector='tech', topics=['AI', 'ai', 'Sensors']), 'officer')
    knowledge.save(knowledge.KnowledgeInput(name='Unclassified'), 'officer')
    def lead(lead_id):
        return SimpleNamespace(id=lead_id, company='Same Company', status='contacted', events=[], outreach={},
                               matches=[], analysis=SimpleNamespace(summary='Plain company description'), updated_at='2026-10-19')
    monkeypatch.setattr(cases, 'list_cases', lambda: [lead('one'), lead('two')])
    monkeypatch.setattr(cases, 'get', lambda entry_id: lead(entry_id) if entry_id == 'one' else None)
    data = client.get('/kb/analytics').json()
    assert data['counts']['knowledge_companies'] == 2
    assert data['counts']['contacted'] == 1 and data['counts']['lead_companies'] == 1
    assert data['counts']['established'] == 0 and data['counts']['collaboration'] == 0
    assert data['sectors'] == {'tech': 1, 'unclassified': 1}
    assert data['topics']['ai'] == 1
    assert client.put('/kb/leads/one/progress', json={'stage': 'established', 'evidence': ''}).status_code == 422
    response = client.put('/kb/leads/one/progress', json={'stage': 'collaboration', 'evidence': 'Written partner confirmation dated 19 October.'})
    assert response.status_code == 200 and response.json()['actor'] == 'officer@example.test'
    assert client.get('/kb/analytics').json()['counts']['collaboration'] == 1
    client.put('/kb/leads/one/progress', json={'stage': 'established', 'evidence': 'Establishment confirmed by the canton in the recorded case file.'})
    assert client.get('/kb/analytics').json()['counts']['established'] == 1
    assert client.put('/kb/leads/missing/progress', json={'stage': 'prospect'}).status_code == 404


def test_agent_cannot_generate_or_send_pitch_or_change_production_role(client):
    assert login(client).status_code == 200
    assert client.get('/staff/session').json()['role'] == 'agent'
    for path in ('brief', 'draft', 'outcome', 'delivery'):
        payload = {'actor': 'Agent', 'kind': 'email', 'subject': 'Pitch', 'body': 'Reviewed', 'idempotency_key': 'test-role-key-123456'}
        assert client.post('/cases/missing/' + path, json=payload).status_code == 403
    assert client.patch('/staff/preview-role', json={'role': 'representative'}).status_code == 403


def test_without_accounts_the_workspace_keeps_the_staff_login_and_the_knowledge_base_stays_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("KB_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("KB_INTERNAL_PREVIEW", raising=False)
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    client = TestClient(app)
    assert client.get("/cases").status_code == 200          # behind the Caddy staff login, as before
    assert client.post("/cases/missing/draft", json={"actor": "Maria"}).status_code == 404   # past the role check
    assert client.get("/kb/companies").status_code == 403   # not behind Caddy: needs a canton account
    assert client.get("/discovery/runs").status_code == 403


def test_cases_are_private_without_verified_session(client):
    assert client.get('/cases').status_code == 403
    assert client.post('/cases', json={'company': 'Example', 'actor': 'Guest'}).status_code == 403
