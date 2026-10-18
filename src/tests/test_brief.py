"""The two outputs: plain explanation for the officer + sourced executive brief for the CEO (fake data, no LLM)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import api, brief, cases, llm, search  # noqa: E402
from navigator.cases import Match  # noqa: E402
from navigator.schema import Entity, Evidence, Page  # noqa: E402

URL = "https://www.dcberne.com/en/team/"
PUB_URL = "https://www.dcberne.com/en/projects/"


def _ent(i, name, etype, ev):
    return Entity(id=i, entity_type=etype, name=name, unit="Sensing Lab", source="dcb", source_label="Diabetes Center Berne",
                  source_urls=[URL], retrieved_at="2026-10-18",
                  evidence=[Evidence(field="name", value=name, snippet=name, url=URL), *ev])


ENTS = {
    "p1": _ent("p1", "Prof. Jane Example", "person", [
        Evidence(field="expertise", value="continuous glucose monitoring",
                 snippet="Her lab develops new sensors for continuous glucose monitoring in daily life.", url=URL)]),
    "p2": _ent("p2", "Dr. Not Approved", "person", []),
}
PAGES = [Page(url=PUB_URL, source="dcb", title="Projects", fetched_at="2026", text=(
    "Recent publications\nExample J, Other A. Accuracy of a new CGM system in daily life. Diabetes Care 2025. "
    "doi: 10.1234/dc25-0001\nUnrelated B. Something else entirely, 2024, doi: 10.9999/xyz-2"))]
REQ = {"company": "Example Sensors (fictional)", "contact_email": "ceo@example.com",
       "request_text": "We build a needle-free CGM patch and look for a clinical study partner.", "actor": "Maria"}
OFF = {"actor": "Maria"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cases, "DB", tmp_path / "cases.db")
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    monkeypatch.setattr(brief.index, "load_entities", lambda: ENTS)
    monkeypatch.setattr(search, "graph", lambda: {})
    monkeypatch.setattr(brief.crawl, "load_pages", lambda source=None: PAGES)
    brief._publications.cache_clear()
    hl = [{"figure": "100+", "label": {"en": "start-ups"}, "quote": "we work with more than 100 start-ups.", "url": "https://x.ch/i"}]
    monkeypatch.setattr(brief.showcase, "build", lambda: {"highlights": hl})
    monkeypatch.setattr(cases.showcase, "build", lambda: {"highlights": hl})
    matches = [Match(id="p1", name="Prof. Jane Example", entity_type="person", institution="DCB", url=URL),
               Match(id="p2", name="Dr. Not Approved", entity_type="person", institution="DCB", url=URL)]
    monkeypatch.setattr(cases, "find_matches", lambda analysis, k=12: ([m.model_copy() for m in matches], None))
    return TestClient(api.app)


def _chosen_case(client):
    cid = client.post("/cases", json=REQ).json()["id"]
    client.post(f"/cases/{cid}/selection", json={"selected": ["p1"], **OFF})   # p2 is offered but not chosen
    return cid


def test_brief_only_chosen_partners_and_everything_sourced(client):
    cid = _chosen_case(client)
    r = client.post(f"/cases/{cid}/brief", json={"lang": "en", "email": "maria@x.ch", **OFF}).json()
    b = r["brief"]
    assert [i["name"] for i in b["items"]] == ["Prof. Jane Example"]  # a partner not chosen is not pitched
    item = b["items"][0]
    assert item["topics"][0]["term"] == "continuous glucose monitoring"
    assert "continuous glucose monitoring" in item["quote"]["text"] and item["quote"]["ref"] >= 1
    assert [p["doi"] for p in item["publications"]] == ["10.1234/dc25-0001"]  # surname match, not the unrelated one
    n = len(b["sources"])
    refs = [item["quote"]["ref"], item["page_ref"], *(x["ref"] for x in item["technical"]),
            *(p["ref"] for p in item["publications"]), *(h["ref"] for h in b["proof"])]
    assert all(1 <= x <= n for x in refs)  # every statement points to a numbered source
    assert any(s["kind"] == "doi" and s["url"] == "https://doi.org/10.1234/dc25-0001" for s in b["sources"])
    assert "agreed" not in b["hook"].lower() and "money" not in b["hook"].lower()
    titles = [s["title"] for s in r["explainer"]]
    assert titles[0] == "Summary of the pitch" and "What we deliberately do not say" in titles
    assert any("A small sensor worn on the skin" in ln.get("plain", "") for s in r["explainer"] for ln in s["lines"])
    # public link: works, read-only, stable across updates
    pub = client.get(f"/briefs/{r['token']}").json()
    assert pub["company"] == REQ["company"] and client.get("/briefs/wrong-token").status_code == 404
    r2 = client.post(f"/cases/{cid}/brief", json={"lang": "de", **OFF}).json()
    assert r2["token"] == r["token"] and "Bern" in r2["brief"]["hook"]


def test_brief_needs_chosen_partners_and_email_links_it(client):
    cid = client.post("/cases", json=REQ).json()["id"]
    client.post(f"/cases/{cid}/selection", json={"selected": [], **OFF})
    assert client.post(f"/cases/{cid}/brief", json={"lang": "en", **OFF}).status_code == 400
    cid = _chosen_case(client)
    tok = client.post(f"/cases/{cid}/brief", json={"lang": "en", **OFF}).json()["token"]
    d = client.post(f"/cases/{cid}/draft", json={"lang": "en", "link": f"http://h/#/b/{tok}", **OFF}).json()
    assert f"#/b/{tok}" in d["body"] and "Prof. Jane Example" in d["body"] and "Dr. Not Approved" not in d["body"]
