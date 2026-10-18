"""Archetypes of Bern's medtech assets: what Bern can offer a company, in the canton's own categories.

The 19 archetypes come from the team's inventory ("archetipi di entità"). The index stores four
coarse entity types (person, unit, project, infrastructure); `classify` maps each entity to one
archetype with transparent rules over its role, email domain, name and description. Archetypes
the index does not hold yet (instruments, funding, events…) are listed so that their tab appears
as soon as such entities are indexed.
"""
from __future__ import annotations

import re

# (id, number in the inventory, group, labels)
ARCHETYPES: list[dict] = [
    {"id": "expert", "n": 1, "group": "people",
     "label": {"en": "Experts & PIs", "de": "Expert:innen & Gruppenleitungen", "fr": "Experts & responsables"}},
    {"id": "clinician", "n": 2, "group": "people",
     "label": {"en": "Clinician-scientists", "de": "Klinische Forschende", "fr": "Cliniciens-chercheurs"}},
    {"id": "workforce", "n": 3, "group": "people",
     "label": {"en": "Research workforce", "de": "Forschungspersonal", "fr": "Personnel de recherche"}},
    {"id": "specialist", "n": 4, "group": "people",
     "label": {"en": "Technical & operational specialists", "de": "Technische & operative Fachleute",
               "fr": "Spécialistes techniques & opérationnels"}},
    {"id": "lived", "n": 5, "group": "people",
     "label": {"en": "Lived-experience experts", "de": "Erfahrungsexpert:innen", "fr": "Patients experts"}},
    {"id": "unit", "n": 6, "group": "organisations",
     "label": {"en": "Research units", "de": "Forschungseinheiten", "fr": "Unités de recherche"}},
    {"id": "hub", "n": 7, "group": "organisations",
     "label": {"en": "Hub institutions", "de": "Zentrale Institutionen", "fr": "Institutions pivots"}},
    {"id": "facility", "n": 8, "group": "infrastructure",
     "label": {"en": "Core facilities", "de": "Core Facilities", "fr": "Plateformes"}},
    {"id": "instrument", "n": 9, "group": "infrastructure",
     "label": {"en": "Instruments", "de": "Geräte", "fr": "Instruments"}},
    {"id": "service", "n": 10, "group": "infrastructure",
     "label": {"en": "Services", "de": "Dienstleistungen", "fr": "Services"}},
    {"id": "digital", "n": 11, "group": "infrastructure",
     "label": {"en": "Digital assets", "de": "Digitale Ressourcen", "fr": "Ressources numériques"}},
    {"id": "project", "n": 12, "group": "research",
     "label": {"en": "Research lines & projects", "de": "Forschungslinien & Projekte", "fr": "Axes & projets de recherche"}},
    {"id": "study", "n": 13, "group": "research",
     "label": {"en": "Clinical studies", "de": "Klinische Studien", "fr": "Études cliniques"}},
    {"id": "technology", "n": 14, "group": "research",
     "label": {"en": "Technology & IP", "de": "Technologie & IP", "fr": "Technologies & PI"}},
    {"id": "company", "n": 15, "group": "ecosystem",
     "label": {"en": "Spin-offs & start-ups", "de": "Spin-offs & Start-ups", "fr": "Spin-offs & start-ups"}},
    {"id": "funding", "n": 16, "group": "ecosystem",
     "label": {"en": "Funding instruments", "de": "Förderinstrumente", "fr": "Instruments de financement"}},
    {"id": "programme", "n": 17, "group": "ecosystem",
     "label": {"en": "Programmes & events", "de": "Programme & Anlässe", "fr": "Programmes & événements"}},
    {"id": "proof", "n": 18, "group": "ecosystem",
     "label": {"en": "Proof points", "de": "Belege", "fr": "Preuves"}},
    {"id": "competence", "n": 19, "group": "ecosystem",
     "label": {"en": "Competences", "de": "Kompetenzen", "fr": "Compétences"}},
]
ORDER = {a["id"]: a["n"] for a in ARCHETYPES}
_FALLBACK = {"person": "workforce", "unit": "unit", "project": "project", "infrastructure": "facility"}

_RX = lambda p: re.compile(p, re.I)  # noqa: E731
_LIVED = _RX(r"lived[- ]experience|patient (expert|partner|representative)|betroffene")
_CLINICAL_MAIL = ("insel.ch", "luks.ch", "spitalbern.ch", "lindenhofgruppe.ch", "hin.ch")
_CLINICIAN = _RX(r"physician|chef[aä]rzt|oberarzt|oberärztin|leitende[rn]? [aä]rzt|consultant|clinical (group head|director)|"
                 r"endocrinologist|surgeon|chirurg|clinician")
_LEARNER = _RX(r"student|candidate|intern|apprentice|master|bachelor|doctoral|phd\b(?! *$)")
_SPECIALIST = _RX(r"engineer|technician|manager|coordinator|regulatory|quality|data|statistic|nurse|developer|werkstatt|"
                  r"polymechanik|administration|communication|officer|finance|\bhr\b|cfo|coo\b|ceo\b|operations|relation|"
                  r"entrepreneur|support|strategy|clinical research|services|programmer|designer|lab manager")
# leads of operational teams (workshop, regulatory, central services…) are specialists, not research PIs
_OPS = _RX(r"regulatory|quality|central services|facility|werkstatt|workshop|communication|finance|\bhr\b|operations|"
           r"administration|lab manager|r&d manager|relation|partnerships")
_LEAD = _RX(r"\bprof|group head|head of|\bhead\b|group leader|team leader|director|principal investigator|\bpi\b|dozent|chair")
_HUB = _RX(r"^(university of bern|universität bern|unibe|inselspital|insel gruppe|bern university hospital|sitem[- ]insel|"
           r"udem|bfh|bern university of applied sciences|csem)\b|competence cent(er|re)|foundation|stiftung|network")
_TECH = _RX(r"technology transfer|unitectra|patent|licen[cs]|intellectual property|\bip\b")
_COMPANY = _RX(r"spin-?off|start-?up|\bgmbh\b|\bag\b$|\bltd\b|\binc\b|\bsa\b$")
_DIGITAL = _RX(r"database|software|platform|web application|\bapp\b|redcap|knowledge graph|dataset|registry|\btool\b|"
               r"algorithm|\bai model")
_INSTRUMENT = _RX(r"printer|printing system|scanner|microscop|µ-?ct|micro-?ct|\bct\b|\bmri\b|bioprinter|confocal|robot|"
                  r"instrument|\bdevice\b|machine|\bmts\b|hr-pqct|spectrometer")
_SERVICE = _RX(r"testing|service|computation|simulation|consult|prototyping|analysis|analytics|support|training|catalog")
_STUDY = _RX(r"\bstudy\b|\btrial\b|\bpilot\b|cohort|\b[A-Z]{2,}[- ]?\d{2,}\b")
_STUDY_TEXT = _RX(r"clinical (trial|study|investigation)|randomi[sz]ed|participants|enrol")
_FUNDING = _RX(r"\bsnsf\b|\bsnf\b|innosuisse|\berc\b|bridge|ambizione|grant|fellowship|funding|förder")
_PROGRAMME = _RX(r"bootcamp|start-?up night|day of innovation|seminar|programme|program\b|event|workshop series|accelerator")


def classify(entity_type: str, name: str = "", role: str | None = "", email: str | None = "", text: str | None = "") -> str:
    name, role, email, text = name or "", role or "", (email or "").lower(), (text or "")[:400]
    if entity_type == "person":
        who = f"{role} {name}"
        if _LIVED.search(f"{who} {text}"):
            return "lived"
        learner = _LEARNER.search(role) and not _LEAD.search(role)
        if not learner and (email.endswith(_CLINICAL_MAIL) or _CLINICIAN.search(role)):
            return "clinician"
        if _LEAD.search(who) and not (_OPS.search(role) and not _RX(r"\bprof").search(who)):
            return "expert"
        if not learner and _SPECIALIST.search(role):
            return "specialist"
        return "workforce"
    if entity_type == "unit":
        return "hub" if _HUB.search(name) else "unit"
    if entity_type == "infrastructure":
        if _RX(r"facility|core\b|\blab\b|laborator").search(name):
            return "facility"
        for aid, rx in (("technology", _TECH), ("company", _COMPANY), ("hub", _HUB), ("funding", _FUNDING),
                        ("programme", _PROGRAMME), ("digital", _DIGITAL), ("instrument", _INSTRUMENT),
                        ("service", _SERVICE)):
            if rx.search(name) or (aid in ("digital", "service") and rx.search(text[:160])):
                return aid
        return "facility"
    if entity_type == "project":
        if _TECH.search(name):
            return "technology"
        if (_STUDY.search(name) and not _RX(r"thesis").search(name)) or _STUDY_TEXT.search(text):
            return "study"
        return "project"
    return _FALLBACK.get(entity_type, "project")
