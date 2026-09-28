"""Local read-only multi-asset scanner controls. Never broker execution."""
import threading
import asyncio
from typing import Literal
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from app.api.routes.mt5 import local_only, get_runner
from app.quant.scanner import Scanner, ScanConfig
from app.quant.scanner_mappings import MappingRequest, compare_mappings
from app.api.routes.instrument_catalog import lookup
from app.database.session import get_db
from app.quant.paper_evidence import evidence_page

router = APIRouter(dependencies=[Depends(local_only)])
_lock = threading.Lock()


def scanner(request: Request):
    with _lock:
        if not hasattr(request.app.state, 'scanner'):
            request.app.state.scanner = Scanner()
        return request.app.state.scanner


@router.get('')
def status(store=Depends(scanner)):
    return store.status()


@router.post('/start')
def start(body: ScanConfig, request: Request, store=Depends(scanner)):
    for asset in body.assets:
        if asset.mapping_id:
            mapping_or_404(store, asset.mapping_id)
    return store.start(body, get_runner(request), request.state.role)


@router.post('/stop')
def stop(store=Depends(scanner)):
    return store.stop()


@router.get('/ledger')
def ledger(store=Depends(scanner)):
    return store.ledger()


@router.get('/paper-evidence')
async def paper_evidence(source: Literal['manual', 'scanner'] = 'scanner',
                         limit: int = Query(50, ge=1, le=200),
                         cursor: str | None = Query(None, max_length=4096),
                         store=Depends(scanner), db=Depends(get_db)):
    return await evidence_page(source, limit, cursor, db, store)


@router.get('/analytics')
def analytics(store=Depends(scanner)):
    return store.analytics()


@router.get('/records')
def records(kind: Literal['observations', 'trades'] = 'observations',
            limit: int = Query(50, ge=1, le=200),
            before: int | None = Query(None, ge=0),
            through: int | None = Query(None, ge=0), store=Depends(scanner)):
    return store.records(kind, limit, before, through)


@router.get('/export')
def export(store=Depends(scanner)):
    return StreamingResponse(store.export(), media_type='application/json',
                             headers={'Content-Disposition': 'attachment; filename="scanner-evidence.json"',
                                      'Cache-Control': 'no-store'})


@router.post('/mappings')
async def register_mapping(body: MappingRequest, request: Request, store=Depends(scanner), db=Depends(get_db)):
    if request.state.role != 'admin':
        raise HTTPException(403, 'Only admin can register scanner mappings')
    _, spec = await lookup(db, body.spec_hash)
    try:
        record, created = await asyncio.to_thread(store.mappings.register, body, spec, request.state.role)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse(record, status_code=201 if created else 200)


@router.get('/mappings')
def mappings(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100000), store=Depends(scanner)):
    return {'mappings': store.mappings.list(limit, offset)}


def mapping_or_404(store, key):
    try:
        return store.mappings.get(key)
    except KeyError as exc:
        raise HTTPException(404, 'Instrument mapping not found') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/mappings/compare')
def mapping_comparison(left: str, right: str, store=Depends(scanner)):
    return compare_mappings(mapping_or_404(store, left), mapping_or_404(store, right))


@router.get('/mappings/{mapping_id}')
def mapping_detail(mapping_id: str, store=Depends(scanner)):
    return mapping_or_404(store, mapping_id)
