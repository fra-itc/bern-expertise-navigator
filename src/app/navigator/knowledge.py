"""Private platform knowledge, separate from the public institutional index."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import company, documents as docs, index, plain
from .config import DATA_DIR

DB = DATA_DIR / "knowledge.db"


class KnowledgeInput(BaseModel):
    discovery_candidate_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    name: str = Field(min_length=1, max_length=200)
    links: list[str] = Field(default_factory=list, max_length=12)
    documents: list[docs.Document] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=12000)
    canton: str = Field(default="", max_length=60)
    sector: Literal["", "tech", "medical", "manufacturing", "consulting", "energy", "other"] = ""
    topics: list[str] = Field(default_factory=list, max_length=20)
    lang: str = Field(default="en", pattern="^(en|de|fr)$")

    @field_validator('topics')
    @classmethod
    def clean_topics(cls, values):
        return list(dict.fromkeys(value.strip()[:100] for value in values if value.strip()))

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Company name is required")
        return value.strip()

    @field_validator("links")
    @classmethod
    def clean_links(cls, values):
        out = []
        for value in values:
            if re.match(r"^[a-z][a-z0-9+.-]*:", value.strip(), re.I) and not re.match(r"^https?://", value.strip(), re.I):
                raise ValueError("Only HTTP and HTTPS links are accepted")
            value = company.normalise(value)
            url = urlsplit(value)
            if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
                raise ValueError("Use a public website or social URL")
            if url.port not in (None, 80, 443) or any(char.isspace() for char in url.netloc):
                raise ValueError("Use a public website on port 80 or 443")
            if len(value) > 1000:
                raise ValueError("URL is too long")
            if value not in out:
                out.append(value)
        return out


def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, revision TEXT NOT NULL, body TEXT NOT NULL)")
    return conn


def list_entries():
    with connection() as conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT body FROM knowledge ORDER BY rowid DESC")]


def get(entry_id):
    with connection() as conn:
        row = conn.execute("SELECT body FROM knowledge WHERE id=?", (entry_id,)).fetchone()
    return json.loads(row[0]) if row else None


def save(body: KnowledgeInput, actor: str, entry_id: str | None = None):
    entry_id = entry_id or uuid.uuid4().hex
    revision = uuid.uuid4().hex
    record = {**body.model_dump(), "id": entry_id, "revision": revision, "actor": actor,
              "updated_at": datetime.now(timezone.utc).isoformat(), "status": "queued",
              "sources": [], "errors": [], "profile": None, "matches": [], "match_message": ""}
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO knowledge VALUES (?, ?, ?)",
                     (entry_id, revision, json.dumps(record)))
    return record


def delete(entry_id):
    with connection() as conn:
        conn.execute("DELETE FROM knowledge WHERE id=?", (entry_id,))


def _update(record):
    # Late background jobs cannot overwrite a newer edit or recreate a deleted entry.
    with connection() as conn:
        changed = conn.execute("UPDATE knowledge SET body=? WHERE id=? AND revision=?",
                               (json.dumps(record), record["id"], record["revision"])).rowcount
    return bool(changed)


def process(entry_id, revision):
    record = get(entry_id)
    if not record or record["revision"] != revision:
        return
    record["status"] = "processing"
    if not _update(record):
        return
    try:
        for link in record["links"]:
            try:
                site = company.read(link)  # includes robots and public-address checks
                record["sources"].append({"url": site.url, "text": site.text, "pages": [p.model_dump() for p in site.pages]})
            except company.FetchError as exc:
                record["errors"].append({"url": link, "message": str(exc)})
        text = "\n\n".join([record["notes"], *(d["text"] for d in record["documents"]), *(s["text"] for s in record["sources"])])
        if not text.strip():
            record["status"] = "error"
            record["errors"].append({"message": "Add readable sources, a document or notes before processing."})
        else:
            profile = plain.analyze_company(record["name"], "", text[:60000], lang=record["lang"])
            record["profile"] = profile.model_dump()
            record["status"] = "partial" if record["errors"] else "ready"
    except Exception:
        record["status"] = "error"
        record["errors"].append({"message": "Processing failed. Your saved sources are preserved; save again to retry."})
    _update(record)


NORTH_CANTONS = {"Bern", "Solothurn", "Aargau", "Basel-Stadt", "Basel-Landschaft", "Zurich", "Lucerne"}


def retrieve(query: str, limit=8, scope="bern"):
    """Source-backed private context for a staff lead; never fed to public search."""
    terms = set(index.tokenize(query))
    hits = []
    for record in list_entries():
        allowed = {"Bern"} if scope == "bern" else NORTH_CANTONS
        if record.get("canton") not in allowed:
            continue
        if record["status"] not in ("ready", "partial"):
            continue
        sources = [*( {"label": s["url"], "text": s["text"], "url": s["url"]} for s in record["sources"] ),
                   *( {"label": d["name"], "text": d["text"]} for d in record["documents"] )]
        if record["notes"]:
            sources.append({"label": "Staff notes", "text": record["notes"]})
        for source in sources:
            # Score evidence passages, not generated summaries.
            for offset in range(0, len(source["text"]), 600):
                snippet = source["text"][offset:offset + 600]
                score = len(terms & set(index.tokenize(snippet)))
                if score:
                    hits.append({"company": record["name"], "canton": record["canton"], "id": record["id"], "source": source["label"],
                                 "url": source.get("url"), "snippet": snippet, "score": score})
    return sorted(hits, key=lambda hit: hit["score"], reverse=True)[:limit]
