"""Relation rules of the expertise graph — ONE place, used by both storage backends.

The file backend materialises them as an undirected adjacency list (what search.py has always
used); the Postgres backend writes the same pairs as typed edges into the AGE graph
`expertise_graph`. Both are derived from `link_pairs`, so `related`/`propagate` see the same
neighbours in the same order whichever backend is active.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .extract import strip_accents, unit_key
from .schema import Entity


def link_pairs(ents: Iterable[Entity]) -> list[tuple[str, str]]:
    """(from_id, to_id) in emission order: an entity names a non-person entity of the same source
    in its unit / institute / projects (matched by unit_key). Same rule search.py always used."""
    ents = list(ents)
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in ents:
        if e.entity_type != "person":
            by_name[(e.source, unit_key(e.name))].append(e.id)
    out: list[tuple[str, str]] = []
    for e in ents:
        for target in (e.unit, e.institute, *e.projects):
            for tid in by_name.get((e.source, unit_key(target or "")), []):
                if tid != e.id:
                    out.append((e.id, tid))
    return out


def adjacency(ents: Iterable[Entity]) -> dict[str, list[str]]:
    """Undirected neighbour lists, first-seen order (identical to the historical search._graph)."""
    g: dict[str, list[str]] = defaultdict(list)
    for a, b in link_pairs(ents):
        g[a].append(b)
        g[b].append(a)
    return {k: list(dict.fromkeys(v)) for k, v in g.items()}


# ---- typed edges (Postgres/AGE) -------------------------------------------------
# Decision table: (type of the entity that names the link, type of the named entity)
#   -> (edge label, direction). "fwd" = namer -> named, "rev" = named -> namer.
# Every pair link_pairs can emit has exactly one row: no implicit default.
EDGE_RULES: dict[tuple[str, str], tuple[str, str]] = {
    ("person", "unit"): ("MEMBER_OF", "fwd"),
    ("person", "infrastructure"): ("MEMBER_OF", "fwd"),   # staff of a facility
    ("person", "project"): ("WORKS_ON", "fwd"),
    ("project", "unit"): ("PART_OF", "fwd"),
    ("project", "project"): ("PART_OF", "fwd"),
    ("unit", "unit"): ("PART_OF", "fwd"),
    ("unit", "project"): ("PART_OF", "rev"),              # unit lists its project -> project PART_OF unit
    ("infrastructure", "unit"): ("OPERATES", "rev"),      # facility's unit operates it
    ("infrastructure", "project"): ("PART_OF", "fwd"),
    ("infrastructure", "infrastructure"): ("PART_OF", "fwd"),
    ("unit", "infrastructure"): ("OPERATES", "fwd"),
    ("project", "infrastructure"): ("OPERATES", "fwd"),
}

LABEL = {"person": "Person", "unit": "Unit", "project": "Project", "infrastructure": "Infrastructure"}
STRUCTURAL = ("MEMBER_OF", "WORKS_ON", "PART_OF", "OPERATES")


@dataclass(frozen=True)
class Edge:
    rel: str
    src: str
    dst: str
    seq: int  # first emission index: ORDER BY seq reproduces adjacency() neighbour order


def typed_edges(ents: list[Entity]) -> list[Edge]:
    """One typed edge per unordered pair, carrying the index of its first emission."""
    by_id = {e.id: e for e in ents}
    seen: set[frozenset[str]] = set()
    out: list[Edge] = []
    for seq, (a, b) in enumerate(link_pairs(ents)):
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        rule = EDGE_RULES.get((by_id[a].entity_type, by_id[b].entity_type))
        if rule is None:  # link_pairs never targets a person; anything else is a rules gap
            raise ValueError(f"no edge rule for {by_id[a].entity_type} -> {by_id[b].entity_type}")
        rel, direction = rule
        src, dst = (a, b) if direction == "fwd" else (b, a)
        out.append(Edge(rel, src, dst, seq))
    return out


def topic_key(s: str) -> str:
    """Topic vertex identity: lowercase, accent-free, single spaces (no synonym merging here)."""
    return re.sub(r"\s+", " ", strip_accents(s).lower()).strip()
