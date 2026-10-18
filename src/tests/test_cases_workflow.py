"""Company-request workflow over the API: understand -> choose partners -> pitch & invite (no LLM, temp database)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import api, cases, llm, plain  # noqa: E402
from navigator.cases import Match  # noqa: E402

OFF = {"actor": "Maria"}
REQ = {"company": "Example Sensors GmbH (fictional)", "contact_name": "Anna Example", "contact_email": "anna@example.com",
       "country": "Germany", "request_text": "We develop a needle-free CGM patch for type 1 diabetes. "
       "We are looking for a clinical study partner and need help with CE marking.", **OFF}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    fake = [Match(id=f"e{i}", name=n, entity_type=t, institution="DCB", url=f"https://www.dcberne.com/{i}", why="test")
            for i, (n, t) in enumerate([("Prof. A", "person"), ("Lab B", "unit"), ("Dr. C", "person")])]
    monkeypatch.setattr(cases, "find_matches", lambda analysis, k=12: ([m.model_copy() for m in fake], None))
    monkeypatch.setattr(cases.showcase, "build", lambda: {"highlights": [{"quote": "Verified sentence.", "url": "https://x.ch/a"}]})
    return TestClient(api.app)


def test_plain_language_terms_from_glossary():
    found = {t["term"] for t in plain.find_terms(REQ["request_text"])}
    assert {"continuous glucose monitoring", "type 1 diabetes", "clinical study", "regulatory affairs"} <= found
    de = plain.find_terms("needle-free CGM", "de")
    assert any("Blutzucker" in t["plain"] for t in de)


def test_full_workflow(client):
    c = client.post("/cases", json=REQ).json()
    cid = c["id"]
    assert c["status"] == "new" and c["analysis"]["generated_by"] == "rules" and len(c["matches"]) == 3
    assert client.post(f"/cases/{cid}/draft", json=OFF).status_code == 400          # no partner chosen yet
    client.post(f"/cases/{cid}/selection", json={"selected": ["e0", "e2"], **OFF})
    d = client.post(f"/cases/{cid}/draft", json={"lang": "de", "slots": ["Di 10:00"], "sender": "Maria", **OFF}).json()
    assert "Prof. A" in d["body"] and "Dr. C" in d["body"] and "Lab B" not in d["body"]  # only chosen partners
    assert "Verified sentence." in d["body"] and "Di 10:00" in d["body"] and d["to"] == REQ["contact_email"]
    ics = client.get(f"/cases/{cid}/invite.ics", params={"start": "2026-10-22T14:00", "organizer_email": "m@x.ch"})
    assert ics.status_code == 200 and "BEGIN:VEVENT" in ics.text and "ATTENDEE;RSVP=TRUE:mailto:anna@example.com" in ics.text
    done = client.post(f"/cases/{cid}/outcome", json={"kind": "email", "subject": d["subject"], "body": d["body"], **OFF}).json()
    assert done["status"] == "contacted"
    assert [e["kind"] for e in done["events"]] == ["created", "analysed", "emailed"]
    assert client.post(f"/cases/{cid}/selection", json={"selected": [], **OFF}).status_code == 409  # locked once contacted
    assert client.get("/cases").json()[0]["status"] == "contacted"


def test_review_endpoints_are_gone_and_actions_need_a_name(client):
    cid = client.post("/cases", json=REQ).json()["id"]
    assert client.post(f"/cases/{cid}/review-request", json={"reviewer": "x", **OFF}).status_code in (404, 405)
    assert client.post(f"/cases/{cid}/review", json={"decision": "approved", **OFF}).status_code in (404, 405)
    assert client.post("/cases", json={**REQ, "actor": ""}).status_code == 422       # anonymous staff actions refused


def test_old_requests_from_the_review_era_still_load():
    raw = {"id": "abcdef1234", "created_at": "2026", "updated_at": "2026", "status": "approved", "company": "X",
           "request_text": "abc", "analysis": {"summary": "s"}, "reviewer": "Dr. R", "review_comment": "ok",
           "matches": [{"id": "e0", "name": "A", "entity_type": "person", "selected": True, "review": "ok"}],
           "events": [{"at": "2026", "actor": "Dr. R", "role": "reviewer", "kind": "approved"}]}
    c = cases.Case.model_validate(raw)
    assert c.status == "new" and c.matches[0].selected


def test_search_first_request_with_filters(client, monkeypatch):
    """A request can start as a short search + filters; the niche sharpens the search; details come later."""
    seen = {}
    real = cases.find_matches

    def spy(analysis, k=12):
        seen["q"] = analysis.search_query
        return real(analysis, k)
    monkeypatch.setattr(cases, "find_matches", spy)
    c = client.post("/cases", json={"request_text": "partner for a sensor study", "country": "Switzerland",
                                    "canton": "Zürich", "area": "diabetes", "niche": "glucose", **OFF}).json()
    assert c["company"] == "" and c["canton"] == "Zürich" and c["niche"] == "glucose"
    assert seen["q"].startswith("continuous glucose monitoring")          # niche terms lead the search
    de = client.post("/cases", json={"request_text": "sensor study", "country": "Germany", "canton": "Zürich", **OFF}).json()
    assert de["canton"] == ""                                              # cantons only for Swiss companies
    areas = client.get("/medtech-areas").json()
    assert any(a["id"] == "diabetes" and any(n["id"] == "glucose" for n in a["niches"]) for a in areas)


def test_company_details_needed_before_pitch(client):
    cid = client.post("/cases", json={"request_text": "partner for a sensor study", **OFF}).json()["id"]
    client.post(f"/cases/{cid}/selection", json={"selected": ["e0"], **OFF})
    assert client.post(f"/cases/{cid}/brief", json={"lang": "en", **OFF}).status_code == 400   # no company yet
    d = client.post(f"/cases/{cid}/details", json={"company": "X AG", "contact_email": "ceo@x.ch", **OFF}).json()
    assert d["company"] == "X AG" and d["contact_email"] == "ceo@x.ch"


def test_broad_search_reads_place_and_topic(client, monkeypatch):
    seen = {}
    real = cases.find_matches

    def spy(analysis, k=12):
        seen["q"] = analysis.search_query
        return real(analysis, k)
    monkeypatch.setattr(cases, "find_matches", spy)
    c = client.post("/cases", json={"request_text": "glucose company in Milan", "broad": True, **OFF}).json()
    assert (c["city"], c["country"], c["area"], c["niche"]) == ("Milan", "Italy", "diabetes", "glucose")
    assert "milan" not in seen["q"].lower() and seen["q"].startswith("continuous glucose monitoring")
    assert {d["kind"] for d in c["understood"]} >= {"city", "country", "niche"}
    # explicit filters win over what the sentence says
    c2 = client.post("/cases", json={"request_text": "Glukosesensor-Firma aus München", "broad": True,
                                     "area": "imaging", **OFF}).json()
    assert (c2["country"], c2["area"], c2["niche"]) == ("Germany", "imaging", "")
    # the same text without broad mode is treated as pasted information (no place guessing)
    c3 = client.post("/cases", json={"request_text": "We sell in Switzerland and Italy", **OFF}).json()
    assert c3["country"] == "" and c3["understood"] == []
    live = client.get("/understand", params={"q": "azienda di glucosio a Milano"}).json()
    assert live["city"] == "Milan" and live["niche"] == "glucose"
