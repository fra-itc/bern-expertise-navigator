"""Broad search: places and medtech topics read from free text in EN / DE / FR / IT / Romansh."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator.understand import understand  # noqa: E402

CASES = [
    # text, country, canton, city, area, niche, words that must remain to be searched
    ("glucose company in Milan", "Italy", "", "Milan", "diabetes", "glucose", ["glucose"]),
    ("azienda di sensori di glucosio a Milano", "Italy", "", "Milan", "diabetes", "glucose", ["sensori", "glucosio"]),
    ("Glukosesensor-Firma aus München", "Germany", "", "Munich", "diabetes", "glucose", ["glukosesensor"]),
    ("entreprise de capteurs de glucose à Lyon", "France", "", "Lyon", "diabetes", "glucose", ["capteurs", "glucose"]),
    ("Ina interpresa da glucosa a Turitg", "Switzerland", "Zurich", "Zurich", "diabetes", "glucose", ["glucosa"]),
    ("robots for neurosurgery from Geneva", "Switzerland", "Geneva", "Geneva", "robotics", "neuro", ["robots", "neurosurgery"]),
    ("Implantat-Hersteller im Kanton Waadt", "Switzerland", "Vaud", "", "ortho", "implants", ["implantat"]),
    ("fabricant d'implants à Lausanne", "Switzerland", "Vaud", "Lausanne", "ortho", "implants", ["implants"]),
    ("azienda di impianti cocleari in Ticino", "Switzerland", "Ticino", "", "neuro", "hearing", ["impianti", "cocleari"]),
    ("cochlear implant startup", "", "", "", "neuro", "hearing", ["cochlear", "implant"]),
    ("German insulin pump maker", "Germany", "", "", "diabetes", "insulin", ["insulin", "pump"]),
    ("Herzklappen Firma in Wien", "Austria", "", "Vienna", "cardio", "valves", ["herzklappen"]),
    ("interpresa da robotica a Cuira", "Switzerland", "Graubünden", "Chur", "robotics", "", ["robotica"]),
]


@pytest.mark.parametrize("text,country,canton,city,area,niche,rest", CASES)
def test_understands_five_languages(text, country, canton, city, area, niche, rest):
    u = understand(text)
    assert (u.country, u.canton, u.city) == (country, canton, city), u
    assert (u.area, u.niche) == (area, niche), u
    for w in rest:
        assert w in u.rest.split(), (w, u.rest)
    for place in filter(None, [city, country, canton]):
        assert place.lower() not in u.rest                      # place words are not searched in Bern
    assert not {"company", "firma", "azienda", "entreprise", "interpresa"} & set(u.rest.split())


def test_every_detection_says_which_words_triggered_it():
    u = understand("glucose company in Milan")
    by = {d.kind: d for d in u.detections}
    assert by["city"].matched == "Milan" and by["niche"].matched == "glucose" and by["country"].value == "Italy"


def test_everyday_words_are_not_places():
    assert understand("we take the Zug to Bern").city == "Bern"       # "Zug" (train) without "in/aus" is no place
    assert understand("eine Firma aus Zug").canton == "Zug"
    assert understand("a nice glucose sensor").country == ""          # "nice" is not Nice (France)
    assert understand("glucose sensor").country == ""


def test_nothing_recognised_keeps_the_text():
    u = understand("partner for clinical validation")
    assert (u.country, u.area) == ("", "") and "clinical" in u.rest and "validation" in u.rest


def test_keyword_niches_exist_in_the_medtech_areas():
    import yaml
    root = Path(__file__).resolve().parents[1] / "config"
    areas = {a["id"]: {n["id"] for n in a["niches"]} for a in yaml.safe_load((root / "medtech_areas.yaml").read_text())["areas"]}
    kw = yaml.safe_load((root / "medtech_keywords.yaml").read_text())["areas"]
    for area, a in kw.items():
        assert area in areas, area
        assert set(a.get("niches", {})) <= areas[area], (area, set(a.get("niches", {})) - areas[area])
