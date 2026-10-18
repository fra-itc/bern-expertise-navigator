"""Broad search: understand a free-text company search in English, German, French, Italian or Romansh.

    "glucose company in Milan"              -> Milan, Italy · diabetes › glucose · search "glucose"
    "Glukosesensor-Firma aus München"       -> Munich, Germany · diabetes › glucose
    "entreprise d'implants à Lausanne"      -> Lausanne, Vaud, Switzerland · ortho › implants
    "azienda di robotica a Milano"          -> Milan, Italy · robotics
    "interpresa da glucosa a Turitg"        -> Zurich, Switzerland · diabetes › glucose

Deterministic and auditable: lists live in config/places.yaml and config/medtech_keywords.yaml, so the team
can add a city or a word without code. Nothing here guesses: a place or topic is set only when one of its
listed names appears in the text, and every detection reports the words that triggered it.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import yaml
from pydantic import BaseModel

from .config import CONFIG_DIR

PLACES = CONFIG_DIR / "places.yaml"
KEYWORDS = CONFIG_DIR / "medtech_keywords.yaml"

# words that introduce a place: "in Milan", "aus München", "à Lyon", "a Milano", "da Cuira", "en Svizra"
_PREP = {"in", "from", "near", "at", "based", "aus", "bei", "im", "nahe", "von", "a", "à", "de", "du", "en", "pres",
         "près", "da", "di", "presso", "vicino", "nel", "nella", "ad", "dal", "dalla"}
# "company" and friends carry no search meaning
_GENERIC = {"medtech", "medtec", "medizintechnik", "company", "companies", "firm", "firms", "startup", "start-up", "startups", "business", "manufacturer",
            "maker", "makers", "producer", "supplier", "firma", "firmen", "unternehmen", "hersteller", "anbieter",
            "entreprise", "entreprises", "société", "societe", "fabricant", "start-up", "azienda", "aziende",
            "impresa", "imprese", "società", "ditta", "produttore", "interpresa", "interpresas", "fatschenta",
            "looking", "searching", "search", "find", "for", "the", "a", "an", "of", "with", "and", "that", "who",
            "eine", "ein", "einer", "der", "die", "das", "für", "mit", "und", "une", "un", "le", "la", "les", "des",
            "pour", "avec", "et", "qui", "una", "uno", "il", "lo", "gli", "per", "con", "e", "che", "ina", "in",
            "da", "per", "cun", "e", "ch", "de", "di", "du", "aus", "von", "à", "en", "im", "nel", "nella"}


def norm(s: str) -> str:
    """lower case, no accents; hyphens, apostrophes and other punctuation become spaces, so
    "Glukosesensor-Firma" -> "glukosesensor firma", "d'implants" -> "d implants" (names and keywords are
    normalised the same way, so "Basel-Stadt" or "3D-Druck" still match)."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    s = s.replace("ß", "ss")
    s = re.sub(r"[^\w ]+|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# compare like with like: the filler lists are written with accents, the text is matched without them
_PREP = {norm(w) for w in _PREP}
_GENERIC = {x for w in _GENERIC for x in norm(w).split()}


class Detection(BaseModel):
    kind: str          # city | canton | country | area | niche
    value: str         # canonical value (e.g. "Milan", "Italy", "diabetes/glucose")
    matched: str       # the words in the text that triggered it


class Understood(BaseModel):
    country: str = ""
    canton: str = ""
    city: str = ""
    area: str = ""
    niche: str = ""
    rest: str = ""                 # what is left to search for once places and filler words are removed
    detections: list[Detection] = []


@lru_cache(maxsize=4)
def _lists(_mt: tuple) -> tuple[list[dict], list[tuple]]:
    places = yaml.safe_load(PLACES.read_text()) if PLACES.exists() else {}
    entries = []  # (kind, value, name_norm, strict, country, canton)
    for c in places.get("countries", []):
        entries += [("country", c["name"], norm(n), c.get("strict", False), c["name"], "") for n in c["names"]]
    for c in places.get("cantons", []):
        entries += [("canton", c["name"], norm(n), c.get("strict", False), "Switzerland", c["name"]) for n in c["names"]]
    for c in places.get("cities", []):
        entries += [("city", c["name"], norm(n), c.get("strict", False), c["country"], c.get("canton", "")) for n in c["names"]]
    entries.sort(key=lambda e: -len(e[2]))           # longest names first ("new york" before "york")
    kw = yaml.safe_load(KEYWORDS.read_text()) if KEYWORDS.exists() else {}
    topics = []  # (area, niche, keyword_norm)
    for area, a in (kw.get("areas") or {}).items():
        topics += [(area, "", norm(k)) for k in a.get("keywords", [])]
        for niche, langs in (a.get("niches") or {}).items():
            for words in (langs or {}).values():
                topics += [(area, niche, norm(k)) for k in (words or [])]
    return entries, topics


def _mtimes() -> tuple:
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in (PLACES, KEYWORDS))


def _find(name: str, text: str, prefix: bool) -> list[re.Match]:
    tail = "" if prefix else r"(?![\w])"
    return list(re.finditer(rf"(?<![\w]){re.escape(name)}{tail}", text))


def understand(text: str) -> Understood:
    entries, topics = _lists(_mtimes())
    t = norm(text)
    u = Understood()
    used: list[tuple[int, int]] = []           # character spans already claimed by a place

    def free(m: re.Match) -> bool:
        return all(m.end() <= a or m.start() >= b for a, b in used)

    def after_prep(m: re.Match) -> bool:
        before = t[:m.start()].split()
        return bool(before) and before[-1] in _PREP

    # ---- places: cities > cantons > countries; a city also fixes its country (and canton in Switzerland)
    found: dict[str, list] = {"city": [], "canton": [], "country": []}
    for kind, value, name, strict, country, canton in entries:
        for m in _find(name, t, prefix=False):
            if not free(m) or (strict and not after_prep(m)):
                continue
            used.append((m.start(), m.end()))
            found[kind].append((m.start(), value, country, canton, text_slice(text, t, m)))
    for kind in ("city", "canton", "country"):
        found[kind].sort()
    # several countries? prefer the one introduced by an origin/location preposition, else the first mentioned
    if found["city"]:
        _, city, country, canton, words = found["city"][0]
        u.city, u.country, u.canton = city, country, canton
        u.detections.append(Detection(kind="city", value=city, matched=words))
    if found["canton"] and not u.canton:
        _, canton, _, _, words = found["canton"][0]
        u.canton, u.country = canton, "Switzerland"
        u.detections.append(Detection(kind="canton", value=canton, matched=words))
    if found["country"] and not u.country:
        _, country, _, _, words = found["country"][0]
        u.country = country
        u.detections.append(Detection(kind="country", value=country, matched=words))
    if u.country and not any(d.kind == "country" for d in u.detections):
        u.detections.append(Detection(kind="country", value=u.country, matched=""))

    # ---- topic: the niche with most keyword hits; area-only words count for the area
    score: dict[tuple[str, str], list[str]] = {}
    for area, niche, kw in topics:
        hits = [m for m in _find(kw, t, prefix=len(kw) >= 5) if free(m)]
        if hits:
            score.setdefault((area, niche), []).append(kw)
    if score:
        niches = {k: v for k, v in score.items() if k[1]}
        if niches:
            (area, niche), kws = max(niches.items(), key=lambda kv: (len(kv[1]), max(len(x) for x in kv[1])))
            u.area, u.niche = area, niche
            u.detections.append(Detection(kind="niche", value=f"{area}/{niche}", matched=", ".join(kws)))
        else:
            (area, _), kws = max(score.items(), key=lambda kv: len(kv[1]))
            u.area = area
            u.detections.append(Detection(kind="area", value=area, matched=", ".join(kws)))

    # ---- what is left to search: drop place words (with their preposition) and filler words
    keep = []
    for m in re.finditer(r"\S+", t):
        if not free(m):
            continue
        keep.append(m.group(0))
    while keep and keep[-1] in _PREP:          # "glucose company in" -> drop dangling "in"
        keep.pop()
    u.rest = " ".join(w for w in keep if len(w) > 1 and w not in _GENERIC and w not in _PREP).strip()
    return u


def topic_keywords(area: str, niche: str = "") -> list[str]:
    """The keywords of an area (and its niche) in every language, normalised: "glucose", "glukose", "glucosio"…"""
    _, topics = _lists(_mtimes())
    return list(dict.fromkeys(kw for a, n, kw in topics if a == area and (not n or n == niche)))


def place_names(value: str) -> list[str]:
    """Every name of a city, canton or country, normalised: "Milan" -> milan, milano, mailand…"""
    entries, _ = _lists(_mtimes())
    return list(dict.fromkeys(name for _, v, name, *_ in entries if v == value))


def text_slice(original: str, normed: str, m: re.Match) -> str:
    """The matched words as the user typed them (best effort; falls back to the normalised form)."""
    words = normed[m.start():m.end()].split()
    pattern = r"[\W_]*".join(re.escape(w) for w in words)
    hit = re.search(pattern, norm_keep_case(original), flags=re.I)
    return original[hit.start():hit.end()] if hit else normed[m.start():m.end()]


def norm_keep_case(s: str) -> str:
    """Accent-stripped but same length as `s`, so positions map back to the original text."""
    return "".join((unicodedata.normalize("NFKD", c)[0] if c.strip() else c) for c in s)
