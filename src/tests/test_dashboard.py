"""Dashboard: Apertus usage per web request (fake model), cost from the configured price, recall of saved eval runs."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import api, company as company_web, dashboard, llm, suggest  # noqa: E402


def _answer(content: str, prompt=1000, completion=200):
    def post(body, usage_in_stream=True):
        return httpx.Response(200, request=httpx.Request("POST", "http://x"), json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}})
    return post


@pytest.fixture()
def price(monkeypatch):
    monkeypatch.setattr(dashboard.settings, "llm_price_in", 2.0)     # CHF per million tokens
    monkeypatch.setattr(dashboard.settings, "llm_price_out", 10.0)


def test_meter_counts_calls_in_thread_pools(monkeypatch):
    monkeypatch.setattr(llm, "_post", _answer("hi", 10, 5))
    with llm.metered() as m, ThreadPoolExecutor(2) as pool:
        llm.chat([{"role": "user", "content": "x"}])
        list(pool.map(llm.bound(lambda _: llm.chat([{"role": "user", "content": "y"}])), range(3)))
    assert (m.calls, m.prompt_tokens, m.completion_tokens) == (4, 40, 20)
    assert llm.current_meter() is None


def test_each_request_that_calls_apertus_is_logged_with_its_cost(monkeypatch, price):
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)
    monkeypatch.setattr(llm, "_post", _answer(json.dumps({"companies": [{"name": "Gone", "website": "gone.example"}]})))

    def unreachable(url, max_extra=5):
        raise company_web.FetchError("The website could not be found.")
    monkeypatch.setattr(suggest.company_web, "read", unreachable)
    client = TestClient(api.app)
    assert client.post("/companies/suggest", json={"text": "glucose company in Milan"}).status_code == 200
    client.get("/health")                                       # no Apertus call: not logged

    rows = [json.loads(line) for line in dashboard.USAGE_PATH.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["route"] == "POST /companies/suggest" and row["calls"] == 1
    assert (row["prompt_tokens"], row["completion_tokens"]) == (1000, 200)
    assert "glucose" not in json.dumps(row)                     # the log never holds what was searched

    d = client.get("/dashboard").json()
    assert d["live"]["requests"] == 1 and d["live"]["calls"] == 1
    assert d["live"]["cost_chf"] == pytest.approx((1000 * 2 + 200 * 10) / 1e6)
    assert d["live"]["by_route"][0]["route"] == "POST /companies/suggest"


def test_cost_per_request_adds_up_every_call_for_that_case(price):
    m = llm.Meter(case_id="c1")
    m.add(1000, 100, 2.0)
    dashboard.record("POST /cases", m, 3.0)
    m2 = llm.Meter(case_id="c1")
    m2.add(500, 50, 1.0)
    dashboard.record("POST /cases/{cid}/rematch", m2, 1.5)
    m3 = llm.Meter()
    m3.add(200, 20, 0.5)
    dashboard.record("GET /search", m3, 0.8)
    live = dashboard.live({"c1": "GlucoFirm"})
    (case,) = live["cases"]
    assert case["company"] == "GlucoFirm" and case["requests"] == 2 and case["calls"] == 2
    assert case["cost_chf"] == pytest.approx((1500 * 2 + 150 * 10) / 1e6, abs=1e-4)
    assert live["requests"] == 3 and live["p95_s"] == 3.0
    assert dashboard.live({})["cases"][0]["deleted"] is True


def test_saved_eval_runs_and_reextraction_estimate(tmp_path, monkeypatch, price):
    monkeypatch.setattr(dashboard, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dashboard, "EVAL_DIR", tmp_path / "eval")
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "rules.json").write_text(json.dumps({
        "tag": "rules", "at": "2026-10-18T19:00:00", "recall_at_k": "88%", "traceability": "100%",
        "synonym_twins_consistent": "71%", "abstention_correct": "100%", "llm_tokens_per_query": 0,
        "config": {"llm_reachable": False, "entities_by_extractor": {"rules": 300, "openalex": 10}}}))
    (tmp_path / "eval" / "apertus.json").write_text(json.dumps({
        "tag": "apertus", "at": "2026-10-19T09:00:00", "recall_at_k": "91%", "llm_tokens_per_query": 1200,
        "llm_prompt_tokens_per_query": 1000, "llm_completion_tokens_per_query": 200,
        "config": {"llm_reachable": True, "llm_expansion": True, "entities_by_extractor": {"apertus": 300}}}))
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "x.jsonl").write_text("\n".join(json.dumps({"text": "a" * n}) for n in (400, 20000)))

    runs = dashboard.quality()
    assert [r["tag"] for r in runs] == ["rules", "apertus"]                       # oldest first
    assert runs[0]["recall"] == 88 and runs[0]["mode"] == "extraction rules; query terms glossary"
    assert runs[1]["cost_per_query_chf"] == pytest.approx((1000 * 2 + 200 * 10) / 1e6)

    est = dashboard.reextraction()
    assert est["pages"] == 2 and est["basis"] == "estimated"                       # no Apertus extraction yet
    (tmp_path / "extract_stats.json").write_text(json.dumps({
        "extractor": "apertus", "llm_usage": {"calls": 10, "prompt_tokens": 30000, "completion_tokens": 5000}}))
    got = dashboard.reextraction()
    assert got["basis"] == "measured" and got["prompt_tokens_per_page"] == 3000
    assert got["cost_chf"] == pytest.approx(round((6000 * 2 + 1000 * 10) / 1e6, 2))
