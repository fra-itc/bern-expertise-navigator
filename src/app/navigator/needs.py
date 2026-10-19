"""Which Bern assets support which company need, from the words of their own pages.

A need ("Regulatory affairs expertise for global market approvals") is linked to an asset only when the asset's
own text names what the need is about (its kind: "regulatory", "approvals") and, when the need also names the
company's topic ("Clinical validation partners for new contrast agents"), that topic as a phrase ("contrast
agents", not "contrast" alone: the optical contrast of a microscope is not a contrast agent).

The offer paragraph, its claim check and the officer's preface all use this, so none of them links a need to an
asset whose sources do not show it. Words in the partner's text that merely look alike are not enough:
"hormonal regulation" does not make a regulatory expert.
"""
from __future__ import annotations

import re

from . import index

# words that say nothing about WHAT a need is ("partners for", "expertise in", "support", "new")
FILLER = set("""need needs partner partners partnership expertise expert experts support supporting specialist specialists
talent talents access new global local international help helping based capability capabilities opportunity
opportunities collaboration collaborations collaborate looking seeking improve improving enhance enhancing scale scaling
develop developing development next generation advanced novel key related service services solution solutions company
companies business technology technologies tech device devices product products system systems medical medicine
healthcare health patient patients treatment treatments therapy care application applications platform innovation
innovative swiss switzerland bern market markets team teams people build builds make makes look want
wants search""".split())


def base(t: str) -> str:
    """Singular form, as far as plural "s" goes ("agents" -> "agent"; not "continuous", "diagnosis", "access")."""
    return t[:-1] if t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 4 else t


def has(low: str, word: str) -> bool:
    """`word` (or its plural) as a whole word in the lowercased text."""
    b = re.escape(base(word))
    if b.endswith("y"):                                     # "study" ~ "studies"
        b = f"(?:{b}|{b[:-1]}ies)"
    return re.search(rf"(?<!\w){b}(?:s|es)?(?!\w)", low) is not None


def _words(text: str) -> list[str]:
    return [t for t in index.tokenize(text) if len(t) > 2]


def topic(analysis) -> set[str]:
    """The company's topic words: its search query and keywords ("continuous glucose monitoring CGM sensor")."""
    return {base(t) for t in _words(" ".join([analysis.search_query, *analysis.keywords])) if t not in FILLER}


def parts(need: str, topic_words: set[str]) -> tuple[list[str], list[list[str]]]:
    """(kind words, topic phrases) of a need. Consecutive topic words form one phrase ("contrast agents")."""
    kind, runs, run = [], [], []
    for t in _words(need):
        if t in FILLER:
            if run:
                runs.append(run)
                run = []
        elif base(t) in topic_words:
            run.append(t)
        else:
            kind.append(t)
            if run:
                runs.append(run)
                run = []
    if run:
        runs.append(run)
    return list(dict.fromkeys(kind)), runs


def supports(text: str, need: str, topic_words: set[str]) -> bool:
    """Does this text (an asset's own pages) show the need: its kind, and its topic phrase if the need names one?"""
    low = text.lower()
    kind, runs = parts(need, topic_words)
    on_topic = not runs or any(all(has(low, w) for w in r) for r in runs)
    if not kind:                     # the need only names the topic ("CGM sensors")
        return bool(runs) and on_topic
    return on_topic and any(has(low, w) for w in kind)


def mentioned(sentence: str, need: str, topic_words: set[str]) -> bool:
    """Does a sentence of the offer talk about this need (names one of its kind words)?"""
    low = sentence.lower()
    return any(has(low, w) for w in parts(need, topic_words)[0])


def pairs(analysis, assets: dict[str, str]) -> dict[str, list[str]]:
    """{need: [asset ids whose text supports it]}, for every stated need (an empty list: nobody in Bern shows it).
    `assets`: {asset id: the asset's own text}."""
    tw = topic(analysis)
    return {n: [aid for aid, text in assets.items() if supports(text, n, tw)]
            for n in analysis.company_needs if n.strip()}
