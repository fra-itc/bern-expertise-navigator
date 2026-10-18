"""A website typed into the broad search is read as the company's website, not searched as a topic (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import cases  # noqa: E402
from navigator.company import CompanyWebsite, WebPage  # noqa: E402
from test_cases_workflow import OFF, client  # noqa: E402,F401  (client: the shared fixture)


def test_split_link():
    assert cases.split_link("bracco.com") == ("bracco.com", "")
    assert cases.split_link("https://www.amplifon.com/") == ("https://www.amplifon.com/", "")
    assert cases.split_link("www.example.ch/en/about") == ("www.example.ch/en/about", "")
    assert cases.split_link("hearing aids, https://www.amplifon.com/de. In Milan") == \
        ("https://www.amplifon.com/de", "hearing aids, In Milan")
    for topic in ["glucose company in Milan", "Medtronic", "Node.js sensors in Bern", "e.g. insulin pumps"]:
        assert cases.split_link(topic) == ("", topic)


def test_a_link_in_the_broad_search_reads_the_website(client, monkeypatch):
    read, seen = [], {}
    site = CompanyWebsite(url="https://www.bracco.com/", name="Bracco",
                          description="Bracco Imaging develops contrast agents for diagnostic imaging.",
                          pages=[WebPage(url="https://www.bracco.com/", title="Bracco")],
                          text="Bracco Imaging develops contrast agents for MRI, CT and ultrasound imaging.")
    monkeypatch.setattr(cases.company_web, "read", lambda url: read.append(url) or site)
    real = cases.find_matches
    monkeypatch.setattr(cases, "find_matches", lambda analysis, k=12: (seen.update(q=analysis.search_query), real(analysis, k))[1])
    c = client.post("/cases", json={"request_text": "bracco.com", "broad": True, **OFF}).json()
    assert read == ["bracco.com"] and c["company_url"] == "https://www.bracco.com/" and c["website"]["name"] == "Bracco"
    assert "bracco com" not in seen["q"] and c["matches"] and c["offer"]["sources"]
    assert c["request_text"] == "" and c["understood"] == []


def test_abbreviations_in_the_glossary_count_only_in_capitals():
    from navigator import plain
    terms = lambda s: {t["term"] for t in plain.find_terms(s)}  # noqa: E731
    assert "automated insulin delivery" not in terms("Get a free hearing aid trial. Wearable hearing technology.")
    assert "automated insulin delivery" in terms("Our AID system connects pump and sensor.")
    assert terms("Soluzioni ai pazienti, Oct 2026") == set()
    assert "continuous glucose monitoring" in terms("a needle-free CGM patch")
