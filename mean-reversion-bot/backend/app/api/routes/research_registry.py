"""Persisted, append-only offline research; existing role middleware applies."""
import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.api.routes.institutional import MAX_BODY_BYTES, _slots
from app.database.models import ResearchFamily, ResearchRun, ResearchOutcome
from app.database.session import get_db
from app.institutional.data import Record, fingerprint
from app.institutional.registry import (FamilyRequest, RunRequest, RegistryConflict,
    declare_family, reserve_run, finish_run, run_summary)
from app.institutional.service import analyze

router = APIRouter()
logger = logging.getLogger(__name__)


async def read_body(request: Request, schema):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY_BYTES:
            raise HTTPException(413, "Registry input is limited to 2 MB")
    try:
        return schema.model_validate(json.loads(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def family_summary(family):
    return {"family_id": family.family_id, "name": family.name, "hypothesis": family.hypothesis,
            "trial_keys": family.trial_keys, "created_at": family.created_at.isoformat() + "Z",
            "created_by_role": family.created_by_role}


@router.post("/families")
async def create_family(request: Request, db: AsyncSession = Depends(get_db)):
    body = await read_body(request, FamilyRequest)
    try:
        return family_summary(await declare_family(db, body, request.state.role))
    except RegistryConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/families")
async def families(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                   db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ResearchFamily).order_by(ResearchFamily.created_at.desc(),
        ResearchFamily.family_id.desc()).offset(offset).limit(limit))).scalars().all()
    return {"families": [family_summary(row) for row in rows]}


@router.get("/families/{family_id}")
async def family_manifest(family_id: str, db: AsyncSession = Depends(get_db)):
    family = await db.get(ResearchFamily, family_id)
    if family is None:
        raise HTTPException(404, "Family not found")
    rows = (await db.execute(select(ResearchRun, ResearchOutcome).outerjoin(ResearchOutcome)
        .options(defer(ResearchRun.input_payload), defer(ResearchOutcome.report))
        .where(ResearchRun.family_id == family_id).order_by(ResearchRun.created_at, ResearchRun.run_id))).all()
    runs = [run_summary(run, outcome) for run, outcome in rows]
    missing = [key for key in family.trial_keys if key not in {r["trial_key"] for r in runs}]
    return {**family_summary(family), "runs": runs, "unattempted_trial_keys": missing,
            "all_trials_terminal": not missing and all(r["status"] != "pending" for r in runs),
            "note": "Completeness covers this declared family only; it is not statistical or trading approval."}


def compute_reserved(operation, payload):
    try:
        return analyze(operation, payload)
    finally:
        _slots.release()


@router.post("/runs")
async def create_run(request: Request, db: AsyncSession = Depends(get_db)):
    body = await read_body(request, RunRequest)
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, "Two analyses are already running; retry after completion")
    worker_started = False
    try:
        try:
            run, created = await reserve_run(db, body, request.state.role)
        except RegistryConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        if created:
            report, error = None, None
            worker_started = True
            try:
                # A disconnected caller can leave a durable pending trial; the
                # thread still releases capacity when it ends. No blind reruns.
                report = await asyncio.shield(asyncio.to_thread(compute_reserved, body.operation, body.payload))
                if report["implementation_hash"] != run.implementation_hash or report["runtime"] != run.runtime:
                    report = None
                    error = "Implementation changed after reservation; declare a new trial"
            except (ValueError, ArithmeticError) as exc:
                error = str(exc)[:8000] or "Analysis validation failed"
            except Exception:
                logger.exception("Registered analysis failed: %s", run.run_id)
                error = "Unexpected analysis failure; inspect server logs"
            outcome = await finish_run(db, run.run_id, request.state.role, report=report, error=error)
        else:
            outcome = await db.get(ResearchOutcome, run.run_id)
        await db.refresh(run)  # A concurrent outcome conflict can roll back/expire ORM state.
        return JSONResponse(run_summary(run, outcome), status_code=201 if created else 200 if outcome else 202)
    finally:
        if not worker_started:
            _slots.release()


@router.get("/runs")
async def runs(family_id: str | None = None, operation: str | None = None,
               status: Literal["pending", "succeeded", "failed", "aborted"] | None = None,
               q: str = Query("", max_length=128), limit: int = Query(25, ge=1, le=100),
               offset: int = Query(0, ge=0, le=100000), db: AsyncSession = Depends(get_db)):
    query = select(ResearchRun, ResearchOutcome).outerjoin(ResearchOutcome).options(
        defer(ResearchRun.input_payload), defer(ResearchOutcome.report))
    if family_id:
        query = query.where(ResearchRun.family_id == family_id)
    if operation:
        query = query.where(ResearchRun.operation == operation)
    if status:
        query = query.where(ResearchOutcome.run_id.is_(None) if status == "pending" else ResearchOutcome.status == status)
    if q:
        query = query.where(ResearchRun.name.contains(q, autoescape=True))
    rows = (await db.execute(query.order_by(ResearchRun.created_at.desc(), ResearchRun.run_id.desc())
                            .offset(offset).limit(limit))).all()
    return {"runs": [run_summary(run, outcome) for run, outcome in rows]}


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    outcome = await db.get(ResearchOutcome, run_id)
    expected_request = {"family_id": run.family_id, "trial_key": run.trial_key,
                        "name": run.name, "operation": run.operation, "dataset_version": run.dataset_version,
                        "parent_run_id": run.parent_run_id, "payload": run.input_payload}
    if fingerprint(expected_request) != run.request_hash:
        raise HTTPException(409, "Stored request failed its integrity check")
    if outcome and outcome.report is not None and fingerprint(outcome.report) != outcome.artifact_hash:
        raise HTTPException(409, "Stored artifact failed its integrity check")
    return JSONResponse({"registry": run_summary(run, outcome), "input_payload": run.input_payload,
                         "report": outcome.report if outcome else None},
                        headers={"Content-Disposition": f'attachment; filename="research-{run.run_id}.json"'})


class Resolution(Record):
    evidence: str = Field(min_length=20, max_length=4000)


@router.post("/runs/{run_id}/resolve")
async def resolve_run(run_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # The shared middleware reserves all /resolve actions for admin.
    body = await read_body(request, Resolution)
    run = await db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if await db.get(ResearchOutcome, run_id):
        raise HTTPException(409, "Run already has an immutable terminal outcome")
    outcome = await finish_run(db, run_id, request.state.role, error=body.evidence, aborted=True)
    await db.refresh(run)
    return run_summary(run, outcome)
