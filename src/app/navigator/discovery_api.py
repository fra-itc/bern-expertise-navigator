"""Authenticated discovery endpoints; discovery never registers companies automatically."""
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from . import cases, discovery, knowledge_access
router=APIRouter(prefix='/discovery')
class Start(BaseModel):
    lead_id: str = Field(min_length=1,max_length=100)
    scope: Literal['bern','north']='bern'
    seed_urls: list[str] = Field(default_factory=list, max_length=12)
class Review(BaseModel):
    fields: dict[str,str]=Field(default_factory=dict,max_length=7)
    decision: Literal['draft','approved','rejected']='draft'
@router.get('/metrics')
def metrics(user=Depends(knowledge_access.require_member)):
    return discovery.metrics()
@router.get('/runs')
def runs(response:Response,lead_id:str|None=None,user=Depends(knowledge_access.require_member)):
    response.headers['Cache-Control']='no-store'
    return discovery.runs(lead_id)
@router.post('/runs',status_code=202)
def start(body:Start,background:BackgroundTasks,user=Depends(knowledge_access.require_member)):
    lead=cases.get(body.lead_id)
    if not lead: raise HTTPException(404,'Lead not found')
    try:
        seeds = discovery.knowledge.KnowledgeInput(name='Discovery', links=body.seed_urls).links
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    record=discovery.create(lead.id,body.scope,user['email'], seeds)
    context='Company: '+lead.company+'\nGoals: '+lead.need+'\n'+lead.request_text
    if lead.website: context+='\n'+lead.website.text[:10000]
    background.add_task(discovery.execute,record['id'],context)
    return record
@router.get('/runs/{run_id}')
def detail(run_id:str,response:Response,user=Depends(knowledge_access.require_member)):
    response.headers['Cache-Control']='no-store'
    r=discovery.detail(run_id)
    if not r: raise HTTPException(404,'Run not found')
    return r
@router.patch('/candidates/{candidate_id}')
def review(candidate_id:str,body:Review,user=Depends(knowledge_access.require_member)):
    if any(len(v)>3000 for v in body.fields.values()): raise HTTPException(422,'Field too long')
    try: return discovery.review(candidate_id,body.fields,body.decision,user['email'])
    except ValueError as e: raise HTTPException(422,str(e)) from e
@router.get('/candidates/{candidate_id}/export')
def export(candidate_id:str,user=Depends(knowledge_access.require_member)):
    try: return discovery.export(candidate_id)
    except ValueError as e: raise HTTPException(422,str(e)) from e
