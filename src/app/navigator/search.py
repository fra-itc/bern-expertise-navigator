"""Stage 5 — hybrid search, fair ranking, cited explanations, honest abstention."""
from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from pydantic import BaseModel

from . import index, llm
from .config import load_glossary, load_sources, settings
from .extract import name_key, unit_key
from .storage import PaperHit, index_store
from .schema import Affiliation, Entity, SearchResponse, SearchResult, SourceRef

RRF_K = 60
NO_SOURCE_MSG = ("No verifiable public source found for this query in the indexed websites. "
                 "Try broader or alternative terms, or check another institution.")
# e5 cosine similarities live in a narrow band; map it to 0..1 for display
CONF_LO, CONF_HI = 0.75, 0.90
# A result must clear this vector score OR share a word with the (expanded) query
RESULT_FLOOR_MARGIN = 0.03


# ---------------- query understanding ---------------------------------------
class _QueryAnalysis(BaseModel):
    terms: list[str]
    person_names: list[str] = []


def glossary_terms(q: str) -> list[str]:
    ql = q.lower()
    out = []
    for k, vs in load_glossary().items():
        if k in ql or any(re.search(rf"\b{re.escape(v)}\b", ql) for v in vs):
            out += [k, *vs]
    return out


@lru_cache(maxsize=1024)
def llm_analyze(q: str) -> _QueryAnalysis:
    try:
        r = llm.chat_json([
            {"role": "system", "content": "You help search university research websites. JSON only."},
            {"role": "user", "content": (
                "For the search query below return:\n"
                "- terms: up to 8 short alternative search terms (technical synonyms, abbreviations, lay terms) "
                "in English, German and French. No explanations.\n"
                "- person_names: names of specific people mentioned in the query (empty if none).\n"
                f"QUERY: {q}")},
        ], _QueryAnalysis, mode="none", max_tokens=250, temperature=0.0)
        terms = [t.strip().lower() for t in r.terms if 1 < len(t.strip()) < 60][:8]  # type: ignore[attr-defined]
        return _QueryAnalysis(terms=terms, person_names=[n for n in r.person_names if n.strip()])  # type: ignore[attr-defined]
    except llm.LLMError:
        return _QueryAnalysis(terms=[])


_TITLE_NAME = re.compile(r"\b(?i:prof|dr|pd)\.?\s+((?:[A-ZÄÖÜ][\w'’-]+\s*){1,3})")


def regex_person_names(q: str) -> list[str]:
    """No-LLM fallback: 'Prof. Jane Doe' / 'Dr. Doe'."""
    return [m.group(1).strip() for m in _TITLE_NAME.finditer(q)]


def analyze(q: str) -> tuple[list[str], list[str]]:
    terms = glossary_terms(q)
    names = regex_person_names(q)
    if settings.use_llm_expansion and llm.available():
        a = llm_analyze(q)
        terms += a.terms
        # Only names literally in the query with >= 2 words ("Parkinson disease" is not a person query)
        names += [n for n in a.person_names if len(n.split()) >= 2 and n.lower() in q.lower()]
    seen, out = {q.lower()}, []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out, list(dict.fromkeys(names))


def expand(q: str) -> list[str]:
    return analyze(q)[0]


def match_person(name: str, ents: dict[str, Entity]) -> list[str]:
    toks = set(name_key(name).split())
    if not toks:
        return []
    return [eid for eid, e in ents.items() if toks <= set(name_key(e.name).split())]


# ---------------- retrieval -----------------------------------------------
def bm25_rank(text: str, top: int = 100) -> tuple[list[str], float]:
    """Lexical ranking for RRF: BM25 (file backend) or Postgres FTS (pg backend), same contract."""
    return index_store().lexical_rank(index.tokenize(text), top)


def vector_rank(q: str, extra: list[str], top: int = 200,
                sources: list[str] | None = None) -> tuple[list[str], dict[str, float]]:
    """Ranking over query + expansions; also returns each entity's best cosine to the ORIGINAL query."""
    texts = [q, *extra[:4]]
    vecs = index.embed(texts, query=True)
    best: dict[str, float] = {}
    orig: dict[str, float] = {}
    for j, (text, vec) in enumerate(zip(texts, vecs)):
        for eid, score in index_store().vector_search(vec, top, sources):
            best[eid] = max(best.get(eid, 0.0), score * (1.0 if j == 0 else 0.97))
            if j == 0:
                orig[eid] = max(orig.get(eid, 0.0), score)
    return sorted(best, key=lambda k: -best[k]), orig


@lru_cache(maxsize=1)
def _record_only_sources() -> frozenset[str]:
    return frozenset(s.name for s in load_sources() if s.type == "openalex")


def rrf(*rankings: list[str], weights: list[float] | None = None) -> dict[str, float]:
    s: dict[str, float] = {}
    for j, r in enumerate(rankings):
        w = weights[j] if weights else 1.0
        for i, eid in enumerate(r):
            s[eid] = s.get(eid, 0.0) + w / (RRF_K + i + 1)
    return s


# ---------------- papers (Postgres backend: store.supports_papers) ----------------
def paper_hits(q: str) -> tuple[dict[str, PaperHit], np.ndarray | None]:
    """Best paper chunk per entity for the query; empty when the store has no paper vectors."""
    st = index_store()
    if not settings.use_papers or not getattr(st, "supports_papers", False) or not st.has_paper_vectors():
        return {}, None
    qvec = index.embed([q], query=True)[0]
    return st.paper_hits(qvec), qvec


def propagate_similar(fused: dict[str, float], ents: dict[str, Entity], depth: int = 10) -> dict[str, tuple[str, float]]:
    """A matching person surfaces the people with a similar research profile (SIMILAR_TO), damped by
    SIMILAR_DAMPING x similarity. Returns {person_id: (person it was reached from, similarity)}."""
    st = index_store()
    people = [pid for pid in sorted(fused, key=lambda x: -fused[x])[:depth]
              if (p := ents.get(pid)) and p.entity_type == "person"]
    g = st.similar_neighbors(people)
    out: dict[str, tuple[str, float]] = {}
    for pid in people:
        for nb, sim in g.get(pid, []):
            if nb not in ents:
                continue
            score = fused[pid] * settings.similar_damping * sim
            if score > fused.get(nb, 0.0):
                fused[nb] = score
                out[nb] = (pid, sim)
    return out


_SENT = re.compile(r"(?<=[.!?])\s+")


def best_sentence(text: str, terms: list[str], max_chars: int = 300) -> str:
    """Verbatim sentence of the chunk sharing most words with the query (first sentence after the title if none)."""
    sents = [x.strip() for x in _SENT.split(text) if x.strip()]
    if not sents:
        return text[:max_chars]
    toks = {t for term in terms for t in index.tokenize(term) if len(t) > 2}
    scored = [(sum(t in x.lower() for t in toks), -i, x) for i, x in enumerate(sents)]
    best = max(scored)[2] if max(scored)[0] > 0 else (sents[1] if len(sents) > 1 else sents[0])
    if len(best) > max_chars:
        cut = best[:max_chars]
        best = cut[: cut.rfind(" ")] if " " in cut else cut
    return best


def paper_source(h: PaperHit, terms: list[str]) -> SourceRef:
    return SourceRef(url=h.url, snippet=best_sentence(h.text, terms), field="publication", retrieved_at=h.fetched_at)


def paper_why(h: PaperHit, snippet: str) -> str:
    when = f" ({h.year})" if h.year else ""
    lead = "Author of" if h.relation == "author" else "Their page lists"
    short = snippet if len(snippet) <= 180 else snippet[: snippet.rfind(" ", 0, 180)] + " …"
    return f"{lead} “{h.title}”{when}, which says: “{short}”"


def fair_top(ids: list[str], ents: dict[str, Entity], k: int) -> list[str]:
    """Diversity cap: at most N people and N units/projects per unit, so small groups stay visible."""
    per_unit: Counter[tuple[str, bool]] = Counter()
    out, overflow = [], []
    for eid in ids:
        e = ents.get(eid)
        if not e:
            continue
        is_person = e.entity_type == "person"
        # people are capped per lab; someone whose lab is unknown counts on their own (no shared bucket)
        unit = (unit_key(e.unit or e.name) if not is_person else (unit_key(e.unit) if e.unit else "id:" + e.id), is_person)
        if is_person and per_unit[unit] >= settings.max_per_unit:
            # the lab is full: a more senior person (e.g. the group head) replaces its most junior pick
            same = [x for x in out if ents[x].entity_type == "person" and ents[x].unit and unit_key(ents[x].unit) == unit[0]]
            weakest = min(same, key=lambda x: seniority(ents[x]), default=None)
            if weakest and seniority(e) > seniority(ents[weakest]):
                out[out.index(weakest)] = eid
                overflow.append(weakest)
                continue
        if per_unit[unit] < settings.max_per_unit:
            per_unit[unit] += 1
            out.append(eid)
        else:
            overflow.append(eid)
        if len(out) == k:
            break
    return (out + overflow)[:k]


# ---------------- lightweight knowledge graph -----------------------------
# person <-> unit, person <-> project, project <-> unit links (by name, within one source).
# The rules live in graph.py; the store answers neighbours (adjacency list or Cypher on AGE).
def neighbors(ids: list[str]) -> dict[str, list[str]]:
    return index_store().neighbors(list(dict.fromkeys(ids))) if ids else {}


def related(e: Entity, ents: dict[str, Entity], limit: int = 8, nb_ids: list[str] | None = None) -> list[str]:
    ids = nb_ids if nb_ids is not None else neighbors([e.id]).get(e.id, [])
    nb = [ents[i] for i in ids if i in ents]
    # people first (by seniority), then units / projects
    nb.sort(key=lambda x: (x.entity_type != "person", -seniority(x)))
    return [x.name for x in nb[:limit]]


_SENIOR = re.compile(r"prof|head|leader|lead\b|director|chair|principal|\bpi\b|chief|ceo", re.I)
_JUNIOR = re.compile(r"student|intern|master|bachelor|apprentice|assistant\b|technician", re.I)


_LEAD = re.compile(r"\bprof|group head|head of|group leader|director|principal investigator|\bpi\b", re.I)


def seniority(e: Entity) -> float:
    text = f"{e.role or ''} {e.name}"
    if _LEAD.search(text):
        return 1.2  # professor / group head: the person to contact first
    if _SENIOR.search(text):
        return 1.0
    if _JUNIOR.search(text):
        return 0.6
    return 0.8


def propagate(fused: dict[str, float], ents: dict[str, Entity], depth: int = 20) -> dict[str, str]:
    """A matching unit/project surfaces its people: 'who do I contact about this?'.

    Returns {person_id: id of the unit/project it was found through}. The person's score is the
    parent's score damped by seniority, so group heads come before students.
    """
    via: dict[str, str] = {}
    parents = [pid for pid in sorted(fused, key=lambda x: -fused[x])[:depth]
               if (p := ents.get(pid)) and p.entity_type != "person"]
    g = neighbors(parents)
    for pid in parents:
        for cid in g.get(pid, []):
            c = ents.get(cid)
            if not c or c.entity_type != "person":
                continue
            # group head lands right after the group itself; members further down
            s = seniority(c)
            score = fused[pid] * (0.98 if s >= 1.2 else 0.93 if s >= 1.0 else 0.85 * s)
            if score > fused.get(cid, 0.0):
                fused[cid] = score
                via[cid] = pid
    return via


# ---------------- explanation (cited, never free-form) ---------------------
class _Why(BaseModel):
    explanation: str
    evidence_ids: list[int]


def matched_evidence(e: Entity, terms: list[str]):
    toks = {t for term in terms for t in index.tokenize(term) if len(t) > 2}
    scored = [(sum(t in ev.snippet.lower() for t in toks), i, ev) for i, ev in enumerate(e.evidence)
              if ev.field != "email"]
    hits = [x for x in sorted(scored, key=lambda x: -x[0]) if x[0] > 0]
    if hits:
        return hits
    # No lexical overlap (semantic match): show the entity's topical evidence, not just its name
    topical = [x for x in scored if x[2].field in ("expertise", "projects", "infrastructure", "role")]
    return topical[:3] or scored[:2]


def coverage(q: str, docs: list[Entity]) -> float:
    """Share of the query's content words (5-char prefix, so plurals match) found in the best document."""
    qt = [t for t in index.tokenize(q) if len(t) > 2]
    if not qt or not docs:
        return 0.0
    best = 0.0
    for d in docs:
        txt = d.search_text().lower()
        best = max(best, sum(bool(re.search(r"\b" + re.escape(t[:5]), txt)) for t in qt) / len(qt))
    return best


def lexical_hit(e: Entity, terms: list[str]) -> bool:
    toks = {t for term in terms for t in index.tokenize(term) if len(t) > 2}
    text = e.search_text().lower()
    return any(re.search(rf"\b{re.escape(t)}", text) for t in toks)


@lru_cache(maxsize=4096)
def _llm_why(q: str, name: str, etype: str, numbered: str, valid: tuple[int, ...]) -> str | None:
    try:
        r = llm.chat_json([
            {"role": "system", "content": "Explain search matches using ONLY the given evidence. JSON only."},
            {"role": "user", "content": (
                f"Query: {q}\nCandidate: {name} ({etype})\nEvidence:\n{numbered}\n\n"
                "In max 30 words, say why this candidate matches the query. Cite the evidence ids you used. "
                "Do not add facts that are not in the evidence. "
                "If the evidence does not support a match, say 'Weak match'.")},
        ], _Why, mode="none", max_tokens=150)
    except llm.LLMError:
        return None
    if not r.evidence_ids or not set(r.evidence_ids) <= set(valid):  # type: ignore[attr-defined]
        return None
    return r.explanation  # type: ignore[attr-defined]


def explain_similar(q: str, person: Entity, parent: Entity, sim: float, terms: list[str],
                    paper: PaperHit | None, use_llm: bool = True) -> tuple[str, list[SourceRef]]:
    """Person reached through SIMILAR_TO: say so, and cite the person's own evidence (paper first)."""
    why, refs = explain(q, person, terms, paper, use_llm=use_llm)
    return f"Research profile similar to {parent.name} (cosine {sim:.2f}). {why}", refs


def explain_via(q: str, person: Entity, parent: Entity, terms: list[str],
                use_llm: bool = True) -> tuple[str, list[SourceRef]]:
    """Person found through a matching unit/project: cite the link AND why the unit/project matches."""
    why_parent, refs = explain(q, parent, terms, use_llm=use_llm)
    link = [ev for ev in person.evidence if ev.field in ("unit", "institute", "projects", "role", "name")
            and (parent.name in ev.value or ev.field in ("role", "name"))][:2]
    link_refs = [SourceRef(url=ev.url, snippet=ev.snippet, field=ev.field, retrieved_at=person.retrieved_at) for ev in link]
    rel = {"unit": "Works in", "project": "On the team of"}.get(parent.entity_type, "Contact for")
    return f"{rel} {parent.name}, which {why_parent[0].lower()}{why_parent[1:]}", link_refs + refs[:3]


_FIELD_NAME = {"name": "name", "description": "description", "expertise": "stated expertise", "projects": "projects",
               "role": "role", "unit": "affiliation", "institute": "affiliation", "infrastructure": "services"}


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def fallback_why(q: str, terms: list[str], hits) -> str:
    """Deterministic, honest explanation: which query words occur where (no LLM)."""
    lexical = [x for x in hits if x[0] > 0]
    if not lexical:
        return "Is close in meaning to your query (no exact word match); see the quoted source."
    text = " ".join(ev.snippet.lower() for _, _, ev in lexical)
    phrases = [t for t in [q, *terms] if len(t) > 2 and re.search(rf"\b{re.escape(t.lower())}", text)]
    if not phrases:
        phrases = list(dict.fromkeys(t for t in index.tokenize(" ".join([q, *terms]))
                                     if len(t) > 2 and re.search(rf"\b{re.escape(t)}", text)))
    fields = list(dict.fromkeys(_FIELD_NAME.get(ev.field, ev.field) for _, _, ev in lexical))
    return f"Mentions {_join([f'“{p}”' for p in phrases[:3]])} in its {_join(fields[:3])}."


def explain(q: str, e: Entity, terms: list[str], paper: PaperHit | None = None,
            use_llm: bool = True) -> tuple[str, list[SourceRef]]:
    hits = matched_evidence(e, [q, *terms])[:4]
    refs = [SourceRef(url=ev.url, snippet=ev.snippet, field=ev.field, retrieved_at=e.retrieved_at)
            for _, _, ev in hits]
    fallback = fallback_why(q, terms, hits)
    numbered_paper: list[tuple[int, str]] = []
    if paper is not None:
        pref = paper_source(paper, [q, *terms])
        pwhy = paper_why(paper, pref.snippet)
        if any(x[0] > 0 for x in hits):   # the page itself matches: the paper supports it
            refs, fallback = refs[:3] + [pref], f"{fallback} {pwhy}."
        else:                              # found through the paper: it is the main evidence
            refs, fallback = [pref] + refs[:3], f"{pwhy}."
        numbered_paper = [(len(e.evidence), f"(publication “{paper.title}”) {pref.snippet}")]
    if not use_llm or not settings.use_llm_explain or not (hits or numbered_paper) or not llm.available():
        return fallback, refs
    items = [(i, f"({ev.field}) {ev.snippet}") for _, i, ev in hits] + numbered_paper
    numbered = "\n".join(f"[{i}] {t}" for i, t in items)
    why = _llm_why(q, e.name, e.entity_type, numbered, tuple(i for i, _ in items))
    return (why or fallback), refs


# ---------------- public API ----------------------------------------------
_pool = ThreadPoolExecutor(max_workers=8)


def _abstain(q: str, terms: list[str], msg: str = NO_SOURCE_MSG) -> SearchResponse:
    return SearchResponse(query=q, expanded_terms=terms, abstained=True, message=msg, results=[])


def search(q: str, k: int = 10, sources: list[str] | None = None, types: list[str] | None = None,
           llm_explain: bool = True) -> SearchResponse:
    """llm_explain=False: rule-based "why" only (fast); callers can explain the few results they keep."""
    q = q.strip()
    ents = index.load_entities()
    if not ents:
        return _abstain(q, [], "The index is empty: run the pipeline (crawl -> extract -> index) first.")
    terms, names = analyze(q)

    # Honest about people: a named person who is not on any indexed page -> no answer
    pinned: list[str] = []
    for n in names:
        found = match_person(n, ents)
        if not found:
            return _abstain(q, terms, f"No person named “{n}” appears on the indexed public pages. " + NO_SOURCE_MSG)
        pinned += found

    bm_q, bm_top = bm25_rank(q)
    bm_x, _ = bm25_rank(" ".join(terms)) if terms else ([], 0.0)
    vec_ids, vec_orig = vector_rank(q, terms, sources=sources)
    # papers (Postgres only): an entity's best paper chunk is semantic evidence like its own snippets
    phits, qvec = paper_hits(q)
    sem = dict(vec_orig)
    for eid, h in phits.items():
        sem[eid] = max(sem.get(eid, 0.0), h.cos)
    vec_top = max(sem.values(), default=0.0)

    # Honest abstention: weak semantic match AND the query's words are mostly absent from the best
    # candidates AND no expansion term occurs verbatim. Calibrated on eval/golden_set.yaml.
    cands = [ents[i] for i in (sorted(sem, key=lambda x: -sem[x])[:5] + bm_q[:5]) if i in ents]
    if not pinned and vec_top < settings.min_vector_score \
            and coverage(q, cands) <= settings.min_coverage \
            and max([coverage(t, cands) for t in terms] or [0.0]) < 1.0:
        return _abstain(q, terms)

    paper_ids = sorted(phits, key=lambda x: (-phits[x].cos, x))
    fused = rrf(bm_q, bm_x, vec_ids, paper_ids, weights=[1.0, 1.0, 1.0, settings.paper_weight])
    record_only = _record_only_sources()
    for eid in fused:
        if eid in ents and ents[eid].source in record_only:
            fused[eid] *= settings.record_only_weight
    via = propagate(fused, ents)
    via_sim = propagate_similar(fused, ents) if phits else {}
    for eid in via_sim:
        via.pop(eid, None)
    for i, eid in enumerate(pinned):
        fused[eid] = fused.get(eid, 0.0) + 1.0 - i * 1e-3
        via.pop(eid, None)
        via_sim.pop(eid, None)
    floor = settings.min_vector_score - RESULT_FLOOR_MARGIN
    all_terms = [q, *terms]
    ranked = [eid for eid in sorted(fused, key=lambda x: -fused[x])
              if eid in ents
              and (not sources or ents[eid].source in sources)
              and (not types or ents[eid].entity_type in types)
              and (eid in pinned or eid in via or eid in via_sim or sem.get(eid, 0.0) >= floor
                   or lexical_hit(ents[eid], all_terms))]
    top = fair_top(ranked, ents, k)
    if via_sim and qvec is not None:  # people reached by similarity: their own best paper for this query
        missing = [eid for eid in top if eid in via_sim and eid not in phits]
        phits = {**phits, **index_store().paper_best_for(qvec, missing)}

    def _explain(eid: str):
        if eid in via and via[eid] in ents:
            return explain_via(q, ents[eid], ents[via[eid]], terms, use_llm=llm_explain)
        if eid in via_sim and via_sim[eid][0] in ents:
            parent, sim = via_sim[eid]
            return explain_similar(q, ents[eid], ents[parent], sim, terms, phits.get(eid), use_llm=llm_explain)
        return explain(q, ents[eid], terms, phits.get(eid), use_llm=llm_explain)

    explained = list(_pool.map(llm.bound(_explain), top))
    nb = neighbors(top)
    results = []
    for eid, (why, refs) in zip(top, explained):
        e = ents[eid]
        if not refs:  # traceability guard: never return an unsourced result
            continue
        parent = via.get(eid) or via_sim.get(eid, ("", 0.0))[0]
        sim = max(sem.get(eid, 0.0), sem.get(parent, 0.0)) or CONF_LO
        conf = float(np.clip((sim - CONF_LO) / (CONF_HI - CONF_LO), 0, 1))
        results.append(SearchResult(
            id=e.id, person_or_unit=e.name, entity_type=e.entity_type, role=e.role,
            affiliation=Affiliation(unit=e.unit, institute=e.institute, institution=e.source_label),
            institution=e.source_label, expertise=e.expertise, projects=e.projects,
            infrastructure_services=e.infrastructure, description=(e.description or [None])[0],
            contact=e.email, why_match=why, related=related(e, ents, nb_ids=nb.get(eid, [])),
            via=ents[parent].name if parent in ents else None, sources=refs, score=round(fused[eid], 4), confidence=round(conf, 2)))
    if not results:
        return _abstain(q, terms)
    return SearchResponse(query=q, expanded_terms=terms, abstained=False, results=results)
