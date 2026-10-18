"""Broad search without a company: Apertus suggests, each company's own homepage confirms (fake model and sites)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import company as company_web, llm, suggest  # noqa: E402

SITES = {
    "glucofirm.example": ("GlucoFirm", "Sensori per il monitoraggio del glucosio, sede a Milano.", "Il nostro team di Milano sviluppa sensori."),
    "dexsense.example": ("DexSense", "", "DexSense makes continuous glucose monitoring patches for people with diabetes."),
    "shoes.example": ("Shoes Milano", "Scarpe di lusso a Milano.", "Collezione autunno."),
    "insulina.example": ("InsuPump", "Insulin pumps.", "Automated insulin delivery systems, Milan office."),
}


@pytest.fixture()
def fake(monkeypatch):
    calls = {"llm": 0, "read": []}
    proposals = [("GlucoFirm", "glucofirm.example"), ("DexSense", "https://www.dexsense.example/"),
                 ("Shoes Milano", "shoes.example"), ("Ghost Medical", "ghost.example"),
                 ("GlucoFirm again", "www.glucofirm.example"), ("InsuPump", "insulina.example")]

    def chat_json(msgs, schema, **kw):
        calls["llm"] += 1
        calls["prompt"] = msgs[-1]["content"]
        return schema(companies=[{"name": n, "website": w} for n, w in proposals])

    def read(url, max_extra=5):
        calls["read"].append((url, max_extra))
        host = url.split("//")[-1].removeprefix("www.").strip("/")
        if host not in SITES:
            raise company_web.FetchError("The website could not be found.")
        name, desc, text = SITES[host]
        return company_web.CompanyWebsite(url=f"https://{host}/", name=name, description=desc, text=text)

    monkeypatch.setattr(llm, "available", lambda *a, **k: True)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(suggest.company_web, "read", read)
    return calls


def test_only_companies_whose_site_talks_about_the_topic_are_shown(fake):
    s = suggest.suggest("glucose company in Milan")
    assert "Place: Milan" in fake["prompt"] and "diabetes / glucose" in fake["prompt"]
    # shoes: the site is not about glucose; ghost: no website; the duplicate host is read once;
    # insulin pumps are diabetes but not glucose sensing -> the site must name the niche's words
    assert [c.name for c in s.candidates] == ["GlucoFirm", "DexSense"]
    first = s.candidates[0]
    assert first.place_found == "Milan" and first.url == "https://glucofirm.example/"   # "Milano" on the page
    assert first.description == "Sensori per il monitoraggio del glucosio, sede a Milano."   # the company's own words
    assert s.candidates[1].description.startswith("DexSense makes continuous glucose monitoring")
    assert all(extra == 0 for _, extra in fake["read"]) and len(fake["read"]) == 5           # homepages only, deduped


def test_a_link_skips_the_suggestions(fake):
    s = suggest.suggest("https://www.amplifon.com/")
    assert s.link == "https://www.amplifon.com/" and s.candidates == [] and fake["llm"] == 0


def test_honest_when_nothing_can_be_suggested(fake, monkeypatch):
    monkeypatch.setattr(suggest.company_web, "read", lambda url, max_extra=5: (_ for _ in ()).throw(company_web.FetchError("x")))
    s = suggest.suggest("glucose company in Milan")
    assert s.candidates == [] and "could be verified" in s.message
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    assert "not reachable" in suggest.suggest("glucose company in Milan").message


def test_at_most_three(fake, monkeypatch):
    monkeypatch.setattr(suggest, "_words", lambda u: [])          # no topic to check: every reachable site counts
    assert len(suggest.suggest("medtech").candidates) == 3
