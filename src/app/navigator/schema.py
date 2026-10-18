"""Data contracts. Every claim carries the snippet it came from (traceability by construction)."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["person", "unit", "project", "infrastructure"]
PageType = Literal["person", "unit", "project", "infrastructure", "other"]


LinkKind = Literal["internal", "external", "paper"]
PaperScheme = Literal["doi", "pubmed", "pmc", "arxiv", "boris", "pdf"]


class PaperRef(BaseModel):
    """A scholarly work a page links to; `id` is normalised per scheme (DOI lowercase, 'PMC123', ...)."""
    scheme: PaperScheme
    id: str
    url: str = Field(description="Canonical URL for the work (doi.org, pubmed, arxiv.org/abs, ...)")


class Link(BaseModel):
    url: str = Field(description="Absolute, normalised (no fragment, lowercase scheme/host)")
    text: str = ""
    kind: LinkKind
    paper_ref: PaperRef | None = None


class Page(BaseModel):
    url: str
    source: str
    title: str = ""
    text: str
    fetched_at: str
    lang: str | None = None
    page_type: PageType | None = None
    # Outgoing links (added later: pages saved before this field load with links=[])
    links: list[Link] = []


# ---- What Apertus must return (constrained JSON) ---------------------------
class Cited(BaseModel):
    value: str = Field(description="The extracted value, as written on the page")
    snippet: str = Field(description="Verbatim sentence from the page that supports the value")


class ExtractedEntity(BaseModel):
    entity_type: EntityType
    name: Cited
    role: Cited | None = None
    unit: Cited | None = Field(None, description="Research group / lab / division the entity belongs to")
    institute: Cited | None = Field(None, description="Institute, centre, department or clinic")
    email: Cited | None = None
    expertise: list[Cited] = []
    projects: list[Cited] = []
    infrastructure: list[Cited] = []
    description: list[Cited] = Field([], description="Up to 2 sentences from the page describing this entity's research or offer")


class Extraction(BaseModel):
    entities: list[ExtractedEntity] = []


# ---- What we store and index ------------------------------------------------
class Evidence(BaseModel):
    field: str
    value: str
    snippet: str
    url: str


class Entity(BaseModel):
    id: str
    entity_type: EntityType
    name: str
    role: str | None = None
    unit: str | None = None
    institute: str | None = None
    email: str | None = None
    expertise: list[str] = []
    projects: list[str] = []
    infrastructure: list[str] = []
    description: list[str] = []
    source: str
    source_label: str
    source_urls: list[str]
    evidence: list[Evidence]
    retrieved_at: str
    extractor: str = "apertus"

    def search_text(self) -> str:
        parts = [self.name, self.role or "", self.unit or "", self.institute or "", *self.expertise,
                 *self.projects, *self.infrastructure, *(e.snippet for e in self.evidence)]
        return " \n".join(dict.fromkeys(p for p in parts if p))


# ---- Papers (OpenAlex), see papers.py ----------------------------------------
class PaperAuthor(BaseModel):
    """One authorship of a work, in OpenAlex order; `entity_id` is set when the author was matched to a person."""
    position: int
    author_position: str | None = None      # OpenAlex: first / middle / last
    author_id: str | None = None            # short OpenAlex id, 'A5012345678'
    name: str = ""
    institutions: list[str] = []            # short OpenAlex institution ids
    entity_id: str | None = None


class EntityLink(BaseModel):
    """Why a work belongs to an entity: an OpenAlex authorship of its matched author, or a link on its own page."""
    entity_id: str
    relation: Literal["author", "page_link"]
    position: int | None = None
    author_id: str | None = None
    page_url: str | None = None


_UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")


def clean_text(s: str) -> str:
    """Drops NUL and lone UTF-16 surrogates: Postgres text rejects the first, UTF-8 encoding fails on the second."""
    return _UNSTORABLE.sub("", s)


class Work(BaseModel):
    id: str                                 # short OpenAlex work id, 'W123'
    doi: str | None = None                  # lowercase, without https://doi.org/
    title: str = ""
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None             # rebuilt from abstract_inverted_index
    authors: list[PaperAuthor] = []
    topics: list[dict] = []                 # [{id, display_name, score, subfield, field}]
    concepts: list[dict] = []               # [{id, display_name, score}]
    cited_by_count: int = 0
    referenced_works: list[str] = []        # short ids only
    is_oa: bool = False
    oa_status: str | None = None
    pdf_urls: list[str] = []                # pdf_url of OA locations, best_oa_location first
    landing_url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    links: list[EntityLink] = []
    pdf_url: str | None = None              # the PDF actually downloaded
    pdf_sha1: str | None = None             # file name in data/papers/pdf/ (sha1 of pdf_url)
    fulltext_chars: int | None = None
    fulltext_status: str | None = None      # ok / not_oa / no_pdf_url / robots_disallowed / too_large / ...
    fetched_at: str

    def url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else (self.landing_url or f"https://openalex.org/{self.id}")


class AuthorMatch(BaseModel):
    """Audit record of one person <-> OpenAlex author decision (nav.author_match)."""
    entity_id: str
    entity_name: str
    candidates: list[dict]
    chosen_author_id: str | None = None
    decided_by: Literal["llm", "rules", "known_id"]   # known_id: the entity came from OpenAlex with its author id
    reason: str
    model: str | None = None


# ---- What the API returns (the challenge's required fields) ----------------
class SourceRef(BaseModel):
    url: str
    snippet: str
    field: str | None = None
    retrieved_at: str | None = None


class Affiliation(BaseModel):
    unit: str | None = None          # group / lab
    institute: str | None = None     # institute / centre / department
    institution: str                 # the source site (UniBE, ARTORG, DCB, ...)


class SearchResult(BaseModel):
    id: str
    person_or_unit: str
    entity_type: EntityType
    role: str | None
    affiliation: Affiliation
    institution: str
    expertise: list[str]
    projects: list[str]
    infrastructure_services: list[str]
    description: str | None = None
    contact: str | None
    why_match: str
    related: list[str] = Field([], description="Linked people/units from the same source (person <-> unit graph)")
    via: str | None = Field(None, description="Set when the result was found through a linked unit/project")
    sources: list[SourceRef]
    score: float
    confidence: float = Field(description="0-1, semantic similarity of the query to the entity's evidence")


class RelatedRef(BaseModel):
    id: str
    name: str
    entity_type: EntityType
    role: str | None = None


class EntityDetail(BaseModel):
    entity: Entity
    related: list[RelatedRef]


class SearchResponse(BaseModel):
    query: str
    expanded_terms: list[str]
    abstained: bool
    message: str | None = None
    results: list[SearchResult]
    took_ms: int = 0
    llm_used: bool = False
