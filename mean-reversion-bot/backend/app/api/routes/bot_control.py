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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotEvent, ConfigEntry, EquitySnapshot, Signal, ExecutionRecord
from app.database.session import get_db
from app.config import settings
from app.execution.safety import account_scope, control_row


def scope():
    try:
        return account_scope(settings)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


def public_config_key(key):
    # Only non-secret Settings fields may be read/written through configuration.
    return key in settings.model_fields and not any(part in key.upper() for part in
        ("TOKEN", "SECRET", "PASSWORD", "KEY", "URL", "DSN", "ACCOUNT_ID"))

# ══════════════════════════════════════════════════════════════════════════════
# BOT CONTROL  /api/bot
# ══════════════════════════════════════════════════════════════════════════════

router = APIRouter()   # re-exported; main.py imports each module separately

bot_control_router = APIRouter()


class ResolveIntent(BaseModel):
    contract_id: Optional[int] = Field(None, gt=0)
    confirmed_not_executed: bool = False
    evidence: str = Field(min_length=20, max_length=2000)

    @model_validator(mode="after")
    def exactly_one_outcome(self):
        if bool(self.contract_id) == self.confirmed_not_executed:
            raise ValueError("Supply either a broker contract ID or confirmed_not_executed")
        return self


@bot_control_router.get("/orders/unresolved")
async def unresolved_orders(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ExecutionRecord).where(
        ExecutionRecord.scope == scope(),
        ExecutionRecord.status.in_(("pending", "unknown", "closing"))
    ))).scalars().all()
    return {"orders": [r.payload for r in rows]}


@bot_control_router.post("/orders/{trade_id}/resolve")
async def resolve_intent(trade_id: str, body: ResolveIntent, request: Request,
                         db: AsyncSession = Depends(get_db)):
    control = await control_row(db, scope(), lock=True)
    if control.enabled:
        raise HTTPException(409, "Stop trading before resolving an uncertain order")
    record = await db.get(ExecutionRecord, trade_id)
    if not record or record.scope != scope():
        raise HTTPException(404, "Order not found")
    if record.status not in {"pending", "unknown"} or record.payload.get("contract_id"):
        raise HTTPException(409, "This order must be reconciled automatically by the worker")
    payload = dict(record.payload)
    if body.confirmed_not_executed:
        payload["status"] = "cancelled"
    else:
        payload["contract_id"] = body.contract_id
    record.payload = payload
    record.status = payload["status"]
    record.updated_at = datetime.utcnow()
    db.add(BotEvent(event_type="order_resolution", severity="warning",
                    message="Operator supplied broker evidence for uncertain order",
                    details_json={"scope": scope(), "trade_id": trade_id,
                                  "role": request.state.role, **body.model_dump()}))
    await db.commit()
    return {"status": "resolution_recorded", "message": "Worker must reconcile before trading resumes"}


@bot_control_router.get("/status")
async def bot_status(db: AsyncSession = Depends(get_db)):
    """
    Current bot status: running state, circuit breaker, open trade count.
    Reads from the bot_events table for circuit breaker state and the
    app state for live metrics.
    """
    control = await control_row(db, scope())
    fresh = bool(control.heartbeat and
                 (datetime.utcnow() - control.heartbeat).total_seconds() < 30)
    # Latest circuit breaker event
    stmt = (
        select(BotEvent)
        .where(BotEvent.event_type.like("circuit_breaker%"))
        .order_by(desc(BotEvent.ts))
        .limit(1)
    )
    result = await db.execute(stmt)
    cb_event = result.scalar_one_or_none()

    bot_stmt = (
        select(BotEvent)
        .where(BotEvent.event_type.in_(("bot_start_manual", "bot_stop_manual")))
        .order_by(desc(BotEvent.ts))
        .limit(1)
    )
    bot_result = await db.execute(bot_stmt)
    bot_event = bot_result.scalar_one_or_none()

    # Latest equity snapshot
    eq_stmt = select(EquitySnapshot).order_by(desc(EquitySnapshot.ts)).limit(1)
    eq_result = await db.execute(eq_stmt)
    latest_eq = eq_result.scalar_one_or_none()

    return {
        "bot_running": bool(control.enabled and fresh and not control.recovery_error),
        "entries_enabled": control.enabled,
        "worker_online": fresh,
        "recovery_error": control.recovery_error,
        "mode": "demo" if settings.DERIV_DEMO else "live",
        "account_id": settings.DERIV_ACCOUNT_ID,
        "circuit_breaker": {
            "state": control.risk_state.get("_state", "unknown"),
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
async def stop_bot(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Emergency stop / kill switch.
    Logs the event and signals the bot process to stop.
    NOTE: Wire this to the actual bot instance via app.state in production.
    """
    control = await control_row(db, scope(), lock=True)
    control.enabled = False
    event = BotEvent(
        event_type="bot_stop_manual",
        severity="warning",
        message="Bot stopped via API kill switch",
        details_json={"source": "api", "role": request.state.role, "scope": scope()},
    )
    db.add(event)
    await db.commit()
    return {"status": "entries_disabled", "message": "Stop persisted; worker will attempt to close managed positions. Check positions for confirmation."}


@bot_control_router.post("/start")
async def start_bot(request: Request, db: AsyncSession = Depends(get_db)):
    """Signal the bot to start (or resume after a pause)."""
    control = await control_row(db, scope(), lock=True)
    if not settings.DERIV_DEMO and not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(409, "Live trading is disabled in server settings")
    if control.recovery_error:
        raise HTTPException(409, control.recovery_error)
    if not control.heartbeat or (datetime.utcnow() - control.heartbeat).total_seconds() >= 30:
        raise HTTPException(409, "Start the worker service and wait for reconciliation first")
    control.enabled = True
    event = BotEvent(
        event_type="bot_start_manual",
        severity="info",
        message="Bot started via API",
        details_json={"source": "api", "role": request.state.role, "scope": scope()},
    )
    db.add(event)
    await db.commit()
    return {"status": "start_signal_sent"}


@bot_control_router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Manually reset the circuit breaker after a HALT.
    Requires conscious operator action — not automated.
    """
    control = await control_row(db, scope(), lock=True)
    control.reset_version += 1
    event = BotEvent(
        event_type="circuit_breaker_manual_reset",
        severity="warning",
        message="Circuit breaker manually reset by operator",
        details_json={"source": "api", "role": request.state.role, "scope": scope()},
    )
    db.add(event)
    await db.commit()
    return {"status": "reset_requested", "version": control.reset_version}


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
            for e in entries if public_config_key(e.key)
        ]
    }


@config_router.put("/{key}")
async def update_config(
    key:    str,
    body:   ConfigUpdate,
    db:     AsyncSession = Depends(get_db),
):
    """Update a single config value. Restricted keys cannot be changed via API."""
    # Runtime risk/account/security parameters are deployment configuration.
    # The worker does not load ConfigEntry overrides, so do not claim otherwise.
    raise HTTPException(409, "Configuration changes require a worker restart; update server settings")


@config_router.get("/{key}")
async def get_config_key(key: str, db: AsyncSession = Depends(get_db)):
    """Get a single config value by key."""
    if not public_config_key(key):
        raise HTTPException(403, "This configuration key is not public")
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
