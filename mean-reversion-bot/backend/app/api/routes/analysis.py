"""Local asynchronous research workflows; authorization is enforced by API middleware."""
import json
import threading
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.api.routes.mt5 import local_only, get_runner
from app.quant.jobs import AnalysisJobs
from app.quant.schemas import AnalysisRequest

router = APIRouter(dependencies=[Depends(local_only)])
_lock = threading.Lock()


def jobs(request: Request):
    with _lock:
        if not hasattr(request.app.state,'analysis_jobs'):
            request.app.state.analysis_jobs = AnalysisJobs()
        return request.app.state.analysis_jobs


@router.post('/runs', status_code=202)
async def create(request: Request, store=Depends(jobs)):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>20*1024*1024:
            raise HTTPException(413,'Analysis input limit is 20 MB')
    try:
        body = AnalysisRequest.model_validate(json.loads(data))
        runner = get_runner(request) if body.source=='mt5' else None
        if runner is not None:
            with runner.lock:
                runner._require_connection()
        return store.create(body,runner)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get('/runs')
def history(store=Depends(jobs)):
    return store.history()


@router.get('/runs/{run_id}')
def result(run_id: str, store=Depends(jobs)):
    try:
        store.recover()
        return store.get(run_id)
    except KeyError:
        raise HTTPException(404,'Analysis not found')


@router.get('/runs/{run_id}/artifact')
def artifact(run_id: str, store=Depends(jobs)):
    try:
        return store.get(run_id,artifacts=True)
    except KeyError:
        raise HTTPException(404,'Analysis not found')


@router.post('/runs/{run_id}/cancel')
def cancel(run_id: str, store=Depends(jobs)):
    try:
        return store.cancel(run_id)
    except KeyError:
        raise HTTPException(404,'Analysis not found')


class CandidateRequest(BaseModel):
    symbol: str = Field(min_length=1,max_length=128)


@router.post('/runs/{run_id}/candidate')
def candidate(run_id: str, body: CandidateRequest, request: Request, store=Depends(jobs)):
    try:
        evidence = store.candidate(run_id,body.symbol)
        return get_runner(request).adopt_research_candidate(evidence)
    except KeyError:
        raise HTTPException(404,'Analysis not found')
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
