from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from typing import Literal
import hmac

from . import knowledge, knowledge_access
from . import analytics, cases, complementarity, vault_api, vault

router = APIRouter()


@router.get('/kb/analytics')
def metrics(response: Response, user=Depends(knowledge_access.require_member)):
    response.headers['Cache-Control'] = 'no-store'
    return analytics.build()


class Progress(BaseModel):
    stage: Literal['prospect', 'opportunity', 'collaboration', 'established']
    evidence: str = Field(default='', max_length=4000)


@router.put('/kb/leads/{entry_id}/progress')
def record_progress(entry_id: str, body: Progress, user=Depends(knowledge_access.require_member)):
    if not cases.get(entry_id):
        raise HTTPException(404, 'Lead not found')
    if body.stage in ('collaboration', 'established') and len(body.evidence.strip()) < 10:
        raise HTTPException(422, 'Record supporting evidence before confirming this outcome.')
    return analytics.set_progress(entry_id, body.stage, body.evidence, user['email'])


class Login(BaseModel):
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PreviewRole(BaseModel):
    role: Literal['agent', 'representative']


@router.patch('/staff/preview-role')
def preview_role(body: PreviewRole, request: Request, response: Response, user=Depends(knowledge_access.require_member)):
    if not user.get('preview'):
        raise HTTPException(403, 'Roles are configured by the operator for real accounts.')
    signature = hmac.new(knowledge_access.KEY, body.role.encode(), 'sha256').hexdigest()
    response.set_cookie('bern_preview_role', body.role + '.' + signature, httponly=True, samesite='strict')
    return {'ok': True}


@router.get("/staff/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return knowledge_access.member(request) or {"can_manage_knowledge": False}


@router.post("/staff/session")
def login(body: Login, request: Request, response: Response):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Cross-origin login is not allowed.")
    token = knowledge_access.login(body.email, body.password, request.client.host if request.client else "unknown")
    response.set_cookie(knowledge_access.COOKIE, token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=28800)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.delete("/staff/session")
def logout(response: Response, user=Depends(knowledge_access.require_member)):
    response.delete_cookie(knowledge_access.COOKIE)
    return {"ok": True}


@router.get("/kb/companies")
def companies(response: Response, user=Depends(knowledge_access.require_member)):
    response.headers["Cache-Control"] = "no-store"
    return knowledge.list_entries()


@router.post("/kb/companies", status_code=202)
def create(body: knowledge.KnowledgeInput, background: BackgroundTasks, user=Depends(knowledge_access.require_member)):
    try:
        vault.validate_references(body.documents)
    except vault.VaultError as e:
        raise HTTPException(422, str(e)) from None
    record = knowledge.save(body, user["email"])
    background.add_task(knowledge.process, record["id"], record["revision"])
    return record


@router.put("/kb/companies/{entry_id}", status_code=202)
def update(entry_id: str, body: knowledge.KnowledgeInput, background: BackgroundTasks, user=Depends(knowledge_access.require_member)):
    try:
        vault.validate_references(body.documents)
    except vault.VaultError as e:
        raise HTTPException(422, str(e)) from None
    if not knowledge.get(entry_id):
        raise HTTPException(404, "Company not found")
    record = knowledge.save(body, user["email"], entry_id)
    background.add_task(knowledge.process, record["id"], record["revision"])
    return record


@router.delete("/kb/companies/{entry_id}")
def delete(entry_id: str, user=Depends(knowledge_access.require_member)):
    knowledge.delete(entry_id)
    return {"ok": True}


@router.get("/kb/search")
def search(response: Response, q: str = Query(min_length=2, max_length=500), scope: Literal["bern", "north"] = "bern", user=Depends(knowledge_access.require_member)):
    response.headers["Cache-Control"] = "no-store"
    return complementarity.retrieve(q, scope=scope)


@router.post("/kb/documents")
async def upload(request: Request, name: str = Query(min_length=1, max_length=200), user=Depends(knowledge_access.require_member)):
    return await vault_api.upload(request, name, user)
