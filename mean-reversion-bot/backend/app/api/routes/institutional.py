"""Protected, bounded offline analyses; no broker adapter or database writes."""
import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, Request

from app.institutional.service import OPERATIONS, analyze

router = APIRouter()
_slots = threading.BoundedSemaphore(2)
MAX_BODY_BYTES = 2_000_000


@router.get("/capabilities")
def capabilities():
    return {"mode": "offline_research", "live_authorized": False,
            "operations": {name: schema.model_json_schema() for name, (schema, _) in OPERATIONS.items()}}


def _run(operation, body):
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, "Two analyses are already running; retry after completion")
    try:
        return analyze(operation, body)
    finally:
        _slots.release()


@router.post("/{operation}")
async def run_analysis(operation: str, request: Request):
    if operation not in OPERATIONS:
        raise HTTPException(404, "Unknown analysis")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY_BYTES:
            raise HTTPException(413, "Analysis input is limited to 2 MB; use the offline CLI")
    try:
        body = json.loads(data)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
        return await asyncio.to_thread(_run, operation, body)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc
