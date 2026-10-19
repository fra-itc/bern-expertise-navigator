"""Company matching keeps only partners with a specific link to the company's topic (fake index, no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import cases, llm, plain, search  # noqa: E402
from navigator.schema import Affiliation, Entity, Evidence, SearchResponse, SearchResult, SourceRef  # noqa: E402

URL = "https://www.artorg.unibe.ch/x"
AMPLIFON = ("digital hearing aid technology development, audiological clinical trials, hearing aid manufacturing "
            "expertise, Bluetooth-enabled medical devices, hearing loss treatment innovation, Swiss medtech R&D partners")


def _ent(i, name, etype, text, unit=None):
    return Entity(id=i, entity_type=etype, name=name, unit=unit, source="artorg", source_label="ARTORG",
                  source_urls=[URL], retrieved_at="2026-10-18",
                  evidence=[Evidence(field="name", value=name, snippet=name, url=URL),
                            Evidence(field="description", value=text, snippet=text, url=URL)])


ENTS = {e.id: e for e in [
    _ent("hrl", "Hearing Research Laboratory", "unit", "We develop cochlear implants and study hearing loss."),
    _ent("aeb", "Dr. Philipp Aebischer", "person", "Electrophysiology of the auditory system.", "Hearing Research Laboratory"),
    _ent("trim", "TrimLab", "unit", "Translational immunometabolism laboratory."),
    _ent("bal", "Prof. Maria Balmer", "person", "Metabolism and immunity in diabetes.", "TrimLab"),
    _ent("perio", "Dr. Periodontist", "person", "Clinical treatment and development of periodontal therapies."),
    _ent("path", "Dr. Pathologist", "person", "Computer aid for tissue diagnosis in pathology."),
    _ent("cochlea", "Dr. Implant Surgeon", "person", "Cochlear implant surgery."),
    _ent("hip", "Prof. Hip Surgeon", "person", "Primary stability of the hip implant in arthroplasty."),
]}


@pytest.fixture()
def fake_index(monkeypatch):
    monkeypatch.setattr(cases.index, "load_entities", lambda: ENTS)
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    # document frequencies of a 100-profile index: "clinical" and "treatment" are everywhere, "hearing" is rare
    common = {"clinical": 40, "treatment": 35, "diabetes": 10}
    monkeypatch.setattr(cases, "_doc_freq", lambda: (100, common))

    def fake_search(q, k=10, llm_explain=True, **kw):
        res = [SearchResult(id=e.id, person_or_unit=e.name, entity_type=e.entity_type, role=None,
                            affiliation=Affiliation(unit=e.unit, institution="ARTORG"), institution="ARTORG",
                            expertise=[], projects=[], infrastructure_services=[], contact=None, why_match="close in meaning",
                            via="TrimLab" if e.id == "bal" else None, sources=[SourceRef(url=URL, snippet=e.name)],
                            score=0.5, confidence=0.4)
               for e in ENTS.values()]
        return SearchResponse(query=q, expanded_terms=[], abstained=False, results=res)
    monkeypatch.setattr(search, "search", fake_search)


def _names(query):
    ms, msg = cases.find_matches(plain.RequestAnalysis(summary="", search_query=query))
    return {m.name for m in ms}, msg


def test_hearing_aid_maker_meets_hearing_research_only(fake_index):
    names, _ = _names(AMPLIFON)
    # in: the hearing lab and its people. out: a lab with a similar-sounding name and its head (TrimLab -> Balmer),
    # shared generic words ("clinical treatment development"), "aid" alone, and "implant" alone
    assert names == {"Hearing Research Laboratory", "Dr. Philipp Aebischer"}


def test_a_query_with_no_specific_word_finds_nobody(fake_index):
    names, msg = _names("www amplifon com")
    assert names == set() and msg == cases.NO_STRONG_MSG


def test_one_word_in_common_is_a_coincidence_unless_it_is_what_the_company_is_about(fake_index):
    assert _names("orthopaedic implant maker")[0] == set()                  # "implant" alone: cochlear or hip?
    assert _names("hip implant, hip arthroplasty")[0] == {"Prof. Hip Surgeon"}


def test_topic_words_and_support():
    words = {"hearing", "aid", "loss"}
    assert cases.topic_support("Hearing aids for HEARING LOSS", words) == words
    assert cases.specific({"aid"}, {"hearing"}) is False                     # short and alone: ambiguous
    assert cases.specific({"hearing"}, {"hearing"}) is True                  # central to the company
    assert cases.specific({"implant"}, set()) is False and cases.specific({"implant", "hip"}, set()) is True
    assert cases.central_words("hearing aid, hearing loss", {"hearing", "aid", "loss"}) == {"hearing"}


def test_document_frequencies_come_from_the_storage_interface(monkeypatch):
    """Regression: _doc_freq called index.load_bm25(), gone since the storage interface, so every request that
    reached the topic filter raised AttributeError. The real _doc_freq and find_matches run here, unstubbed."""
    monkeypatch.setattr(cases.index, "load_entities", lambda: ENTS)
    monkeypatch.setattr(cases, "_df_cache", {})
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    n, df = cases._doc_freq()
    assert n == len(ENTS)
    assert df["cochlear"] == 2 and df["hip"] == 1                     # per profile, not per occurrence
    assert "cochlear" in cases.topic_words("cochlear implant maker")

    def fake_search(q, k=10, llm_explain=True, **kw):
        res = [SearchResult(id=e.id, person_or_unit=e.name, entity_type=e.entity_type, role=None,
                            affiliation=Affiliation(unit=e.unit, institution="ARTORG"), institution="ARTORG",
                            expertise=[], projects=[], infrastructure_services=[], contact=None, why_match="close in meaning",
                            via=None, sources=[SourceRef(url=URL, snippet=e.name)], score=0.5, confidence=0.4)
               for e in ENTS.values()]
        return SearchResponse(query=q, expanded_terms=[], abstained=False, results=res)
    monkeypatch.setattr(search, "search", fake_search)
    names, _ = _names("hip implant, hip arthroplasty")
    assert names == {"Prof. Hip Surgeon"}
