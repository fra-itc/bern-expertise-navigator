"""OpenAlex source with a fake API: affiliation-verified authors, record pages, verified entities, merge."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import extract, openalex  # noqa: E402
from navigator.config import Source  # noqa: E402
from navigator.schema import Entity, Evidence  # noqa: E402

UNIBE = "https://openalex.org/I118564535"
DEPT = ("Department of Diabetes, Endocrinology, Nutritional Medicine and Metabolism, Inselspital, "
        "Bern University Hospital, University of Bern, Bern, Switzerland")


def work(i, year, authors):
    return {"id": f"https://openalex.org/W{i}", "doi": f"https://doi.org/10.1/w{i}", "title": f"Glucose sensing study {i}",
            "publication_year": year, "primary_topic": {"display_name": "Diabetes Management and Technology"},
            "topics": [{"display_name": "Continuous Glucose Monitoring"}], "authorships": authors}


def author(aid, name, bern=True, raw=DEPT):
    return {"author": {"id": f"https://openalex.org/{aid}", "display_name": name},
            "institutions": [{"id": UNIBE if bern else "https://openalex.org/I999"}],
            "raw_affiliation_strings": [raw] if bern else ["University of Limerick, Ireland"]}


def fake_get(client, path, params):
    if path == "/works":
        res = [work(i, 2024 - i % 2, [author("A1", "Lilian Witthauer"), author("A2", "Other Person", bern=False)])
               for i in range(4)] + [work(9, 2023, [author("A3", "Rare Author")])]
        return {"results": res, "meta": {"next_cursor": None}}
    return {"results": [{"id": "https://openalex.org/A1", "display_name": "Lilian Witthauer",
                         "orcid": "https://orcid.org/0000-0000-0000-0001"}]}


def src(tmp):
    return Source(name="unibe", label="University of Bern", domains=[], seeds=[], max_pages=0, max_depth=0,
                  delay_seconds=0, user_agent="test", priority_keywords=[], skip_keywords=[], type="openalex",
                  options={"institution": "I118564535", "from_date": "2023-01-01", "min_works": 3, "subfields": [2712]})


def test_fetch_keeps_only_authors_verified_by_their_own_affiliation(tmp_path, monkeypatch):
    monkeypatch.setattr(openalex, "_get", fake_get)
    monkeypatch.setattr(openalex, "DATA_DIR", tmp_path)
    pages = openalex.fetch(src(tmp_path))
    assert [p.title for p in pages] == ["Lilian Witthauer"]      # A2 never signed as UniBE; A3 has only 1 paper
    text = pages[0].text
    assert "ORCID: https://orcid.org/0000-0000-0000-0001" in text and f"Department: {DEPT}" in text
    assert "Research topic: Continuous Glucose Monitoring" in text and "doi:10.1/w0" in text
    assert pages[0].url == "https://openalex.org/A1" and (tmp_path / "pages" / "unibe.jsonl").exists()


def test_record_page_becomes_a_verified_person(tmp_path, monkeypatch):
    monkeypatch.setattr(openalex, "_get", fake_get)
    monkeypatch.setattr(openalex, "DATA_DIR", tmp_path)
    [page] = openalex.fetch(src(tmp_path))
    ext, pubs = openalex.to_extracted(page)
    rejected = []
    v = extract.verify(ext, page, rejected)
    assert rejected == [] and v.unit.value == "Department of Diabetes, Endocrinology, Nutritional Medicine and Metabolism"
    assert v.institute.value == "University of Bern"
    assert "Continuous Glucose Monitoring" in [c.value for c in v.expertise]
    ev = openalex.publication_evidence(page, pubs)
    assert ev and all(e.snippet in page.text and e.url == page.url for e in ev)


def test_unit_from_affiliation_text():
    assert openalex._unit("ARTORG Center for Biomedical Engineering Research, University of Bern, Bern, Switzerland") \
        == "ARTORG Center for Biomedical Engineering Research"
    assert openalex._unit("University of Bern, Bern, Switzerland") == ""
    assert openalex._unit("Department of Periodontology University of Bern  Bern Switzerland") == "Department of Periodontology"


def test_researcher_on_a_website_and_in_openalex_is_one_entity():
    def ent(i, name, source, ev):
        return Entity(id=i, entity_type="person", name=name, role="Professor", source=source, source_label=source,
                      source_urls=[f"https://{source}/{i}"], evidence=ev, retrieved_at="2026")
    web = ent("w", "Prof. Dr. phil. Lilian Witthauer", "dcb", [Evidence(field="name", value="x", snippet="x", url="https://dcb/w")])
    oa = ent("o", "Lilian Witthauer", "unibe", [Evidence(field="publication", value="p", snippet="Publication: p", url="https://openalex.org/A1")])
    oa.expertise, oa.source_urls = ["Continuous Glucose Monitoring"], ["https://openalex.org/A1"]
    out = openalex.attach_to_web_profiles([web, oa], {"unibe"})
    assert [e.id for e in out] == ["w"] and out[0].role == "Professor"
    assert "Continuous Glucose Monitoring" in out[0].expertise and "https://openalex.org/A1" in out[0].source_urls
    assert any(e.field == "publication" for e in out[0].evidence)


def test_name_variants_merge_but_homonyms_do_not():
    def ent(i, name, source):
        return Entity(id=i, entity_type="person", name=name, source=source, source_label=source, source_urls=[f"https://{i}"],
                      evidence=[Evidence(field="name", value=name, snippet=name, url=f"https://{i}")], retrieved_at="2026")
    web = [ent("w1", "Prof. Dr. phil. Lilian Witthauer", "dcb"), ent("w2", "Prof. Dr. Stavroula Mougiakakou", "artorg"),
           ent("w3", "Anna Meier", "artorg"), ent("w4", "Andreas Meier", "dcb")]
    oa = [ent("o1", "L. Witthauer", "unibe"), ent("o2", "Stavroula Georgia Mougiakakou", "unibe"), ent("o3", "A. Meier", "unibe")]
    out = {e.id for e in openalex.attach_to_web_profiles(web + oa, {"unibe"})}
    assert "o1" not in out and "o2" not in out           # merged into the website profiles
    assert "o3" in out                                    # "A. Meier" could be Anna or Andreas: kept separate
