"""Administrative metadata registration and offline plans against pinned revisions."""
import asyncio
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.api.routes.institutional import _run
from app.api.routes.research_registry import read_body
from app.database.models import InstrumentRevision
from app.database.session import get_db
from app.institutional.catalog import CatalogConflict, register_spec, revision_summary, validated_spec
from app.institutional.instrument_planning import PlanInputs
from app.institutional.instruments import InstrumentSpec

router = APIRouter()


@router.post("/revisions")
async def register(request: Request, db: AsyncSession = Depends(get_db)):
    if request.state.role != "admin":
        raise HTTPException(403, "Only admin can register instrument specifications")
    spec = await read_body(request, InstrumentSpec)
    try:
        row, created = await register_spec(db, spec, request.state.role)
    except CatalogConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse(revision_summary(row), status_code=201 if created else 200)


@router.get("/revisions")
async def revisions(q: str = Query("", max_length=128), venue: str | None = None,
                    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                    db: AsyncSession = Depends(get_db)):
    query = select(InstrumentRevision).options(defer(InstrumentRevision.spec))
    if q:
        query = query.where(InstrumentRevision.instrument_id.contains(q, autoescape=True))
    if venue:
        query = query.where(InstrumentRevision.venue == venue)
    rows = (await db.execute(query.order_by(InstrumentRevision.registered_at.desc(), InstrumentRevision.spec_hash)
                            .offset(offset).limit(limit))).scalars().all()
    return {"revisions": [revision_summary(row) for row in rows]}


async def lookup(db, spec_hash):
    row = await db.get(InstrumentRevision, spec_hash)
    if row is None:
        raise HTTPException(404, "Instrument revision not found")
    try:
        spec = validated_spec(row)
    except ValueError as exc:
        raise HTTPException(409, "Stored instrument specification failed its integrity check") from exc
    return row, spec


@router.get("/revisions/{spec_hash}")
async def revision(spec_hash: str, db: AsyncSession = Depends(get_db)):
    row, spec = await lookup(db, spec_hash)
    return {**revision_summary(row), "spec": spec.model_dump(mode="json")}


class CatalogPlanRequest(PlanInputs):
    spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/plans")
async def plan(request: Request, db: AsyncSession = Depends(get_db)):
    body = await read_body(request, CatalogPlanRequest)
    row, spec = await lookup(db, body.spec_hash)
    payload = body.model_dump(mode="json", exclude={"spec_hash"}) | {"instrument": spec.model_dump(mode="json")}
    try:
        report = await asyncio.to_thread(_run, "instrument-plan", payload)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc
    observed_ms = int(row.registered_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
    return {"catalog": revision_summary(row), "catalog_observed_by_decision": observed_ms <= body.as_of_ms,
            "report": report, "live_authorized": False,
            "note": "Historical plans may use backfilled metadata. Publication times are source assertions, not verified point-in-time availability."}
