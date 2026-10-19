"""Faithfulness of the offer paragraph and the pitch (review of the Dexcom, Bracco and Amplifon cases, fake data)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import brief, cases, index, llm, needs, plain  # noqa: E402
from navigator.cases import Case, Match, OfferSource, _check, _cite, _faithful  # noqa: E402
from navigator.schema import Entity, Evidence  # noqa: E402

URL = "https://example.org/"


def _ent(i, name, etype, *snippets, unit=None, role=None, label="ARTORG Center"):
    return Entity(id=i, entity_type=etype, name=name, unit=unit, role=role, source="t", source_label=label,
                  source_urls=[URL + i], retrieved_at="2026",
                  evidence=[Evidence(field="description", value=s[:20], snippet=s, url=URL + i) for s in snippets])


# --- which asset shows which need ------------------------------------------------------------------------------
def test_a_need_is_linked_only_when_the_asset_text_shows_it():
    tw = needs.topic(plain.RequestAnalysis(summary="", search_query="contrast agents MRI", keywords=["contrast agents"]))
    reg = "Regulatory affairs expertise for global market approvals"
    assert not needs.supports("Publication: Clinical evidence for high-risk CE-marked medical devices", reg, tw)
    assert not needs.supports("Dapagliflozin's impact on hormonal regulation and ketogenesis", reg, tw)
    assert needs.supports("We prepare regulatory submissions to Swissmedic", reg, tw)
    # the need's topic as a phrase: optical contrast is not a contrast agent
    val = "Clinical validation partners for new contrast agents"
    assert not needs.supports("polarised light increases the contrast between healthy tissue; a clinical challenge", val, tw)
    assert needs.supports("clinical validation of new MRI contrast agents in patients", val, tw)
    assert needs.has("we run clinical studies", "study")                  # y -> ies


def test_needs_without_any_supporting_asset_are_listed_empty():
    a = plain.RequestAnalysis(summary="", company_needs=["Manufacturing talent", "Clinical validation partners"],
                              search_query="hearing aid", keywords=["hearing aids"])
    got = needs.pairs(a, {"hrl": "The lab develops instruments; clinical validation of cochlear implants.",
                          "surgeon": "Co-Head Otology and Hearing Implant Center"})
    assert got == {"Manufacturing talent": [], "Clinical validation partners": ["hrl"]}


# --- citation numbers -----------------------------------------------------------------------------------------------
def test_a_name_inside_another_name_gets_no_number():
    src = [OfferSource(n=1, id="w", name="Prof. Lilian Witthauer", kind="People", entity_type="person",
                       unit="Sensing & Monitoring Lab"),
           OfferSource(n=2, id="m", name="Monitoring", kind="Services", entity_type="infrastructure"),
           OfferSource(n=3, id="s", name="SPN-005 – Pilot study on painless glucose monitoring", kind="Studies",
                       entity_type="project")]
    out = _cite("Prof. Witthauer leads the Sensing & Monitoring Lab. Studies such as SPN-005 on painless glucose "
                "monitoring are supported by the Monitoring service.", src)
    assert out == ("Prof. Witthauer [1] leads the Sensing & Monitoring Lab. Studies such as SPN-005 [3] on painless "
                   "glucose monitoring are supported by the Monitoring [2] service.")


# --- the claim check ----------------------------------------------------------------------------------------------
def _amplifon():
    srcs = [OfferSource(n=1, id="hrl", name="Hearing Research Laboratory", kind="Organizations", entity_type="unit",
                        institution="ARTORG Center", about="The lab develops precision instruments for otological surgery."),
            OfferSource(n=2, id="m", name="Prof. Georgios Mantokoudis", kind="People", entity_type="person",
                        role="Co-Head Otology and Hearing Implant Center", institution="ARTORG Center"),
            OfferSource(n=3, id="s", name="Dr. Stephan Schraivogel", kind="People", entity_type="person",
                        role="Postdoctoral Researcher", institution="ARTORG Center")]
    case = Case(id="c", created_at="", updated_at="", company="Amplifon", analysis=plain.RequestAnalysis(
        summary="Amplifon provides hearing aids.", company_needs=["Manufacturing talent", "Regulatory compliance support"],
        search_query="hearing aid", keywords=["hearing aids"]))
    texts = {s.n: " ".join([s.name, s.role, s.institution, s.about]).lower() for s in srcs}
    return srcs, case, texts, {"Manufacturing talent": [], "Regulatory compliance support": []}


def test_invented_needs_and_shared_descriptions_are_rejected():
    srcs, case, texts, paired = _amplifon()
    ok = ("The Hearing Research Laboratory develops precision instruments for otological surgery. Prof. Georgios "
          "Mantokoudis is Co-Head of the Otology and Hearing Implant Center, and Dr. Stephan Schraivogel is a "
          "Postdoctoral Researcher.")
    assert _faithful(_cite(ok, srcs), srcs, case, texts, paired) is None
    bad = ok.replace("Prof. Georgios", "Manufacturing talent is available through Prof. Georgios")
    assert "Manufacturing" in _faithful(_cite(bad, srcs), srcs, case, texts, paired)
    bad = ok + " Regulatory compliance support can be pursued with Dr. Schraivogel."
    assert "Regulatory compliance support" in _faithful(_cite(bad, srcs), srcs, case, texts, paired)
    # "A and B, …, bring X": both must show X (Schraivogel's sources say nothing about instruments)
    bad = ("Prof. Georgios Mantokoudis and Dr. Stephan Schraivogel, a Postdoctoral Researcher, develop precision "
           "instruments. The Hearing Research Laboratory works on otological surgery.")
    assert "asset 2" in _faithful(_cite(bad, srcs), srcs, case, texts, paired)
    # a claim the sources do not make ("has conducted", "long experience")
    bad = ok.replace("develops precision instruments", "has long experience with precision instruments")
    assert "experience" in _faithful(_cite(bad, srcs), srcs, case, texts, paired)


def test_offer_retries_once_then_falls_back_to_the_template(monkeypatch):
    srcs, case, texts, paired = _amplifon()
    ents = {"hrl": _ent("hrl", "Hearing Research Laboratory", "unit", "The lab develops precision instruments for otological surgery."),
            "m": _ent("m", "Prof. Georgios Mantokoudis", "person", "Co-Head Otology and Hearing Implant Center", role="Co-Head"),
            "s": _ent("s", "Dr. Stephan Schraivogel", "person", "Postdoctoral Researcher", role="Postdoctoral Researcher")}
    monkeypatch.setattr(index, "load_entities", lambda: ents)
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)
    calls = []
    invented = ("Manufacturing talent is available through Prof. Georgios Mantokoudis. The Hearing Research Laboratory "
                "and Dr. Stephan Schraivogel are relevant.")
    monkeypatch.setattr(llm, "chat_json", lambda msgs, *a, **k: calls.append(msgs) or cases._Para(paragraph=invented))
    case.matches = [Match(id=i, name=e.name, entity_type=e.entity_type, role=e.role, institution="ARTORG Center",
                          url=URL + i) for i, e in ents.items()]
    o = cases.summarize_offer(case, "en")
    assert len(calls) == 2 and "Not accepted" in calls[1][-1]["content"]      # one retry, told what was wrong
    assert o.generated_by == "rules" and "Manufacturing talent is available" not in o.text
    assert o.text.endswith("Not shown on the public pages of a Bern partner: Manufacturing talent; Regulatory compliance support.")


def test_weak_matches_stay_out_of_the_offer(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    ms = [Match(id="a", name="Prof. A", entity_type="person", why="Weak match. Not about hearing aids.", url=URL + "a"),
          Match(id="b", name="Prof. B", entity_type="person", why="Works on hearing aids [1].", url=URL + "b")]
    case = Case(id="c", created_at="", updated_at="", company="X", analysis=plain.RequestAnalysis(summary="s"), matches=ms)
    o = cases.summarize_offer(case, "en")
    assert [s.id for s in o.sources] == ["b"] and "Prof. A" not in o.text


# --- the pitch and the officer's preface --------------------------------------------------------------------------
def test_pitch_needs_nobody_shows_get_no_partner_no_estimate_and_no_money(monkeypatch):
    ents = {"p": _ent("p", "Prof. Jane Example", "person",
                      "Her team runs clinical studies of continuous glucose monitoring patches with patients.",
                      "Publication: Clinical evidence for high-risk CE-marked medical devices")}
    monkeypatch.setattr(brief.index, "load_entities", lambda: ents)
    monkeypatch.setattr(brief.search, "neighbors", lambda ids: {})
    monkeypatch.setattr(brief.showcase, "build", lambda: {})
    monkeypatch.setattr(brief, "pubs_for", lambda e: [])
    monkeypatch.setattr(brief.llm, "available", lambda *a, **k: False)
    case = Case(id="c", created_at="", updated_at="", company="Glucopatch", analysis=plain.RequestAnalysis(
        summary="Glucopatch makes CGM patches.", search_query="continuous glucose monitoring patch",
        keywords=["continuous glucose monitoring"],
        company_needs=["Clinical validation partners for new patches", "Regulatory affairs expertise for approvals",
                       "Manufacturing talent and equipment for production"]),
        matches=[Match(id="p", name="Prof. Jane Example", entity_type="person", selected=True)])
    out = brief.build(case, "en", {"name": "Officer"})
    by = {n["id"]: n for n in out["brief"]["needs"]}
    assert [p["name"] for p in by["clinical"]["partners"]] == ["Prof. Jane Example"] and by["clinical"]["figure"]
    assert by["regulatory"]["partners"] == [] and not by["regulatory"]["figure"] and not by["regulatory"]["mail"]
    assert "not yet found a partner" in by["regulatory"]["solve"]                     # "CE-marked" is not regulatory work
    found = [ln["text"] for ln in out["explainer"][1]["lines"]]
    assert "They need official approval to sell a medical product. We did not find a partner in Bern" in " ".join(found)
    assert "Our own team" not in " ".join(found)
    how = " ".join(ln["text"] for ln in out["explainer"][3]["lines"])
    assert "approval" not in how and "estimate" not in how.lower()                 # no benefit for a need nobody shows
    everything = repr(out)
    assert not re.search(r"CHF|Fr\.\s?\d|\d[\d',.]*\s?(?:francs|CHF)", everything)  # "says nothing about money"
    assert "one potential partner whose public pages" in out["brief"]["hook"]
