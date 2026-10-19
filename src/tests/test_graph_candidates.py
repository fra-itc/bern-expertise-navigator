"""Candidates the graph brings in pass the same relevance gate as search results, on their OWN text; page-section
headings ("Ongoing Projects", "Team members") are never assets nor graph parents; one person takes one offer slot.
Offline: fake index / hashing embedder, no network, no LLM."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import cases, config, index, llm, plain, search  # noqa: E402
from navigator.rules_extract import extract_page, section_heading  # noqa: E402
from navigator.schema import Affiliation, Entity, Evidence, Page, SearchResponse, SearchResult, SourceRef  # noqa: E402
from test_search_offline import ent, fake_embed  # noqa: E402

URL = "https://www.dcberne.com/x"
CGM = ("continuous glucose monitoring sensors, glucose sensor accuracy, automated insulin delivery, "
       "glucose monitoring clinical trials, diabetes data analytics")


def _ent(i, name, etype, text, unit=None, source="dcb"):
    return Entity(id=i, entity_type=etype, name=name, unit=unit, source=source, source_label="DCB",
                  source_urls=[URL], retrieved_at="2026-10-19",
                  evidence=[Evidence(field="name", value=name, snippet=name, url=URL),
                            Evidence(field="description", value=text, snippet=text, url=URL)])


ENTS = {e.id: e for e in [
    # a heading taken for a project: its text aggregates many pages, so it matches almost any topic
    _ent("ongoing", "Ongoing Projects", "project", "Glucose sensor studies, insulin delivery and clinical data."),
    _ent("pedi", "Prof. Paediatric Endocrinologist", "person", "Adrenal steroid biology in children.", "Ongoing Projects"),
    _ent("aid", "Prof. AID Researcher", "person", "Automated insulin delivery and glucose control algorithms."),
    _ent("sim", "Dr. Similar Profile", "person", "Clinical data management for hospital registries."),
    _ent("ger", "Sensor Based Monitoring", "project", "Monitoring the movement of elderly people at home."),
    _ent("lab", "Diabetes Lab", "unit", "Closed-loop insulin delivery and continuous glucose monitoring."),
    _ent("member", "Dr. Lab Member", "person", "Statistics.", "Diabetes Lab"),
    _ent("bally_page", "Dr. med. Dr. phil. Jane Bally", "person", "Glucose sensors and insulin delivery in hospital."),
    _ent("bally_rec", "Jane Bally", "person", "Glucose monitoring and insulin delivery trials.", source="openalex"),
]}
VIA = {"pedi": "Ongoing Projects", "sim": "Prof. AID Researcher", "member": "Diabetes Lab"}


@pytest.fixture()
def fake_index(monkeypatch):
    monkeypatch.setattr(cases.index, "load_entities", lambda: ENTS)
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    monkeypatch.setattr(cases, "_doc_freq", lambda: (100, {"clinical": 40, "data": 45, "monitoring": 12}))

    def fake_search(q, k=10, llm_explain=True, **kw):
        res = [SearchResult(id=e.id, person_or_unit=e.name, entity_type=e.entity_type, role=None,
                            affiliation=Affiliation(unit=e.unit, institution="DCB"), institution="DCB",
                            expertise=[], projects=[], infrastructure_services=[], contact=None, why_match="close",
                            via=VIA.get(e.id), sources=[SourceRef(url=URL, snippet=e.name)], score=0.5, confidence=0.4)
               for e in ENTS.values() if e.id != "ongoing"]   # search itself no longer returns the heading
        return SearchResponse(query=q, expanded_terms=[], abstained=False, results=res)
    monkeypatch.setattr(search, "search", fake_search)


def _names(query=CGM):
    ms, _ = cases.find_matches(plain.RequestAnalysis(summary="", search_query=query))
    return [m.name for m in ms]


def test_graph_neighbour_is_judged_on_its_own_text_not_on_its_parents(fake_index):
    names = _names()
    # reached through "Ongoing Projects" (whose text matches) but its own text is about adrenal steroids: out
    assert "Prof. Paediatric Endocrinologist" not in names
    # reached through SIMILAR_TO from a matching person: its own text has only generic words: out
    assert "Dr. Similar Profile" not in names
    # reached through a matching lab, own text "Statistics." -> only the lab's name in its affiliation: out
    assert "Dr. Lab Member" not in names
    assert "Prof. AID Researcher" in names and "Diabetes Lab" in names


def test_the_same_person_from_a_page_and_a_publication_record_takes_one_slot(fake_index):
    names = _names()
    assert names.count("Dr. med. Dr. phil. Jane Bally") + names.count("Jane Bally") == 1
    assert names.index("Dr. med. Dr. phil. Jane Bally") >= 0          # the first-ranked record is kept


def test_dedupe_people_keeps_first_and_leaves_non_people_alone():
    ms = [cases.Match(id="a", name="Prof. Dr. José García", entity_type="person"),
          cases.Match(id="b", name="Jose Garcia", entity_type="person"),
          cases.Match(id="c", name="Monitoring", entity_type="infrastructure"),
          cases.Match(id="d", name="Monitoring", entity_type="project")]
    assert [m.id for m in cases.dedupe_people(ms)] == ["a", "c", "d"]


# ---- page-section headings ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Ongoing Projects", "Ongoing Project", "Ended Projects", "Team members",
                                  "All Researchers", "Current projects", "Projects"])
def test_section_headings(name):
    assert section_heading(name)


@pytest.mark.parametrize("name", ["Bally Lab", "Monitoring", "Sensor Based Monitoring", "Diabetes Center Berne",
                                  "SPN-005 – Pilot study on painless glucose monitoring", "Hearing Research Laboratory",
                                  None, ""])
def test_not_section_headings(name):
    assert not section_heading(name)


def test_extractor_does_not_take_team_members_heading_for_a_unit():
    page = Page(url="https://www.artorg.unibe.ch/research/hrl/team/index_eng.html", source="artorg",
                title="Team - Hearing Research Laboratory", page_type="other", fetched_at="2026-10-19",
                text="Team members\nProf. Dr. Anna Muster\nGroup Head\nanna.muster@unibe.ch\n")
    people = [e for e in extract_page(page) if e["entity_type"] == "person"]
    assert people and all((p.get("unit") or {}).get("value") != "Team members" for p in people)


@pytest.fixture()
def heading_index(tmp_path, monkeypatch):
    for name in ("BM25_PATH", "ENTITIES_PATH", "VEC_PATH", "VEC_META_PATH"):
        monkeypatch.setattr(index, name, tmp_path / name.lower())
    monkeypatch.setattr(index, "embed", fake_embed)
    monkeypatch.setattr(config.settings, "qdrant_url", "")
    monkeypatch.setattr(config.settings, "use_llm_expansion", False)
    monkeypatch.setattr(config.settings, "use_llm_explain", False)
    monkeypatch.setattr(search.llm, "available", lambda: False)
    monkeypatch.setattr(config.settings, "min_vector_score", 0.30)
    monkeypatch.setattr(config.settings, "max_per_unit", 2)
    ents = [
        ent(1, "Ongoing Projects", "unit", None, ["continuous glucose monitoring", "insulin pumps"]),
        ent(2, "Prof. Steroid Expert", "person", "Ongoing Projects", ["adrenal steroids"]),
        ent(3, "Prof. Glucose Expert", "person", "Team members", ["continuous glucose monitoring"]),
        ent(4, "Dr. Other Glucose", "person", "Team members", ["glucose monitoring sensors"]),
        ent(5, "Dr. Third Glucose", "person", "Team members", ["glucose monitoring in hospital"]),
        # unrelated profiles, so that "glucose" is a specific word of this index (not in most profiles)
        *(ent(10 + i, f"Prof. Other {i}", "person", f"Lab {i}", [topic]) for i, topic in enumerate(
            ["bone biomechanics", "hearing research", "cardiac imaging", "lung organoids", "eye surgery robots",
             "sleep and circadian rhythm", "gut microbiome", "radiotracers", "urinary tract", "epilepsy",
             "tissue engineering", "flow cytometry", "biobank", "steroid analysis", "thrombectomy devices",
             "nanorobotics"])),
    ]
    index.build(ents)
    return ents


def test_heading_entity_is_neither_a_result_nor_a_graph_parent(heading_index):
    r = search.search("continuous glucose monitoring")
    names = [x.person_or_unit for x in r.results]
    assert "Ongoing Projects" not in names
    assert "Prof. Steroid Expert" not in names                        # only reachable through the heading
    assert all(x.via != "Ongoing Projects" for x in r.results)


def test_heading_unit_is_not_an_affiliation_nor_a_shared_lab(heading_index):
    r = search.search("glucose monitoring")
    assert not r.abstained
    people = [x for x in r.results if x.entity_type == "person"]
    assert {x.person_or_unit for x in people} >= {"Prof. Glucose Expert", "Dr. Other Glucose", "Dr. Third Glucose"}
    # "Team members" is not a lab: it is not shown, and the three people are not capped as one lab (max_per_unit=2)
    assert all(x.affiliation.unit is None for x in people)


# ---- abstention: coincidences do not count as coverage ---------------------------------------------------------
def test_query_coverage_ignores_lexical_coincidences_and_index_generic_words(monkeypatch):
    profiles = [_ent(f"p{i}", f"Prof. P{i}", "person", f"Research in Bern on topic {i}.") for i in range(10)]
    profiles.append(_ent("ins", "Prof. Insulin", "person", "Best practice for insulin delivery in Bern."))
    monkeypatch.setattr(search.index, "load_entities", lambda: {e.id: e for e in profiles})
    monkeypatch.setattr(search, "_df_cache", {})
    q = "best pizza delivery in Bern"
    # "bern" is in every profile: not evidence; a lexical candidate with 2 of the 3 other words is a coincidence
    assert search.query_covered(q, sem_docs=[profiles[0]], lex_docs=[profiles[-1]]) <= 0.5
    # a lexical candidate with every specific word is evidence
    assert search.query_covered("insulin delivery", sem_docs=[profiles[0]], lex_docs=[profiles[-1]]) == 1.0
    # a paper chunk among the semantic candidates counts through its words
    assert search.query_covered("photoacoustic spectroscopy", [profiles[0], "Photoacoustic spectroscopy of skin"],
                                []) == 1.0


# ---- offer slots: people do not crowd out labs and projects -----------------------------------------------------
def test_people_and_other_assets_have_their_own_candidate_pool(monkeypatch):
    people = [_ent(f"p{i}", f"Dr. Glucose Person {i}", "person", "Glucose sensors and insulin delivery.") for i in range(45)]
    lab = _ent("lab", "Closed Loop Lab", "unit", "Closed-loop insulin delivery and glucose sensors.")
    proj_a = _ent("pa", "Diabetes Project A", "project", "Diabetes and glucose education.")
    proj_b = _ent("pb", "Glucose Analytics Project", "project", "Glucose sensor data analytics for diabetes.")
    ents = {e.id: e for e in [*people, lab, proj_a, proj_b]}
    monkeypatch.setattr(cases.index, "load_entities", lambda: ents)
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    monkeypatch.setattr(cases, "_doc_freq", lambda: (100, {}))
    score = {e.id: 1.0 - i / 100 for i, e in enumerate(ents.values())}   # every person ranks above the lab

    def fake_search(q, k=10, llm_explain=True, types=None, **kw):
        hits = [e for e in ents.values() if not types or e.entity_type in types][:k]
        res = [SearchResult(id=e.id, person_or_unit=e.name, entity_type=e.entity_type, role=None,
                            affiliation=Affiliation(unit=None, institution="DCB"), institution="DCB", expertise=[],
                            projects=[], infrastructure_services=[], contact=None, why_match="close", via=None,
                            sources=[SourceRef(url=URL, snippet=e.name)], score=score[e.id], confidence=0.4)
               for e in hits]
        return SearchResponse(query=q, expanded_terms=[], abstained=False, results=res)
    monkeypatch.setattr(search, "search", fake_search)
    kept, _ = cases.find_matches(plain.RequestAnalysis(summary="", search_query="glucose sensors, insulin delivery, "
                                                                                  "diabetes analytics"))
    names = [m.name for m in kept]
    assert "Closed Loop Lab" in names                                   # rank 46 in one shared list of 40
    assert "Closed Loop Lab" in [m.name for m in cases.pick_assets(kept)]
