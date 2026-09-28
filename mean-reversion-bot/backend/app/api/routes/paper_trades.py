"""Protected hypothetical trade ledger; this router never submits orders."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PaperTrade
from app.database.session import get_db

router = APIRouter()


class PaperTradeIn(BaseModel):
    signal_id: str | None = Field(default=None, max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    timeframe: str = Field(min_length=1, max_length=8)
    direction: Literal['buy', 'sell']
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    quantity: float = Field(default=1, gt=0)
    score: int = Field(default=0, ge=0, le=100)
    regime: str = Field(default='unknown', max_length=32)
    reason: str = Field(default='', max_length=2000)


class PaperClose(BaseModel):
    exit_price: float = Field(gt=0)


def serialize(row: PaperTrade):
    return {key: getattr(row, key) for key in (
        'id', 'signal_id', 'symbol', 'timeframe', 'direction', 'entry_price',
        'stop_loss', 'take_profit', 'exit_price', 'quantity', 'pnl', 'score',
        'regime', 'reason', 'status', 'approval_status', 'created_by_role') } | {
        'created_at': row.created_at.isoformat(),
        'closed_at': row.closed_at.isoformat() if row.closed_at else None,
        'live_authorized': False,
    }


@router.get('')
async def list_paper_trades(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(PaperTrade.status == status)
    if symbol:
        stmt = stmt.where(PaperTrade.symbol == symbol)
    rows = (await db.execute(stmt)).scalars().all()
    return {'count': len(rows), 'trades': [serialize(row) for row in rows]}


@router.post('', status_code=201)
async def create_paper_trade(body: PaperTradeIn, request: Request, db: AsyncSession = Depends(get_db)):
    row = PaperTrade(id=str(uuid4()), created_by_role=request.state.role, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize(row)


@router.get('/analytics')
async def paper_analytics(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PaperTrade).where(PaperTrade.status == 'closed'))).scalars().all()
    pnl = [float(row.pnl or 0) for row in rows]

    def summary(items):
        values = [float(item.pnl or 0) for item in items]
        wins = sum(value for value in values if value > 0)
        losses = -sum(value for value in values if value < 0)
        return {'trades': len(values), 'wins': sum(value > 0 for value in values),
                'win_rate': sum(value > 0 for value in values) / len(values) if values else None,
                'total_pnl': sum(values), 'profit_factor': wins / losses if losses else None}

    def grouped(key):
        groups = {}
        for row in rows:
            value = key(row)
            groups.setdefault(value, []).append(row)
        return {str(value): summary(items) for value, items in sorted(groups.items(), key=lambda pair: str(pair[0]))}

    return {'sample_status': 'insufficient_sample' if len(rows) < 300 else 'reviewable',
            'overall': summary(rows), 'by_symbol': grouped(lambda row: row.symbol),
            'by_regime': grouped(lambda row: row.regime),
            'by_score_bucket': grouped(lambda row: f"{(row.score // 2) * 2}-{(row.score // 2) * 2 + 1}"),
            'session': {'status': 'not_recorded', 'note': 'Paper entries do not yet capture session metadata.'}}


@router.post('/{trade_id}/close')
async def close_paper_trade(trade_id: str, body: PaperClose, db: AsyncSession = Depends(get_db)):
    row = await db.get(PaperTrade, trade_id)
    if row is None:
        raise HTTPException(404, 'Paper trade not found')
    if row.status != 'open':
        raise HTTPException(409, 'Paper trade is already closed')
    row.exit_price = body.exit_price
    row.pnl = ((body.exit_price - row.entry_price) if row.direction == 'buy'
               else (row.entry_price - body.exit_price)) * row.quantity
    row.status = 'closed'
    row.closed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return serialize(row)


async def set_approval(trade_id: str, approval_status: str, db: AsyncSession):
    row = await db.get(PaperTrade, trade_id)
    if row is None:
        raise HTTPException(404, 'Paper trade not found')
    if row.status != 'open':
        raise HTTPException(409, 'Only open paper trades can change approval')
    row.approval_status = approval_status
    await db.commit()
    await db.refresh(row)
    return serialize(row)


@router.post('/{trade_id}/request-approval')
async def request_approval(trade_id: str, db: AsyncSession = Depends(get_db)):
    return await set_approval(trade_id, 'pending', db)


@router.post('/{trade_id}/approve')
async def approve_paper_trade(trade_id: str, db: AsyncSession = Depends(get_db)):
    return await set_approval(trade_id, 'approved', db)


@router.post('/{trade_id}/reject')
async def reject_paper_trade(trade_id: str, db: AsyncSession = Depends(get_db)):
    return await set_approval(trade_id, 'rejected', db)