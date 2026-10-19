"""Private original documents. Deploy on a private, access-controlled data volume.

Bytes are not encrypted by this module: use encrypted storage/backups and TLS in
deployment. Never mount this directory as static content. Cleanup requires an
explicit complete set of live references, and only removes old unreferenced files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from .config import DATA_DIR
from .documents import MAX_BYTES, DocumentError, read

ROOT = DATA_DIR / "private-originals"


class VaultError(ValueError):
    pass


def _root():
    if ROOT.is_symlink():
        raise VaultError("Unsafe document storage")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    return ROOT.resolve()


def _path(identifier, suffix):
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise VaultError("Invalid original document identifier")
    path = _root() / (identifier + suffix)
    if path.is_symlink() or path.resolve().parent != _root():
        raise VaultError("Unsafe document storage")
    return path


def _write(path, payload):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(payload)


def store(name: str, payload: bytes, actor: str):
    """Parse before retaining; filenames are metadata only, never storage paths."""
    if not payload or len(payload) > MAX_BYTES:
        raise DocumentError("The document is empty or exceeds the upload size limit.")
    filename = re.sub(r"[\x00-\x1f\x7f]", "", name.replace("\\", "/").split("/")[-1])[:200]
    document = read(filename, payload)
    identifier = uuid.uuid4().hex
    metadata = {"original_id": identifier, "name": filename, "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "created_at": time.time(), "actor": actor}
    data_path, meta_path = _path(identifier, ".bin"), _path(identifier, ".json")
    try:
        _write(data_path, payload)
        _write(meta_path, json.dumps(metadata).encode("utf-8"))
    except Exception:
        data_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise
    return {**document.model_dump(), "original_id": identifier, "original_size": len(payload),
            "original_sha256": metadata["sha256"]}


def retrieve(identifier: str):
    meta_path, data_path = _path(identifier, ".json"), _path(identifier, ".bin")
    try:
        metadata = json.loads(meta_path.read_text("utf-8"))
        if metadata.get("size", MAX_BYTES + 1) > MAX_BYTES or data_path.stat().st_size > MAX_BYTES:
            raise VaultError("Original document integrity check failed")
        payload = data_path.read_bytes()
    except FileNotFoundError:
        raise VaultError("Original document not found") from None
    except (ValueError, TypeError, OSError) as exc:
        raise VaultError("Original document unavailable") from exc
    if len(payload) != metadata.get("size") or hashlib.sha256(payload).hexdigest() != metadata.get("sha256"):
        raise VaultError("Original document integrity check failed")
    return metadata, payload


def remove(identifier: str, referenced_ids: set[str]):
    if identifier in referenced_ids:
        raise VaultError("The original is still referenced by a company")
    data_path, meta_path = _path(identifier, ".bin"), _path(identifier, ".json")
    data_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def validate_references(documents):
    for document in documents:
        if document.original_id:
            metadata, _ = retrieve(document.original_id)
            if document.original_sha256 != metadata['sha256'] or document.original_size != metadata['size']:
                raise VaultError('Original document reference does not match its stored metadata')


def cleanup(referenced_ids: set[str], older_than_seconds=7 * 86400):
    """Explicit maintenance operation; do not call with a partial reference list."""
    if older_than_seconds < 86400:
        raise VaultError("Keep staged originals for at least one day")
    removed = []
    for path in _root().glob("*.json"):
        identifier = path.stem
        if identifier in referenced_ids:
            continue
        metadata, _ = retrieve(identifier)
        if metadata["created_at"] < time.time() - older_than_seconds:
            remove(identifier, referenced_ids)
            removed.append(identifier)
    return removed
