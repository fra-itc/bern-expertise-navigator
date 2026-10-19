"""Member-only routes; responses force attachment and never expose a disk path."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from . import documents, knowledge, knowledge_access, vault, cases

router = APIRouter()


def referenced_ids():
    references = {document["original_id"] for entry in knowledge.list_entries()
                  for document in entry.get("documents", []) if document.get("original_id")}
    references.update(d.original_id for case in cases.list_cases() for d in case.documents if d.original_id)
    return references


async def upload(request: Request, name: str = Query(min_length=1, max_length=200),
                 user=Depends(knowledge_access.require_member)):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > documents.MAX_BYTES:
            raise HTTPException(413, "Document exceeds upload size limit")
    try:
        return await run_in_threadpool(vault.store, name, bytes(data), user["email"])
    except (documents.DocumentError, vault.VaultError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/kb/originals/{identifier}")
def download(identifier: str, user=Depends(knowledge_access.require_member)):
    try:
        metadata, payload = vault.retrieve(identifier)
    except vault.VaultError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(payload, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(metadata["name"], safe=""),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/kb/originals/{identifier}")
def delete(identifier: str, user=Depends(knowledge_access.require_member)):
    try:
        vault.remove(identifier, referenced_ids())
    except vault.VaultError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True}
