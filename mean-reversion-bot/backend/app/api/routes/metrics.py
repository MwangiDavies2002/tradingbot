"""Prometheus scrape endpoint based on durable worker state (works across processes)."""
from datetime import datetime
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from app.database.models import TradingControl, ExecutionRecord
from app.database.session import get_db
from app.config import settings
from app.execution.safety import account_scope

router = APIRouter()


@router.get("/metrics")
async def metrics(db=Depends(get_db)):
    scope = account_scope(settings)
    control = await db.get(TradingControl, scope)
    rows = (await db.execute(select(ExecutionRecord).where(ExecutionRecord.scope == scope))).scalars().all()
    age = max(0, (datetime.utcnow() - control.heartbeat).total_seconds()) if control and control.heartbeat else 1e9
    latency = [r.payload["latency_ms"] / 1000 for r in rows if r.payload.get("latency_ms") is not None]
    values = {
        "mrbot_worker_heartbeat_age_seconds": age,
        "mrbot_entries_enabled": int(bool(control and control.enabled)),
        "mrbot_recovery_blocked": int(bool(control and control.recovery_error)),
        "mrbot_open_positions": sum(r.status in {"open", "closing"} for r in rows),
        "mrbot_unresolved_orders": sum(r.status in {"pending", "unknown"} for r in rows),
        "mrbot_closed_trades": sum(r.status == "closed" for r in rows),
        "mrbot_realized_pnl": sum(r.payload.get("pnl") or 0 for r in rows if r.status == "closed"),
        "mrbot_order_latency_seconds_mean": sum(latency) / len(latency) if latency else 0,
    }
    return Response("".join(f"# TYPE {name} gauge\n{name} {value}\n" for name, value in values.items()),
                    media_type="text/plain; version=0.0.4")
