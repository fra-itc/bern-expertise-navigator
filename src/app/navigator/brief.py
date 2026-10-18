"""The two outputs of a request, once the officer has chosen the partners.

Output 1 — for the business-development officer: a plain-language explanation of what was
prepared and why, so she understands what she is sending without knowing the field.

Output 2 — for the company's CEO: a short executive brief whose only goal is a visit to Bern.
No overselling: every statement is either a verbatim quote from a public institutional page or
a scientific publication (DOI) listed on such a page, and each is numbered and linked. The brief
never claims that anyone has agreed to meet, and says nothing about money.
"""
from __future__ import annotations

import re
from functools import lru_cache

from . import crawl, index, plain, search, showcase
from .cases import Case
from .config import DATA_DIR
from .extract import name_key
from .schema import Entity

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>|,;]+[^\s\"<>|,;.)\]])")

T = {
    "en": {
        "kicker": "An invitation to meet Bern's research community",
        "hook": "Your enquiry mentions {topics}. In Bern, {n} research team(s) describe work on these topics on their "
                "public pages. We would like to introduce you to them in person.",
        "hook_nt": "In Bern, {n} research team(s) describe work close to what {company} is doing. We would like to "
                   "introduce you to them in person.",
        "why": "Who you would meet", "topic": "Shared topic", "stmt": "sourced statements", "teams": "research teams",
        "pubs_n": "publications", "tech": "Technical details", "pubs": "Selected publications",
        "proof": "Bern in numbers", "visit": "Proposed: a half-day in Bern",
        "visit_meet": "Meet {who}", "visit_tour": "Visit the {what}", "visit_talk": "Discuss collaboration, pilots and next steps",
        "cta": "Plan your visit", "pdf": "Save as PDF", "sources": "Sources",
        "honest": "Every statement above is quoted from the public website of the institution it describes, or is a "
                  "publication listed there, and is linked to its source. This brief proposes a meeting; it does not "
                  "state that any person has already agreed to one.",
        "from": "Prepared by {who}",
        # officer explainer
        "x.what": "Summary of the pitch",
        "x.what1": "A one-page invitation for the leadership of {company}, in English. It introduces {n} research "
                   "partner(s) in Bern and proposes a half-day visit. Nothing is said about money or contracts.",
        "x.why": "Rationale for the selected partners",
        "x.why1": "{name} ({where}) works on {topic}.",
        "x.mean": "Context: {plain}",
        "x.why2": "{name} ({where}) was chosen for this request; see the quoted sources in the brief.",
        "x.check": "What the CEO can check",
        "x.check1": "{c} statement(s), each linked to the public page it comes from, and {p} scientific publication(s) "
                    "with a DOI. Nothing in the brief is invented or estimated.",
        "x.not": "What we deliberately do not say",
        "x.not1": "No promises: we do not say that anyone has agreed to meet, we do not mention money, funding or "
                  "conditions, and we do not compare Bern with other places.",
        "x.next": "Recommended next step",
        "x.next1": "Send the link (or the PDF) with the short email below. If they are interested, propose a call or "
                   "a visit date.",
    },
    "de": {
        "kicker": "Eine Einladung, Berns Forschung kennenzulernen",
        "hook": "Ihre Anfrage erwähnt {topics}. In Bern beschreiben {n} Forschungsteam(s) auf ihren öffentlichen "
                "Seiten Arbeiten zu diesen Themen. Gerne stellen wir sie Ihnen persönlich vor.",
        "hook_nt": "In Bern beschreiben {n} Forschungsteam(s) Arbeiten, die nahe an dem liegen, was {company} macht. "
                   "Gerne stellen wir sie Ihnen persönlich vor.",
        "why": "Wen Sie treffen würden", "topic": "Gemeinsames Thema", "stmt": "belegte Aussagen", "teams": "Forschungsteams",
        "pubs_n": "Publikationen", "tech": "Technische Details", "pubs": "Ausgewählte Publikationen",
        "proof": "Bern in Zahlen", "visit": "Vorschlag: ein halber Tag in Bern",
        "visit_meet": "Treffen mit {who}", "visit_tour": "Besuch: {what}", "visit_talk": "Austausch zu Zusammenarbeit, Pilotprojekten und nächsten Schritten",
        "cta": "Besuch planen", "pdf": "Als PDF speichern", "sources": "Quellen",
        "honest": "Jede Aussage oben ist wörtlich von der öffentlichen Website der beschriebenen Institution zitiert "
                  "oder ist eine dort aufgeführte Publikation und mit ihrer Quelle verlinkt. Dieses Dokument schlägt "
                  "ein Treffen vor; es behauptet nicht, dass jemand bereits zugesagt hat.",
        "from": "Erstellt von {who}",
        "x.what": "Zusammenfassung des Pitchs",
        "x.what1": "Eine einseitige Einladung an die Geschäftsleitung von {company}, auf Deutsch. Sie stellt {n} "
                   "Forschungspartner in Bern vor und schlägt einen halbtägigen Besuch vor. Über Geld oder Verträge "
                   "wird nichts gesagt.",
        "x.why": "Begründung der ausgewählten Partner",
        "x.why1": "{name} ({where}) arbeitet an {topic}.",
        "x.mean": "Einordnung: {plain}",
        "x.why2": "{name} ({where}) wurde für diese Anfrage ausgewählt; die Belege stehen im Dokument.",
        "x.check": "Was die Geschäftsleitung prüfen kann",
        "x.check1": "{c} Aussage(n), jede mit der öffentlichen Seite verlinkt, von der sie stammt, und {p} "
                    "wissenschaftliche Publikation(en) mit DOI. Nichts ist erfunden oder geschätzt.",
        "x.not": "Was wir bewusst nicht sagen",
        "x.not1": "Keine Versprechen: Wir sagen nicht, dass jemand einem Treffen zugestimmt hat, erwähnen weder Geld, "
                  "Förderung noch Konditionen und vergleichen Bern nicht mit anderen Standorten.",
        "x.next": "Empfohlener nächster Schritt",
        "x.next1": "Senden Sie den Link (oder das PDF) mit der kurzen E-Mail unten. Bei Interesse schlagen Sie ein "
                   "Gespräch oder einen Besuchstermin vor.",
    },
    "fr": {
        "kicker": "Une invitation à rencontrer la recherche bernoise",
        "hook": "Votre demande mentionne {topics}. À Berne, {n} équipe(s) de recherche décrivent des travaux sur ces "
                "sujets sur leurs pages publiques. Nous aimerions vous les présenter en personne.",
        "hook_nt": "À Berne, {n} équipe(s) de recherche décrivent des travaux proches de ceux de {company}. Nous "
                   "aimerions vous les présenter en personne.",
        "why": "Qui vous rencontreriez", "topic": "Sujet commun", "stmt": "affirmations sourcées", "teams": "équipes de recherche",
        "pubs_n": "publications", "tech": "Détails techniques", "pubs": "Publications choisies",
        "proof": "Berne en chiffres", "visit": "Proposition : une demi-journée à Berne",
        "visit_meet": "Rencontrer {who}", "visit_tour": "Visiter : {what}", "visit_talk": "Échanger sur collaboration, projets pilotes et prochaines étapes",
        "cta": "Planifier votre visite", "pdf": "Enregistrer en PDF", "sources": "Sources",
        "honest": "Chaque affirmation ci-dessus est citée du site public de l'institution concernée, ou est une "
                  "publication qui y figure, avec un lien vers sa source. Ce document propose une rencontre ; il "
                  "n'affirme pas que quiconque l'a déjà acceptée.",
        "from": "Préparé par {who}",
        "x.what": "Résumé du pitch",
        "x.what1": "Une invitation d'une page pour la direction de {company}, en français. Elle présente {n} "
                   "partenaire(s) de recherche à Berne et propose une visite d'une demi-journée. Rien n'est dit sur "
                   "l'argent ou les contrats.",
        "x.why": "Justification des partenaires retenus",
        "x.why1": "{name} ({where}) travaille sur {topic}.",
        "x.mean": "Contexte : {plain}",
        "x.why2": "{name} ({where}) a été choisi(e) pour cette demande ; les sources figurent dans la note.",
        "x.check": "Ce que la direction peut vérifier",
        "x.check1": "{c} affirmation(s), chacune liée à la page publique d'où elle provient, et {p} publication(s) "
                    "scientifique(s) avec DOI. Rien n'est inventé ni estimé.",
        "x.not": "Ce que nous ne disons volontairement pas",
        "x.not1": "Aucune promesse : nous ne disons pas que quelqu'un a accepté de rencontrer l'entreprise, ne parlons "
                  "ni d'argent, ni de financement, ni de conditions, et ne comparons pas Berne à d'autres lieux.",
        "x.next": "Prochaine étape recommandée",
        "x.next1": "Envoyez le lien (ou le PDF) avec le court e-mail ci-dessous. En cas d'intérêt, proposez un appel "
                   "ou une date de visite.",
    },
}


# ---------------- publications (DOIs listed on the institutions' pages) --------------------------
@lru_cache(maxsize=2)
def _publications(_key: tuple) -> list[dict]:
    out, seen = [], set()
    for p in crawl.load_pages():
        lines = [ln.strip(" -•|") for ln in p.text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            for m in _DOI.finditer(ln):
                doi = m.group(1)
                # the citation is the DOI line, or (DCB style "Title / Authors / DOI: …") the lines above it
                cite = ln if len(ln) > 60 else " · ".join(x for x in lines[max(0, i - 2):i + 1] if x)
                if (doi, p.url) in seen:
                    continue
                seen.add((doi, p.url))
                out.append({"doi": doi, "citation": cite[:400], "page": p.url, "source": p.source})
    return out


def publications() -> list[dict]:
    files = tuple(sorted(f.stat().st_mtime for f in (DATA_DIR / "pages").glob("*.jsonl")))
    return _publications(files)


def pubs_for(e: Entity, limit: int = 2) -> list[dict]:
    """Publications that name this person (surname in the citation) or sit on this entity's own pages."""
    surname = [t for t in name_key(e.name).split() if len(t) >= 4]
    own = set(e.source_urls)
    hits = []
    for pub in publications():
        if pub["source"] != e.source:
            continue
        cite = name_key(pub["citation"])
        if (e.entity_type == "person" and surname and re.search(rf"\b{re.escape(surname[-1])}\b", cite)) or \
                (e.entity_type != "person" and pub["page"] in own):
            hits.append(pub)
    return hits[:limit]


# ---------------- topic overlap: request terms <-> partner evidence --------------------------------
def _topics(case: Case, e: Entity, lang: str) -> list[dict]:
    """Glossary topics named in the company's request AND in this partner's own evidence."""
    req_terms = {t["term"] for t in plain.find_terms(case.source_text(), lang)}
    text = e.search_text()
    return [t for t in plain.find_terms(text, lang) if t["term"] in req_terms]


def _quote_candidates(e: Entity, topics: list[dict], ents: dict[str, Entity]):
    """Verbatim sentences about this partner, most telling first, for a non-specialist reader.

    Order: own sentence naming a shared topic → linked project/lab sentence naming it (projects whose
    name carries the topic first) → own description → linked description → role line. Team-list lines
    are relations, not descriptions, so they are never used as the headline quote.
    """
    forms = [t["found_as"] for t in topics]
    topical = ("description", "expertise", "infrastructure")
    linked = [ents[i] for i in search.neighbors([e.id]).get(e.id, []) if i in ents and ents[i].entity_type in ("project", "unit")]
    linked.sort(key=lambda x: not any(f in x.name.lower() for f in forms))

    def sentences(ent: Entity, need_topic: bool):
        for ev in ent.evidence:
            if ev.field in topical and len(ev.snippet) > 50 and (not need_topic or any(f in ev.snippet.lower() for f in forms)):
                yield ev

    for need in ((True, False) if forms else (False,)):
        for ev in sentences(e, need):
            yield {"text": ev.snippet, "url": ev.url, "via": None}
        for ln in linked:
            topic_in_name = any(f in ln.name.lower() for f in forms)
            for ev in sentences(ln, need and not topic_in_name):
                yield {"text": ev.snippet, "url": ev.url, "via": ln.name}
    for ev in e.evidence:
        if ev.field == "role":
            yield {"text": ev.snippet, "url": ev.url, "via": None}


def _best_quote(e: Entity, topics: list[dict], ents: dict[str, Entity], used: set[str] | None = None) -> dict | None:
    """First candidate not already shown on another card (falls back to a repeat rather than nothing)."""
    first = None
    for q in _quote_candidates(e, topics, ents):
        first = first or q
        if not used or q["text"] not in used:
            return q
    return first


# ---------------- build both outputs ---------------------------------------------------------------
def build(case: Case, lang: str, officer: dict) -> dict:
    t = T.get(lang, T["en"])
    ents = index.load_entities()
    approved = [m for m in case.matches if m.selected and m.id in ents]
    sources: list[dict] = []

    def cite(url: str, label: str, kind: str = "page") -> int:
        for i, s in enumerate(sources, 1):
            if s["url"] == url:
                return i
        sources.append({"url": url, "label": label, "kind": kind})
        return len(sources)

    items, all_topics, used_quotes = [], [], set()
    for m in approved:
        e = ents[m.id]
        topics = _topics(case, e, lang)
        all_topics += [x for x in topics if x["term"] not in {y["term"] for y in all_topics}]
        quote = _best_quote(e, topics, ents, used_quotes)
        if quote:
            used_quotes.add(quote["text"])
        q = {**quote, "ref": cite(quote["url"], f"{e.source_label} — {quote['via'] or e.name}")} if quote else None
        seen_snips: set[str] = set()
        tech = []
        for ev in e.evidence:
            if ev.field in ("name", "email") or ev.snippet in seen_snips or (quote and ev.snippet == quote["text"]):
                continue
            seen_snips.add(ev.snippet)
            tech.append({"field": ev.field, "text": ev.snippet, "url": ev.url, "ref": cite(ev.url, f"{e.source_label} — {e.name}")})
        tech = tech[:6]
        pubs = [{**p, "ref": cite(f"https://doi.org/{p['doi']}", p["citation"][:120], "doi"),
                 "page_ref": cite(p["page"], f"{e.source_label} — publication list")} for p in pubs_for(e)]
        items.append({"id": e.id, "name": e.name, "type": e.entity_type, "role": e.role, "unit": e.unit,
                      "institution": e.source_label, "email": e.email, "page": e.source_urls[0],
                      "page_ref": cite(e.source_urls[0], f"{e.source_label} — {e.name}"),
                      "topics": [{"term": x["term"], "plain": x["plain"]} for x in topics],
                      "quote": q, "technical": tech, "publications": pubs})

    proof = []
    for h in showcase.build().get("highlights", [])[:3]:
        proof.append({**h, "label": h["label"].get(lang) or h["label"]["en"], "ref": cite(h["url"], h["url"])})

    topic_txt = ", ".join(x["term"] for x in all_topics[:3])
    n = len(items)
    hook = t["hook"].format(company=case.company, topics=topic_txt, n=n) if topic_txt else t["hook_nt"].format(company=case.company, n=n)
    people = [i["name"] for i in items if i["type"] in ("person", "unit")][:3]
    facility = next((i["name"] for i in items if i["type"] == "infrastructure"), None)
    agenda = ([t["visit_meet"].format(who=", ".join(people))] if people else []) + \
        ([t["visit_tour"].format(what=facility)] if facility else []) + [t["visit_talk"]]

    brief = {"lang": lang, "company": case.company, "kicker": t["kicker"], "hook": hook, "items": items,
             "proof": proof, "agenda": agenda, "sources": sources, "honest": t["honest"],
             "labels": {k: t[k] for k in ("why", "topic", "tech", "pubs", "proof", "visit", "cta", "pdf", "sources",
                                          "stmt", "teams", "pubs_n")},
             "from": t["from"].format(who=", ".join(x for x in [officer.get("name"), officer.get("team")] if x)),
             "contact": {"name": officer.get("name", ""), "email": officer.get("email", ""), "team": officer.get("team", "")}}

    # ---- Output 1: what the officer is sending, in plain words
    why = []
    for it in items:
        where = ", ".join(x for x in [it["unit"], it["institution"]] if x)
        if it["topics"]:
            tp = it["topics"][0]
            why.append({"text": t["x.why1"].format(name=it["name"], where=where, topic=tp["term"]),
                        "plain": t["x.mean"].format(plain=tp["plain"])})
        else:
            why.append({"text": t["x.why2"].format(name=it["name"], where=where), "plain": ""})
    n_claims = sum(1 for i in items if i["quote"]) + sum(len(i["technical"]) for i in items) + len(proof)
    n_pubs = sum(len(i["publications"]) for i in items)
    explainer = [
        {"title": t["x.what"], "lines": [{"text": t["x.what1"].format(company=case.company, n=n)}]},
        {"title": t["x.why"], "lines": why},
        {"title": t["x.check"], "lines": [{"text": t["x.check1"].format(c=n_claims, p=n_pubs)}]},
        {"title": t["x.not"], "lines": [{"text": t["x.not1"]}]},
        {"title": t["x.next"], "lines": [{"text": t["x.next1"]}]},
    ]
    return {"brief": brief, "explainer": explainer, "stats": {"claims": n_claims, "publications": n_pubs, "sources": len(sources)}}
