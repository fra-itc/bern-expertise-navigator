"""Deterministic (no-LLM) extractor on page shapes taken from the real sites; output must pass the verifier."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import extract  # noqa: E402
from navigator.rules_extract import name_like, role_like  # noqa: E402
from navigator.schema import Entity, Evidence, Page  # noqa: E402

TEAM = Page(url="https://www.dcberne.com/en/team/", source="dcb", title="Team - Diabetes Center Berne", page_type="person",
            fetched_at="2026-10-18", text="""Team
DCB Team
Core Team Operations
CFO/COO/HRM
Lorenz Burkhalter
Mail
Associated Research Groups
Sensing & Monitoring Lab
For more information, visit
samlab.org
Tenure track professor
Prof. Dr. phil. Lilian Witthauer
Mail
PhD student
Camilo Mendez Schneider
Mail
PrecisionLab
Assistant professor
Prof. José Garcia-Tirado
Mail""")

PROFILE = Page(url="https://www.artorg.unibe.ch/research/aihn/group_members/persons/dr_debeire_kevin/index_eng.html",
               source="artorg", title="Research: Dr. Kevin Debeire - ARTORG", page_type="person", fetched_at="2026-10-18",
               text="""Dr. Kevin Debeire
Postdoctoral Researcher
University of Bern, ARTORG Center for Biomedical Engineering Research, AI in Health and Nutrition
- kevin.debeire@unibe.ch
Curriculum Vitae
Kevin Debeire is a postdoctoral researcher in AI in Health and Nutrition at the ARTORG Center since 2026. He focuses on developing and applying causal discovery methods in healthcare.""")

UNIT = Page(url="https://www.artorg.unibe.ch/research/mia/index_eng.html", source="artorg", page_type="unit",
            title="Research: Medical Image Analysis - ARTORG", fetched_at="2026-10-18", text="""Medical Image Analysis
Contact
Prof. Dr. Mauricio Reyes
- Phone
The Medical Image Analysis (MIA) group develops advanced AI-based image analysis technologies to quantify and monitor diseases.
Our core expertise lies in multimodal image segmentation and longitudinal analysis for brain tumours.""")

PROJECT = Page(url="https://www.dcberne.com/en/project/the-moonwalk-project/", source="dcb", page_type="project",
               title="The Moonwalk Project - Diabetes Center Berne", fetched_at="2026-10-18", text="""The Moonwalk Project
The Moonwalk project aims to investigate the possible association between glucose levels and motion patterns during sleep.
Project team: Prof. Lilian Witthauer, Prof. Markus Laimer, QUMEA AG""")


def run(page):
    rejected = []
    ents = {e.name.value: e for e in extract.extract_page(page, rejected, extractor="rules")}
    assert rejected == []  # rules only cut values out of the page -> nothing to reject
    return ents


def test_heuristics():
    assert name_like("Prof. Dr. phil. Lilian Witthauer") and name_like("José Garcia-Tirado")
    assert not name_like("Computational Bioengineering") and not name_like("Group Members")
    assert not name_like("Chief Physician") and role_like("Tenure track professor")


def test_directory_cards_with_lab_headings():
    ents = run(TEAM)
    w = ents["Prof. Dr. phil. Lilian Witthauer"]
    assert w.role.value == "Tenure track professor" and w.unit.value == "Sensing & Monitoring Lab"
    assert ents["Prof. José Garcia-Tirado"].unit.value == "PrecisionLab"  # CamelCase lab name
    assert ents["Lorenz Burkhalter"].unit.value == "Core Team Operations"
    assert "samlab.org" not in {e.unit.value for e in ents.values() if e.unit}


def test_profile_page():
    [p] = run(PROFILE).values()
    assert p.role.value == "Postdoctoral Researcher"
    assert p.unit.value == "AI in Health and Nutrition"
    assert p.email.value == "kevin.debeire@unibe.ch"
    assert any("causal discovery" in c.value for c in p.expertise)


def test_unit_page_contact_is_linked_person():
    ents = run(UNIT)
    unit = ents["Medical Image Analysis"]
    assert unit.entity_type == "unit" and any("segmentation" in c.value for c in unit.expertise)
    reyes = ents["Prof. Dr. Mauricio Reyes"]
    assert reyes.entity_type == "person" and reyes.unit.value == "Medical Image Analysis"


def test_project_team_line():
    ents = run(PROJECT)
    assert ents["The Moonwalk Project"].entity_type == "project"
    laimer = ents["Prof. Markus Laimer"]
    assert [c.value for c in laimer.projects] == ["The Moonwalk Project"]
    assert "QUMEA AG" not in ents


def test_site_structure_links_members_to_their_unit():
    def ent(i, name, etype, url):
        return Entity(id=i, entity_type=etype, name=name, source="artorg", source_label="ARTORG", source_urls=[url],
                      evidence=[Evidence(field="name", value=name, snippet=name, url=url)], retrieved_at="2026")
    unit = ent("u", "AI in Health and Nutrition", "unit", "https://www.artorg.unibe.ch/research/aihn/index_eng.html")
    sub = ent("s", "Intelligent Nutrition", "unit",
              "https://www.artorg.unibe.ch/research/aihn/research_activities/intelligent_nutrition/index_eng.html")
    person = ent("p", "Rafael Morand", "person", "https://www.artorg.unibe.ch/research/aihn/group_members/index_eng.html")
    extract.link_site_structure([unit, sub, person])
    assert person.unit == "AI in Health and Nutrition"
    assert any(ev.field == "unit" and ev.url == unit.source_urls[0] for ev in person.evidence)  # cited on the unit page
    assert sub.entity_type == "project" and "Intelligent Nutrition" in unit.projects


def _page(url, title, text, ptype):
    return Page(url=url, source="unibe_web", title=title, page_type=ptype, fetched_at="2026-10-18", text=text)


def test_directory_profile_with_surname_first_heading_is_a_person():
    # UniBE staff directories head profiles "Surname, Firstname" or "Surname Firstname, PhD"; the page type is "unit"
    dort = run(_page("https://dcr.unibe.ch/about_us/personen_all_dcr_staff/dort_jacqueline/index_eng.html",
                     "Dort, Jacqueline", "Dort, Jacqueline\nResearch Assistant\nDCR / MDS\nField of work\n"
                     "Researcher in medical data science with a focus on Large Language Models for drug approval data", "unit"))
    assert dort["Jacqueline Dort"].entity_type == "person" and dort["Jacqueline Dort"].role.value == "Research Assistant"
    ballif = run(_page("https://www.ispm.unibe.ch/about_us/staff/ballif_marie/index_eng.html", "Ballif Marie, PhD, MPH",
                       "Ballif Marie, PhD, MPH\nResearch Collaborator\nResearch - HIV, Hepatitis and Tuberculosis", "unit"))
    assert "Ballif Marie" in ballif and ballif["Ballif Marie"].entity_type == "person" and "Ballif Marie, PhD, MPH" not in ballif
    # same shape without a role line is not a person
    place = run(_page("https://www.dbmr.unibe.ch/about_us/how_to_find_us/index_eng.html", "Bern, Switzerland",
                      "Bern, Switzerland\nMurtenstrasse 35\n3008 Bern", "unit"))
    assert not any(e.entity_type == "person" for e in place.values())


def test_site_administration_headings_are_not_entities():
    for title in ["Disclaimer", "Booking & Rates", "Johanna Dürmüller-Bol DBMR Research Award", "Terms of Use",
                  "Human Resources", "How to find us", "+41 31 632 41 14 (clinic)", "Research Groups and Themes",
                  "Projects: 2nd round", "BORIS Portal Publications"]:
        ents = run(_page("https://www.dbmr.unibe.ch/services/x/index_eng.html", title,
                         f"{title}\nPlease contact the office for details about this page.", "infrastructure"))
        assert title not in ents, title
    kept = run(_page("https://www.dbmr.unibe.ch/services/core_facilities/fccs/index_eng.html",
                     "Flow Cytometry and Cell Sorting (FCCS)",
                     "Flow Cytometry and Cell Sorting (FCCS)\nThe FCCS offers cell sorting and analysis on six cytometers.",
                     "infrastructure"))
    assert kept["Flow Cytometry and Cell Sorting (FCCS)"].entity_type == "infrastructure"
