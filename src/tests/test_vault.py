import json
import time

import pytest

from navigator import documents, vault


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "ROOT", tmp_path / "private-originals")
    return vault.ROOT


def test_original_roundtrip_and_filename_is_metadata(storage):
    result = vault.store("../../notes.txt", b"Clinical research notes. with sufficient detailed information about the clinical research programme.", "officer@example.test")
    metadata, payload = vault.retrieve(result["original_id"])
    assert payload == b"Clinical research notes. with sufficient detailed information about the clinical research programme."
    assert metadata["name"] == "notes.txt"
    assert result["text"] == "Clinical research notes. with sufficient detailed information about the clinical research programme."
    assert result["original_sha256"] == metadata["sha256"]
    assert len(list(storage.iterdir())) == 2
    assert all(path.parent == storage for path in storage.iterdir())


def test_invalid_formats_are_not_retained(storage):
    with pytest.raises(documents.DocumentError):
        vault.store("unknown.exe", b"not a document", "officer")
    assert not storage.exists()


def test_integrity_and_traversal(storage):
    result = vault.store("notes.txt", b"Original content with sufficient detailed information about the clinical research programme.", "officer")
    (storage / (result["original_id"] + ".bin")).write_bytes(b"Modified content")
    with pytest.raises(vault.VaultError, match="integrity"):
        vault.retrieve(result["original_id"])
    with pytest.raises(vault.VaultError, match="identifier"):
        vault.retrieve("../../secret")


def test_reference_protection_and_staged_cleanup(storage):
    first = vault.store("first.txt", b"First document with sufficient detailed information about the clinical research programme.", "officer")["original_id"]
    second = vault.store("second.txt", b"Second document with sufficient detailed information about the clinical research programme.", "officer")["original_id"]
    for identifier in (first, second):
        path = storage / (identifier + ".json")
        metadata = json.loads(path.read_text())
        metadata["created_at"] = time.time() - 10 * 86400
        path.write_text(json.dumps(metadata))
    with pytest.raises(vault.VaultError, match="referenced"):
        vault.remove(first, {first})
    assert vault.cleanup({first}) == [second]
    assert vault.retrieve(first)[1] == b"First document with sufficient detailed information about the clinical research programme."


def test_original_routes_require_member(storage, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from navigator import knowledge_access, vault_api
    app = FastAPI()
    app.include_router(vault_api.router)
    app.post("/kb/documents")(vault_api.upload)
    client = TestClient(app)
    monkeypatch.setattr(knowledge_access, "member", lambda request: None)
    assert client.post("/kb/documents?name=notes.txt", content=b"Research notes with sufficient detailed information about the clinical research programme.").status_code == 403
    assert client.get("/kb/originals/" + "a" * 32).status_code == 403
    app.dependency_overrides[knowledge_access.require_member] = lambda: {"email": "officer@example.test"}
    result = client.post("/kb/documents?name=notes.txt", content=b"Research notes with sufficient detailed information about the clinical research programme.")
    assert result.status_code == 200
    identifier = result.json()["original_id"]
    response = client.get("/kb/originals/" + identifier)
    assert response.content == b"Research notes with sufficient detailed information about the clinical research programme."
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    monkeypatch.setattr(vault_api, "referenced_ids", lambda: {identifier})
    assert client.delete("/kb/originals/" + identifier).status_code == 409
