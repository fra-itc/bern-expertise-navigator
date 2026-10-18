"""The company's side of the pitch: opening the brief, replying, and the private link's lifetime (no LLM, temp db)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import cases, reply  # noqa: E402
from test_brief import OFF, _chosen_case, client  # noqa: E402,F401  (client: the shared fixture)


def _pitched(client):
    cid = _chosen_case(client)
    tok = client.post(f"/cases/{cid}/brief", json={"lang": "en", "email": "maria@x.ch", **OFF}).json()["token"]
    return cid, tok


def test_openings_are_counted_but_not_the_officers_preview(client):
    cid, tok = _pitched(client)
    assert client.get(f"/briefs/{tok}", params={"preview": True}).status_code == 200
    assert "views" not in client.get(f"/cases/{cid}").json()["outreach"]["brief"]
    b = client.get(f"/briefs/{tok}").json()
    assert b["reply"]["visit"] == "I'd like to visit Bern" and "Maria will get back to you" in b["reply"]["lead"]
    client.get(f"/briefs/{tok}")
    c = client.get(f"/cases/{cid}").json()
    assert c["outreach"]["brief"]["views"] == 2
    assert [e["kind"] for e in c["events"]].count("brief_opened") == 1          # logged once, then only counted
    assert client.get("/cases").json()[0]["views"] == 2
    # preparing the pitch again keeps the link and what was seen
    client.post(f"/cases/{cid}/brief", json={"lang": "de", **OFF})
    assert client.get(f"/cases/{cid}").json()["outreach"]["brief"]["views"] == 2


def test_reply_marks_the_request_interested_and_reopens_a_closed_one(client):
    cid, tok = _pitched(client)
    client.post(f"/cases/{cid}/outcome", json={"kind": "closed", "detail": "no answer", **OFF})
    r = client.post(f"/briefs/{tok}/reply", json={"kind": "visit", "name": "Anna Example", "email": "anna@example.com",
                                                 "message": "Week 45 works for us."})
    assert r.status_code == 201
    c = client.get(f"/cases/{cid}").json()
    assert c["status"] == "interested"
    assert c["outreach"]["replies"][0] | {"at": ""} == {"kind": "visit", "name": "Anna Example", "email": "anna@example.com",
                                                        "message": "Week 45 works for us.", "at": ""}
    ev = c["events"][-1]
    assert ev["actor"] == "Anna Example" and ev["kind"] == "replied" and "Week 45" in ev["text"] and "reopened" in ev["text"]
    assert client.get("/cases").json()[0]["replies"] == 1
    assert client.post(f"/briefs/{tok}/reply", json={"kind": "lunch"}).status_code == 422


def test_marking_the_email_sent_keeps_the_link_it_contains(client):
    cid, tok = _pitched(client)
    client.post(f"/briefs/{tok}/reply", json={"kind": "question", "message": "Is there parking?"})
    client.post(f"/cases/{cid}/outcome", json={"kind": "email", "subject": "s", "body": f"#/b/{tok}", **OFF})
    assert client.get(f"/briefs/{tok}").status_code == 200
    assert len(client.get(f"/cases/{cid}").json()["outreach"]["replies"]) == 1


def test_disabled_link_is_gone_and_a_new_pitch_gets_a_new_link(client):
    cid, tok = _pitched(client)
    c = client.post(f"/cases/{cid}/brief/revoke", json=OFF).json()
    assert c["outreach"]["brief"]["revoked_at"] and c["events"][-1]["kind"] == "brief_revoked"
    r = client.get(f"/briefs/{tok}")
    assert r.status_code == 410 and r.json()["detail"]["state"] == "revoked" and r.json()["detail"]["email"] == "maria@x.ch"
    assert client.post(f"/briefs/{tok}/reply", json={"kind": "visit"}).status_code == 410
    new = client.post(f"/cases/{cid}/brief", json={"lang": "en", **OFF}).json()["token"]
    assert new != tok and client.get(f"/briefs/{new}").status_code == 200 and client.get(f"/briefs/{tok}").status_code == 410
    assert client.post("/cases/nope/brief/revoke", json=OFF).status_code == 404


def test_expired_link_comes_back_when_the_pitch_is_prepared_again(client):
    cid, tok = _pitched(client)
    c = cases.get(cid)
    assert reply.state(c.outreach["brief"]) == "ok"
    c.outreach["brief"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    cases.save(c)
    assert client.get(f"/briefs/{tok}").json()["detail"]["state"] == "expired"
    assert client.post(f"/cases/{cid}/brief", json={"lang": "en", **OFF}).json()["token"] == tok
    assert client.get(f"/briefs/{tok}").status_code == 200


def test_replies_are_capped_and_tokens_are_checked_safely(client, monkeypatch):
    cid, tok = _pitched(client)
    monkeypatch.setattr(reply, "MAX_REPLIES", 2)
    assert [client.post(f"/briefs/{tok}/reply", json={"kind": "call"}).status_code for _ in range(3)] == [201, 201, 429]
    assert client.get("/briefs/ünïcode").status_code == 404                      # not a server error
