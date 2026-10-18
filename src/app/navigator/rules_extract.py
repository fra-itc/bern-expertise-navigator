"""Deterministic extraction baseline (no LLM).

Used when no Apertus endpoint is reachable (offline demo, CI) and as the baseline that shows
what Apertus adds (`make extract EXTRACTOR=rules` vs `apertus`). It only reads page structure
that is common across research websites; no per-site code:

  * profile header:      <Name> / <Role> / <Affiliation, comma separated>
  * directory cards:     "Name / Titel" <Name> "Funktion" <Role>,  or  <Role> <Name>
  * contact blocks:      "Contact" <Name>  on a unit / facility page
  * team lines:          "Project team: Prof. A, Dr. B"
  * research sentences:  "... focuses on X", "expertise lies in X", "develops X", ...

Every value is cut from the page text and carries the verbatim lines it came from, so the
normal snippet verifier (extract.verify) accepts or rejects it exactly like LLM output.
"""
from __future__ import annotations

import re

from .schema import Cited, ExtractedEntity, Page

_TITLE_TOK = {"prof", "prof.", "dr", "dr.", "pd", "phil.", "med.", "nat.", "rer.", "dent.", "vet.", "phd", "msc",
              "dipl.", "ing.", "em.", "dr.-ing.", "md", "ph.d.", "mba", "bsc", "ma"}
_PARTICLES = {"de", "da", "di", "del", "della", "van", "von", "der", "den", "la", "le", "y", "dos", "du", "zu", "al", "el", "bin"}
_NOT_NAME = set("""group groups members member staff students student phd contact contacts phone mail email e-mail research
lab laboratory laboratories center centre team teams project projects services service about news university institute
department core facility facilities master masters software engineers engineer senior head heads alumni former visiting
guests guest interns intern administration office home overview publications teaching education jobs vacancies career
partners network focus area areas innovation community foundation donate legal notice privacy policy select page
english german deutsch français more information visit the and for of in on with our we postal address curriculum vitae
diabetes bern berne artorg biomedical engineering clinic clinical data operations communication partnerships associated
technology technologies medicine medical health nutrition imaging robotics systems sensing monitoring study studies
program programme chair division unit science sciences your our matters voice digital welcome back
devices systems models methods tools technologies applications materials sensors implants projects assist
ventricular valves""".split())
_ROLE_WORDS = re.compile(
    r"\b(professor|prof\.|ph\.?d|doctoral|doktorand|postdoc|post-doc|researcher|research associate|scientist|student|"
    r"engineer|manager|head|lead|leader|director|coordinator|fellow|assistant|technician|intern|ceo|cfo|coo|cto|"
    r"officer|specialist|statistician|developer|physician|lecturer|chair|group leader|principal investigator|"
    r"mitarbeiter|wissenschaftlich|professeur|chercheur|doctorant|secretary|administrat|data scientist|nurse|"
    r"collaborator|consultant|advis[eo]r)", re.I)
_UNIT_WORDS = re.compile(r"\b(lab|laboratory|labor|group|gruppe|team|center|centre|zentrum|unit|institute|institut|clinic|klinik|"
                         r"division|department|abteilung|facility|platform|chair|lehrstuhl)\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CUE = re.compile(
    r"\b(?:focus(?:es|ed|ing)? (?:is |are )?on|research (?:interests? |focus )?(?:is |are |include[s]? |lies )?(?:in |on )?|"
    r"expertise (?:lies |is )?in|speciali[sz](?:es|ed|ing|ation)? (?:is )?in|works? on|working on|is dedicated to|"
    r"develop(?:s|ing)?|investigat(?:es|ing)|stud(?:ies|ying)|interested in|aims? (?:is )?to (?:develop|improve|understand)|"
    r"core expertise lies in|forscht (?:an|zu)|beschäftigt sich mit|travaille sur)\s+(.{8,220}?)(?:[.;:]\s|[.;:]?$)", re.I)
_TEAM_LINE = re.compile(r"^(project team|team|principal investigators?|pi|sponsor|project leads?|project leader|"
                        r"lead|investigators?|contact persons?|projektleitung|projektteam)\s*:\s*(.+)$", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜÉ])")
_NON_NAME_SUFFIX = ("eering", "ology", "ologie", "ics", "tion", "sion", "ment", "ism", "ity", "scopy", "graphy",
                    "ware", "logy", "ing systems")
# Navigation-style page headings that are not research entities
GENERIC_HEAD = re.compile(
    r"^(our |the )?(research( activities| projects| areas?)?|jobs?\b.*|job vacancies|vacancies|teaching|"
    r"student projects|((msc|master|bachelor|semester) )?thesis projects|theses|homepage|home|contacts?|partners?|software|back to .*|information|"
    r"services?|facilities|our services|publications?|news.*|team|group members|members|staff|people|"
    r"collaborations?|.*seminars?|education|about( us)?|overview|studienteilnehmende|.*archives|.*spin-offs|"
    r"(our )?core research pillars|downloads?|links?|media|events?|select page|projects?|focus( areas?)?|"
    r"innovation|community|get involved!?|career|imprint|legal notice|privacy policy|\d+|"
    # site administration, events and listings (UniBE institute sites): navigation, not research entities
    r"disclaimer|faq|terms (of use|& conditions|and conditions)|pricing|fees( and conditions)?|booking.*|"
    r"(meeting room )?reservations?|equipment reservation|how to .*|(vision and )?mission|our institute|"
    r"organi[sz]ation|guidelines?.*|funding( programs)?|.*\bawards?|.*\bprizes?( .*)?|awardees|"
    r"acknowledgements?|authorship|administrative (office|support)|administration|human resources|"
    r"event coordination|important information|institute secretariat|team and contact|support|resources|"
    r"research (groups( and themes)?|group leaders|units|programs|support|overview.*|fields|strategy|meetings|"
    r"collaborations)|group leaders|platform|applications|core (facilities|activities)|clusters( and networks)?|"
    r"(past )?trainings?( and courses)?|phd dissertations|academic career paths|scientific integrity|.* alumni|"
    r"group excursion.*|other equipment|instruments|microscopes|.* website|standard workplace|"
    r"projects?:.*|.*\bpublications?|\+?[\d ()/-]{6,}.*)$", re.I)
# "Dort, Jacqueline" / "Ballif Marie, PhD": person-directory headings (UniBE), surname first
_SURNAME_FIRST = re.compile(r"^([A-ZÄÖÜÉ][\w'’-]+), ([A-ZÄÖÜÉ][\w'’-]+(?: [A-ZÄÖÜÉ][\w'’-]+)?)$")
_DEGREE = r"(?:PhD|MPH|MD|MSc|MBA|PD|Dr\.|Prof\.)"
_NAME_TITLE = re.compile(rf"^([A-ZÄÖÜÉ][\w'’-]+ [A-ZÄÖÜÉ][\w'’-]+), {_DEGREE}(?:[ ,]+{_DEGREE})*$")


def _clean(line: str) -> str:
    return re.sub(r"^\s*[-*•·|]\s*", "", line).strip()


def name_like(s: str) -> bool:
    if not 4 <= len(s) <= 60 or re.search(r"[\d@/:|()&,;!?]", s):
        return False
    toks = s.replace("’", "'").split()
    core = [t for t in toks if t.lower() not in _TITLE_TOK]
    if not 2 <= len(core) <= 5 or _ROLE_WORDS.search(" ".join(core)):
        return False
    for t in core:
        tl = t.lower().strip(".")
        if tl in _NOT_NAME or (len(tl) > 6 and tl.endswith(_NON_NAME_SUFFIX)):
            return False
        if tl in _PARTICLES:
            continue
        if not (t[0].isupper() and any(c.islower() for c in t)) and not re.fullmatch(r"[A-Z]\.", t):
            return False
    return True


def role_like(s: str) -> bool:
    return len(s) <= 90 and bool(_ROLE_WORDS.search(s)) and not name_like(s) and not _EMAIL.search(s)


def _heading(page: Page, lines: list[str]) -> str:
    first = lines[0] if lines else ""
    if 3 <= len(first) <= 100:
        return first
    return re.split(r"\s+[-|–]\s+", page.title)[0].split(":")[-1].strip()


def _span(lines: list[str], i: int, j: int) -> str:
    return " ".join(lines[i:j + 1])


def _phrases(sentence: str) -> list[str]:
    out = []
    for m in _CUE.finditer(sentence):
        p = re.split(r"\s+(?:in order to|which|that|so that|with the aim|to improve|to help)\s+", m.group(1))[0]
        p = re.sub(r"^(the |a |an |new |novel |innovative )+", "", p.strip(" ,"), flags=re.I)
        words = p.split()
        if 2 <= len(words) <= 16:
            out.append(p)
    return out


def _sentences(lines: list[str]) -> list[str]:
    out = []
    for l in lines:
        if len(l) < 60:
            continue
        out += [s.strip() for s in _SENT.split(l)
                if 50 <= len(s.strip()) <= 450 and s.strip()[-1] in ".!?" and len(s.split()) >= 8]
    return out


def _people(lines: list[str], page_unit: str | None) -> list[ExtractedEntity]:
    found: dict[str, ExtractedEntity] = {}
    heading: tuple[int, str] | None = None
    n = len(lines)

    def add(name_i: int, role_i: int | None, extra_until: int):
        name = lines[name_i]
        if name in found:
            return
        lo, hi = (min(name_i, role_i), max(name_i, role_i)) if role_i is not None else (name_i, name_i)
        ent = ExtractedEntity(entity_type="person", name=Cited(value=name, snippet=lines[name_i]))
        if role_i is not None:
            ent.role = Cited(value=lines[role_i], snippet=_span(lines, lo, hi))
        for k in range(hi + 1, min(extra_until, n)):
            m = _EMAIL.search(lines[k])
            if m:
                ent.email = Cited(value=m.group(0), snippet=lines[k])
                break
            if lines[k] in ("Name / Titel", "Name / Title") or (k > hi + 1 and name_like(lines[k])):
                break
        if heading:
            ent.unit = Cited(value=heading[1], snippet=heading[1])
        found[name] = ent

    i = 0
    while i < n:
        l = lines[i]
        nxt = lines[i + 1] if i + 1 < n else ""
        if (_UNIT_WORDS.search(l) or re.search(r"[a-z]Lab\b", l)) and len(l) <= 70 and not re.search(r"\w\.\w", l) and not role_like(l) and not name_like(l) and not l.endswith(".") \
                and not GENERIC_HEAD.match(l):
            heading = (i, l)
        if l.lower() in ("name / titel", "name / title", "name") and name_like(nxt):
            role_i = next((k + 1 for k in range(i + 2, min(i + 5, n - 1))
                           if lines[k].lower() in ("funktion", "function", "position", "fonction")), None)
            add(i + 1, role_i, i + 9)
            i += 2
            continue
        if l.lower() in ("contact", "kontakt", "contacts") and name_like(nxt):
            add(i + 1, None, i + 8)
            i += 2
            continue
        if role_like(l) and name_like(nxt):
            add(i + 1, i, i + 4)
            i += 2
            continue
        if name_like(l) and role_like(nxt):
            add(i, i + 1, i + 4)
            i += 2
            continue
        m = _TEAM_LINE.match(l)
        if not m and l.endswith(":") and _TEAM_LINE.match(l + " x") and nxt:
            m = _TEAM_LINE.match(f"{l} {nxt}")  # "Sponsor:" / "Prof. X, PhD – University" on two lines
            if m:
                l = f"{l} {nxt}"
        if m:
            for part in re.split(r",|;| and | und | et ", m.group(2)):
                part = re.sub(r"\(.*?\)|–.*$|-\s.*$", "", part).strip()
                if name_like(part) and part not in found:
                    found[part] = ExtractedEntity(entity_type="person", name=Cited(value=part, snippet=l))
        i += 1
    return list(found.values())


def extract_page(page: Page) -> list[dict]:
    """Returns raw entities (as dicts, same shape as the LLM output) for extract.verify()."""
    lines = [c for c in (_clean(l) for l in page.text.splitlines()) if c]
    if not lines:
        return []
    head = _heading(page, lines)
    bare_head = re.sub(r"\s*\(.*?\)\s*", " ", head).strip()  # "Daniel Ahmed (PI)" -> "Daniel Ahmed"
    if GENERIC_HEAD.match(head.strip(" :")):
        head = ""
    ptype = page.page_type or "other"
    # a directory profile headed "Dort, Jacqueline" / "Ballif Marie, PhD" whose next line is a role
    directory_person = False
    if head and len(lines) > 1 and role_like(lines[1]):
        if m := _SURNAME_FIRST.match(head):
            bare_head, directory_person = f"{m.group(2)} {m.group(1)}", True
        elif m := _NAME_TITLE.match(head):
            bare_head, directory_person = m.group(1), True
    ents: list[ExtractedEntity] = []
    sents = _sentences(lines)
    phrases = list(dict.fromkeys(p for s in sents for p in _phrases(s)))

    def cites(values: list[str], limit: int) -> list[Cited]:
        out = []
        for v in values:
            s = next((x for x in sents if v in x), None)
            if s:
                out.append(Cited(value=v, snippet=s))
            if len(out) == limit:
                break
        return out

    description = [Cited(value=s[:120], snippet=s) for s in sents[:3]]

    # Profile page: a name-like heading AND a person signal (person URL, academic title or a role line)
    person_signal = ptype == "person" or bare_head.split()[0].lower() in _TITLE_TOK \
        or (len(lines) > 1 and role_like(lines[1]))
    if head and (directory_person or (name_like(bare_head) and person_signal)):
        ent = ExtractedEntity(entity_type="person", name=Cited(value=bare_head, snippet=lines[0]))
        if len(lines) > 1 and role_like(lines[1]):
            ent.role = Cited(value=lines[1], snippet=_span(lines, 0, 1))
        for k in range(1, min(5, len(lines))):
            parts = [p.strip() for p in lines[k].split(",")]
            if len(parts) >= 2 and any(_UNIT_WORDS.search(p) or "ARTORG" in p for p in parts):
                ent.unit = Cited(value=parts[-1], snippet=lines[k])
                if len(parts) >= 3:
                    ent.institute = Cited(value=parts[-2], snippet=lines[k])
                break
        m = _EMAIL.search("\n".join(lines[:12]))
        if m:
            ent.email = Cited(value=m.group(0), snippet=next(l for l in lines if m.group(0) in l))
        ent.expertise = cites(phrases, 8)
        ent.description = description
        ents.append(ent)
    elif ptype in ("unit", "project", "infrastructure") and head:
        # a sentence-like heading ("Exploring how real-world conditions impact ...") is a topic, not a lab
        sentence_like = len(head.split()) > 6 or re.match(
            r"^(Understanding|Exploring|Investigating|Developing|Improving|Assessing|Measuring|Towards|Using|"
            r"Building|Predicting|Enabling|Unlocking)\b", head) is not None
        etype = "project" if ptype == "unit" and sentence_like else ptype
        ent = ExtractedEntity(entity_type=etype, name=Cited(value=head, snippet=lines[0] if lines[0] == head else head))
        if etype == "infrastructure":
            ent.infrastructure = [Cited(value=head, snippet=ent.name.snippet)]
        ent.expertise = cites(phrases, 8)
        ent.description = description
        ents.append(ent)

    page_entity = ents[0].name.value if ents and ents[0].entity_type != "person" else None
    for p in _people(lines, page_entity):
        if ents and ents[0].entity_type == "person" and p.name.value == ents[0].name.value:
            continue
        if page_entity:
            if ents[0].entity_type == "project":
                p.projects = [Cited(value=page_entity, snippet=p.name.snippet)]
            elif p.unit is None:
                p.unit = Cited(value=page_entity, snippet=p.name.snippet)
        ents.append(p)
    return [e.model_dump() for e in ents]
