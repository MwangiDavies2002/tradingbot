"""
trades.py  (API Router)
────────────────────────────────────────────────────────────────────────────────
Trades API — /api/trades
────────────────────────────────────────────────────────────────────────────────

ENDPOINTS:
    GET  /api/trades          Paginated trade history with filters
    GET  /api/trades/{id}     Single trade detail with full audit trail
    GET  /api/trades/stats    Aggregated performance statistics
    GET  /api/trades/export   CSV export of trade history
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Trade
from app.database.session import get_db

router = APIRouter()


# ── GET /api/trades ───────────────────────────────────────────────────────────

@router.get("")
async def list_trades(
    symbol:     Optional[str] = Query(None,  description="Filter by symbol"),
    direction:  Optional[str] = Query(None,  description="buy or sell"),
    status:     Optional[str] = Query(None,  description="open, closed, cancelled"),
    date_from:  Optional[datetime] = Query(None),
    date_to:    Optional[datetime] = Query(None),
    min_score:  Optional[int] = Query(None,  description="Minimum confluence score"),
    page:       int           = Query(1,     ge=1),
    page_size:  int           = Query(50,    ge=1, le=200),
    db:         AsyncSession  = Depends(get_db),
):
    """
    Paginated trade history with optional filters.
    Returns trades newest first.
    """
    stmt = select(Trade).order_by(Trade.opened_at.desc())

    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if direction:
        stmt = stmt.where(Trade.direction == direction)
    if status:
        stmt = stmt.where(Trade.status == status)
    if date_from:
        stmt = stmt.where(Trade.opened_at >= date_from)
    if date_to:
        stmt = stmt.where(Trade.opened_at <= date_to)
    if min_score is not None:
        stmt = stmt.where(Trade.confluence_score >= min_score)

    # Total count for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total      = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt    = stmt.offset((page - 1) * page_size).limit(page_size)
    result  = await db.execute(stmt)
    trades  = result.scalars().all()

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     (total + page_size - 1) // page_size,
        "trades": [_trade_to_dict(t) for t in trades],
    }


# ── GET /api/trades/stats ─────────────────────────────────────────────────────

@router.get("/stats")
async def trade_stats(
    symbol:    Optional[str]      = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to:   Optional[datetime] = Query(None),
    db:        AsyncSession       = Depends(get_db),
):
    """
    Aggregated performance statistics.
    Returns win rate, avg R:R, profit factor, total P&L.
    """
    stmt = select(Trade).where(Trade.status == "closed")
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if date_from:
        stmt = stmt.where(Trade.opened_at >= date_from)
    if date_to:
        stmt = stmt.where(Trade.opened_at <= date_to)

    result = await db.execute(stmt)
    trades = result.scalars().all()

    if not trades:
        return {"message": "No closed trades found", "stats": {}}

    total        = len(trades)
    wins         = [t for t in trades if (t.pnl or 0) > 0]
    losses       = [t for t in trades if (t.pnl or 0) <= 0]
    total_pnl    = sum(t.pnl or 0 for t in trades)
    gross_profit = sum(t.pnl for t in wins  if t.pnl)
    gross_loss   = abs(sum(t.pnl for t in losses if t.pnl))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win  = gross_profit / len(wins)   if wins   else 0
    avg_loss = gross_loss   / len(losses) if losses else 0
    avg_rr   = avg_win / avg_loss if avg_loss > 0 else 0

    close_reasons = {}
    for t in trades:
        r = t.close_reason or "unknown"
        close_reasons[r] = close_reasons.get(r, 0) + 1

    return {
        "stats": {
            "total_trades":   total,
            "winning_trades": len(wins),
            "losing_trades":  len(losses),
            "win_rate":       round(len(wins) / total, 4) if total else 0,
            "total_pnl":      round(total_pnl, 2),
            "gross_profit":   round(gross_profit, 2),
            "gross_loss":     round(gross_loss, 2),
            "profit_factor":  round(profit_factor, 3),
            "avg_win":        round(avg_win, 2),
            "avg_loss":       round(avg_loss, 2),
            "avg_rr":         round(avg_rr, 3),
            "close_reasons":  close_reasons,
        }
    }


# ── GET /api/trades/{trade_id} ────────────────────────────────────────────────

@router.get("/{trade_id}")
async def get_trade(trade_id: str, db: AsyncSession = Depends(get_db)):
    """Single trade detail with full indicator snapshot and score breakdown."""
    result = await db.execute(select(Trade).where(Trade.trade_id == trade_id))
    trade  = result.scalar_one_or_none()
    if not trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return _trade_to_dict(trade, full=True)


# ── GET /api/trades/export ────────────────────────────────────────────────────

@router.get("/export/csv")
async def export_trades_csv(
    symbol:    Optional[str]      = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to:   Optional[datetime] = Query(None),
    db:        AsyncSession       = Depends(get_db),
):
    """Export all matching trades as a downloadable CSV file."""
    stmt = select(Trade).order_by(Trade.opened_at.asc())
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if date_from:
        stmt = stmt.where(Trade.opened_at >= date_from)
    if date_to:
        stmt = stmt.where(Trade.opened_at <= date_to)

    result = await db.execute(stmt)
    trades = result.scalars().all()

    output  = io.StringIO()
    writer  = csv.writer(output)
    headers = [
        "trade_id", "symbol", "timeframe", "direction", "status",
        "entry_price", "exit_price", "stop_loss", "take_profit",
        "stake", "pnl", "pnl_pct", "confluence_score", "reason_code",
        "close_reason", "opened_at", "closed_at",
        "z_score", "rsi_value", "hurst_value", "lsl_wick_ratio",
    ]
    writer.writerow(headers)
    for t in trades:
        writer.writerow([
            t.trade_id, t.symbol, t.timeframe, t.direction, t.status,
            t.entry_price, t.exit_price, t.stop_loss, t.take_profit,
            t.stake, t.pnl, t.pnl_pct, t.confluence_score, t.reason_code,
            t.close_reason,
            t.opened_at.isoformat() if t.opened_at else "",
            t.closed_at.isoformat()  if t.closed_at  else "",
            t.z_score, t.rsi_value, t.hurst_value, t.lsl_wick_ratio,
        ])

    output.seek(0)
    filename = f"trades_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trade_to_dict(t: Trade, full: bool = False) -> dict:
    d = {
        "trade_id":        t.trade_id,
        "contract_id":     t.contract_id,
        "symbol":          t.symbol,
        "timeframe":       t.timeframe,
        "direction":       t.direction,
        "contract_type":   t.contract_type,
        "status":          t.status,
        "entry_price":     t.entry_price,
        "exit_price":      t.exit_price,
        "stop_loss":       t.stop_loss,
        "take_profit":     t.take_profit,
        "stake":           t.stake,
        "pnl":             t.pnl,
        "pnl_pct":         t.pnl_pct,
        "confluence_score": t.confluence_score,
        "reason_code":     t.reason_code,
        "close_reason":    t.close_reason,
        "opened_at":       t.opened_at.isoformat() if t.opened_at else None,
        "closed_at":       t.closed_at.isoformat()  if t.closed_at  else None,
    }
    if full:
        d.update({
            "breakdown":     t.breakdown_json,
            "z_score":       t.z_score,
            "rsi_value":     t.rsi_value,
            "bb_position":   t.bb_position,
            "vwap_dev":      t.vwap_dev,
            "stoch_k":       t.stoch_k,
            "hurst_value":   t.hurst_value,
            "atr_value":     t.atr_value,
            "lsl_wick_ratio": t.lsl_wick_ratio,
        })
    return d
