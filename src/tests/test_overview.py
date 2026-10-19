"""Manager dashboard: where requests stand, the work over time, and the Apertus 8B summary (fake data)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import api, cases, dashboard, llm, overview, plain  # noqa: E402
from navigator.cases import Case, Event, Match  # noqa: E402

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _case(i, days_ago, status="new", brief=False, matched=True, emailed=False, replied=False, pitch_days_ago=None):
    created = NOW - timedelta(days=days_ago)
    ev = [Event(at=created.isoformat(), actor="t", kind="created")]
    out = {}
    if brief:
        at = NOW - timedelta(days=pitch_days_ago if pitch_days_ago is not None else days_ago)
        ev.append(Event(at=at.isoformat(), actor="t", kind="brief_prepared"))
        out["brief"] = {"token": f"t{i}", "at": at.isoformat(), "views": 1 if emailed else 0, "data": {}}
    if emailed:
        ev.append(Event(at=(created + timedelta(hours=5)).isoformat(), actor="t", kind="emailed"))
    if replied:
        ev.append(Event(at=(created + timedelta(days=1)).isoformat(), actor="t", kind="replied"))
        out["replies"] = [{"kind": "call"}]
    return Case(id=f"c{i}", created_at=created.isoformat(), updated_at=created.isoformat(), status=status,
                company=f"Company {i}", country="Germany" if i % 2 else "Italy", area="diabetes",
                analysis=plain.RequestAnalysis(summary="s"), outreach=out, events=ev,
                matches=[Match(id="p", name="P", entity_type="person", selected=True)] if matched else [])


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    for c in [_case(1, 1), _case(2, 5),                                          # to do (one waiting > 3 days)
              _case(3, 4, brief=True, pitch_days_ago=3), _case(4, 1, brief=True),  # pitch ready (one waiting > 2 days)
              _case(5, 6, "contacted", brief=True, emailed=True),                  # invited
              _case(6, 8, "interested", brief=True, emailed=True, replied=True),   # replied
              _case(7, 2, matched=False),                                          # no match
              _case(8, 60, "closed", brief=True, emailed=True)]:                    # outside 30 days
        cases.save(c)


def test_stages_funnel_rates_and_attention(store):
    o = overview.build(30, now=NOW)
    assert o["total"] == 7 and o["all_total"] == 8 and o["unit"] == "day" and len(o["periods"]) == 31
    assert o["stages"] == {"todo": 2, "ready": 2, "done": 1, "replied": 1, "none": 1}
    assert o["funnel"] == {"received": 7, "matched": 6, "pitch": 4, "invited": 2, "opened": 2, "replied": 1}
    assert o["kpi"]["open_rate"] == 100 and o["kpi"]["reply_rate"] == 50 and o["kpi"]["match_rate"] == 86
    att = {a["kind"]: a["ids"] for a in o["attention"]}
    assert att == {"replied": ["c6"], "ready_waiting": ["c3"], "todo_waiting": ["c2"], "no_match": ["c7"]}
    assert sum(sum(v) for v in o["received"].values()) == 7 and sum(o["work"]["received"]) == 7
    assert overview.build(None, now=NOW)["unit"] == "week"                 # all time spans 60 days: weeks


def test_summary_is_written_by_apertus_8b_and_checked(store, monkeypatch):
    o = overview.build(30, now=NOW)
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)
    seen = []

    def fake(msgs, schema, **kw):
        seen.append(kw.get("model"))
        assert "Company 1" not in msgs[-1]["content"]                       # aggregate figures only, no names
        return overview._Text(text="7 requests came in. 1 company replied and waits for an answer: reply first.")
    monkeypatch.setattr(llm, "chat_json", fake)
    overview._cache.clear()
    a = overview.analysis(o, "en")
    assert a["by"] == "apertus" and a["model"] == "apertus-v1-5-8b" and seen == ["apertus-v1-5-8b"]
    # a number that is not among the figures: one retry, then the rules text, and the page says why
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: overview._Text(text="Requests grew by 340% this week, a record."))
    overview._cache.clear()
    a = overview.analysis(o, "de")
    assert a["by"] == "rules" and a["reason"] == "unchecked_numbers" and a["text"].startswith("In den letzten 30 Tagen sind 7")


def test_routes_and_usage_log_name_the_8b_model(store, tmp_path, monkeypatch):
    from navigator import knowledge_access
    monkeypatch.setattr(knowledge_access, "member", lambda request: {"email": "m@example.test", "role": "representative"})
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    c = TestClient(api.app)
    o = c.get("/cases/overview", params={"days": 0}).json()
    assert o["total"] == 8 and o["days"] is None
    assert c.get("/cases/overview/analysis", params={"days": 30, "lang": "fr"}).json()["text"].startswith("Sur les 30 derniers jours")
    assert c.get("/cases/c1").json()["id"] == "c1"                          # /cases/{cid} still answers
    m = llm.Meter()
    m.add(10, 5, 0.1, "apertus-v1-5-8b")
    monkeypatch.setattr(dashboard, "USAGE_PATH", tmp_path / "usage.jsonl")
    dashboard.record("GET /cases/overview/analysis", m, 0.2)
    assert '"model": "apertus-v1-5-8b"' in (tmp_path / "usage.jsonl").read_text()
