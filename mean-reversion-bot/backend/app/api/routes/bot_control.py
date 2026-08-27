"""
bot_control.py  — /api/bot
signals.py      — /api/signals
risk.py         — /api/risk
config.py       — /api/config
────────────────────────────────────────────────────────────────────────────────
Remaining API Routers
────────────────────────────────────────────────────────────────────────────────
All four routers in one file for now.
Split into separate files when each grows beyond 3-4 endpoints.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotEvent, ConfigEntry, EquitySnapshot, Signal
from app.database.session import get_db

# ══════════════════════════════════════════════════════════════════════════════
# BOT CONTROL  /api/bot
# ══════════════════════════════════════════════════════════════════════════════

router = APIRouter()   # re-exported; main.py imports each module separately

bot_control_router = APIRouter()


@bot_control_router.get("/status")
async def bot_status(db: AsyncSession = Depends(get_db)):
    """
    Current bot status: running state, circuit breaker, open trade count.
    Reads from the bot_events table for circuit breaker state and the
    app state for live metrics.
    """
    # Latest circuit breaker event
    stmt = (
        select(BotEvent)
        .where(BotEvent.event_type.like("circuit_breaker%"))
        .order_by(desc(BotEvent.ts))
        .limit(1)
    )
    result = await db.execute(stmt)
    cb_event = result.scalar_one_or_none()

    # Latest equity snapshot
    eq_stmt = select(EquitySnapshot).order_by(desc(EquitySnapshot.ts)).limit(1)
    eq_result = await db.execute(eq_stmt)
    latest_eq = eq_result.scalar_one_or_none()

    return {
        "bot_running":     True,   # Placeholder — replace with live bot.state
        "circuit_breaker": {
            "state":       cb_event.details_json.get("state", "active") if cb_event else "active",
            "last_trigger": cb_event.event_type if cb_event else None,
            "triggered_at": cb_event.ts.isoformat() if cb_event else None,
        },
        "equity": {
            "balance":    latest_eq.balance   if latest_eq else None,
            "daily_pnl":  latest_eq.daily_pnl if latest_eq else None,
            "open_trades": latest_eq.open_trades if latest_eq else 0,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@bot_control_router.post("/stop")
async def stop_bot(db: AsyncSession = Depends(get_db)):
    """
    Emergency stop / kill switch.
    Logs the event and signals the bot process to stop.
    NOTE: Wire this to the actual bot instance via app.state in production.
    """
    event = BotEvent(
        event_type="bot_stop_manual",
        severity="warning",
        message="Bot stopped via API kill switch",
        details_json={"source": "api", "ts": datetime.utcnow().isoformat()},
    )
    db.add(event)
    await db.commit()
    return {"status": "stop_signal_sent", "message": "Bot will stop after closing open positions"}


@bot_control_router.post("/start")
async def start_bot(db: AsyncSession = Depends(get_db)):
    """Signal the bot to start (or resume after a pause)."""
    event = BotEvent(
        event_type="bot_start_manual",
        severity="info",
        message="Bot started via API",
        details_json={"source": "api", "ts": datetime.utcnow().isoformat()},
    )
    db.add(event)
    await db.commit()
    return {"status": "start_signal_sent"}


@bot_control_router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(db: AsyncSession = Depends(get_db)):
    """
    Manually reset the circuit breaker after a HALT.
    Requires conscious operator action — not automated.
    """
    event = BotEvent(
        event_type="circuit_breaker_manual_reset",
        severity="warning",
        message="Circuit breaker manually reset by operator",
        details_json={"source": "api", "ts": datetime.utcnow().isoformat()},
    )
    db.add(event)
    await db.commit()
    return {"status": "circuit_breaker_reset", "new_state": "active"}


# ══════════════════════════════════════════════════════════════════════════════
# SIGNALS  /api/signals
# ══════════════════════════════════════════════════════════════════════════════

signals_router = APIRouter()


@signals_router.get("")
async def list_signals(
    symbol:   Optional[str]  = Query(None),
    fired:    Optional[bool] = Query(None, description="True=only fired, False=only skipped"),
    min_score: Optional[int] = Query(None),
    limit:    int            = Query(100, ge=1, le=500),
    db:       AsyncSession   = Depends(get_db),
):
    """Recent signal evaluations with indicator values."""
    stmt = select(Signal).order_by(desc(Signal.evaluated_at)).limit(limit)
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if fired is not None:
        stmt = stmt.where(Signal.fired == fired)
    if min_score is not None:
        stmt = stmt.where(Signal.score >= min_score)

    result  = await db.execute(stmt)
    signals = result.scalars().all()

    return {
        "count":   len(signals),
        "signals": [
            {
                "id":           s.id,
                "symbol":       s.symbol,
                "timeframe":    s.timeframe,
                "direction":    s.direction,
                "score":        s.score,
                "fired":        s.fired,
                "reason":       s.reason,
                "evaluated_at": s.evaluated_at.isoformat(),
                "eval_ms":      s.eval_ms,
                "indicators": {
                    "z_score":     s.z_score,
                    "rsi":         s.rsi,
                    "bb_position": s.bb_position,
                    "vwap_dev":    s.vwap_dev_atr,
                    "stoch_k":     s.stoch_k,
                    "hurst":       s.hurst,
                    "lsl_grab":    s.lsl_grab,
                    "bos_choch":   s.bos_choch,
                    "order_block": s.order_block,
                },
            }
            for s in signals
        ],
    }


@signals_router.get("/live")
async def live_signals():
    """
    Placeholder for live signal state.
    In production: read from Redis keys signal:{symbol}:{tf}.
    Replace with Redis read when connected.
    """
    return {
        "message": "Connect Redis to get live signal states",
        "keys_pattern": "signal:{symbol}:{timeframe}",
    }


# ══════════════════════════════════════════════════════════════════════════════
# RISK  /api/risk
# ══════════════════════════════════════════════════════════════════════════════

risk_router = APIRouter()


@risk_router.get("")
async def risk_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Risk dashboard: drawdown metrics, circuit breaker state, equity snapshots.
    """
    # Last 48 equity snapshots for mini chart
    eq_stmt = (
        select(EquitySnapshot)
        .order_by(desc(EquitySnapshot.ts))
        .limit(48)
    )
    eq_result = await db.execute(eq_stmt)
    snapshots = eq_result.scalars().all()
    snapshots = list(reversed(snapshots))  # chronological order

    # Last CB events
    cb_stmt = (
        select(BotEvent)
        .where(BotEvent.event_type.like("circuit_breaker%"))
        .order_by(desc(BotEvent.ts))
        .limit(10)
    )
    cb_result = await db.execute(cb_stmt)
    cb_events = cb_result.scalars().all()

    current_balance = snapshots[-1].balance if snapshots else None
    day_start_bal   = next(
        (s.balance for s in snapshots if s.note == "day_start"), current_balance
    )
    daily_pnl = (
        (current_balance - day_start_bal) if (current_balance and day_start_bal) else None
    )
    daily_dd_pct = (
        abs(daily_pnl) / day_start_bal
        if (daily_pnl and day_start_bal and daily_pnl < 0) else 0.0
    )

    return {
        "current_balance": current_balance,
        "daily_pnl":       round(daily_pnl, 2) if daily_pnl else None,
        "daily_drawdown_pct": round(daily_dd_pct * 100, 2),
        "equity_curve": [
            {
                "ts":      s.ts.isoformat(),
                "balance": s.balance,
                "daily_pnl": s.daily_pnl,
            }
            for s in snapshots
        ],
        "circuit_breaker_history": [
            {
                "event_type": e.event_type,
                "severity":   e.severity,
                "message":    e.message,
                "ts":         e.ts.isoformat(),
            }
            for e in cb_events
        ],
    }


@risk_router.get("/equity")
async def equity_curve(
    limit: int = Query(200, ge=10, le=1000),
    db:    AsyncSession = Depends(get_db),
):
    """Equity curve data points for charting."""
    stmt = (
        select(EquitySnapshot)
        .order_by(desc(EquitySnapshot.ts))
        .limit(limit)
    )
    result    = await db.execute(stmt)
    snapshots = list(reversed(result.scalars().all()))
    return {
        "count": len(snapshots),
        "points": [
            {"ts": s.ts.isoformat(), "balance": s.balance, "open_equity": s.open_equity}
            for s in snapshots
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG  /api/config
# ══════════════════════════════════════════════════════════════════════════════

config_router = APIRouter()


class ConfigUpdate(BaseModel):
    value: str
    description: Optional[str] = None


@config_router.get("")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Return all configuration entries (excludes secrets)."""
    EXCLUDED_KEYS = {"DERIV_API_TOKEN", "SECRET_KEY", "TELEGRAM_BOT_TOKEN"}
    stmt   = select(ConfigEntry).order_by(ConfigEntry.key)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return {
        "config": [
            {
                "key":         e.key,
                "value":       e.value if e.key not in EXCLUDED_KEYS else "***",
                "value_type":  e.value_type,
                "description": e.description,
                "updated_at":  e.updated_at.isoformat(),
            }
            for e in entries
        ]
    }


@config_router.put("/{key}")
async def update_config(
    key:    str,
    body:   ConfigUpdate,
    db:     AsyncSession = Depends(get_db),
):
    """Update a single config value. Restricted keys cannot be changed via API."""
    RESTRICTED = {"DERIV_API_TOKEN", "SECRET_KEY", "DATABASE_URL"}
    if key in RESTRICTED:
        raise HTTPException(status_code=403, detail=f"Key {key!r} cannot be updated via API")

    stmt   = select(ConfigEntry).where(ConfigEntry.key == key)
    result = await db.execute(stmt)
    entry  = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail=f"Config key {key!r} not found")

    entry.value      = body.value
    entry.updated_at = datetime.utcnow()
    if body.description:
        entry.description = body.description

    await db.commit()
    return {"status": "updated", "key": key, "new_value": body.value}


@config_router.get("/{key}")
async def get_config_key(key: str, db: AsyncSession = Depends(get_db)):
    """Get a single config value by key."""
    stmt   = select(ConfigEntry).where(ConfigEntry.key == key)
    result = await db.execute(stmt)
    entry  = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Config key {key!r} not found")
    return {
        "key":        entry.key,
        "value":      entry.get_typed_value(),
        "value_type": entry.value_type,
        "updated_at": entry.updated_at.isoformat(),
    }


# ── Export all routers so main.py can import them ─────────────────────────────
# main.py does: from app.api.routes import bot_control, signals, risk, config
# and each module exposes its router as `router`.

# Since all four live in one file, we alias here:
bot_router     = bot_control_router    # noqa: F841  (imported as bot_control.router in main)
signals_export = signals_router        # noqa: F841
risk_export    = risk_router           # noqa: F841
config_export  = config_router         # noqa: F841

# main.py imports this as: from app.api.routes import bot_control
# and uses bot_control.router
router = bot_control_router
