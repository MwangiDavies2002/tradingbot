"""Durable Deriv controls, execution journal and exclusive worker ownership."""
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select, text

from app.database.models import ExecutionRecord, Trade, TradingControl, DecisionReceipt, Signal


def account_scope(settings):
    if not settings.DERIV_ACCOUNT_ID:
        raise ValueError("DERIV_ACCOUNT_ID must identify the intended broker account")
    return f"deriv:{'demo' if settings.DERIV_DEMO else 'live'}:{settings.DERIV_ACCOUNT_ID}"


def validate_account(settings, state):
    account_scope(settings)
    if not state.connected or not state.authenticated:
        raise RuntimeError("Broker is not authenticated")
    if state.account_id != settings.DERIV_ACCOUNT_ID:
        raise RuntimeError("Broker account does not match DERIV_ACCOUNT_ID")
    if state.is_virtual is None or state.is_virtual != settings.DERIV_DEMO:
        raise RuntimeError("Broker account does not match demo/live mode")
    if not settings.DERIV_DEMO and not settings.LIVE_TRADING_ENABLED:
        raise RuntimeError("Live trading is disabled")
    if state.currency != "USD":
        raise RuntimeError("This execution adapter currently requires a USD account")
    if settings.DERIV_PRODUCT != "multiplier":
        raise RuntimeError("Only multiplier execution is supported")


async def control_row(db, scope, lock=False):
    query = select(TradingControl).where(TradingControl.scope == scope)
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        row = TradingControl(scope=scope, enabled=False, risk_state={},
                             reset_version=0, reset_applied=0)
        db.add(row)
        await db.flush()
    return row


class ExecutionStore:
    def __init__(self, sessions, scope):
        self.sessions = sessions
        self.scope = scope
        self._owner = None

    async def acquire(self, engine):
        # Session-level lock survives commits. Fail closed on unsupported DBs.
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Deriv worker requires PostgreSQL for exclusive ownership")
        self._owner = await engine.connect()
        key = int.from_bytes(hashlib.sha256(self.scope.encode()).digest()[:8],
                             "big", signed=True)
        acquired = await self._owner.scalar(text("SELECT pg_try_advisory_lock(:key)"),
                                            {"key": key})
        await self._owner.commit()
        if not acquired:
            await self._owner.close()
            self._owner = None
            raise RuntimeError("Another worker owns this account")
        self._owner_key = key
        async with self.sessions() as db:
            row = await control_row(db, self.scope, lock=True)
            row.enabled = False
            row.heartbeat = None
            row.recovery_error = "Startup reconciliation required"
            await db.commit()

    async def release(self):
        if self._owner is not None:
            try:
                await self._owner.execute(text("SELECT pg_advisory_unlock(:key)"),
                                          {"key": self._owner_key})
                await self._owner.commit()
            finally:
                await self._owner.close()
                self._owner = None

    async def check_owner(self):
        if self._owner is None or self._owner.invalidated:
            raise RuntimeError("Worker ownership lost")
        await self._owner.execute(text("SELECT 1"))
        await self._owner.commit()

    @asynccontextmanager
    async def entry_gate(self):
        await self.check_owner()
        async with self.sessions() as db:
            async with db.begin():
                row = await control_row(db, self.scope, lock=True)
                if not row.enabled or row.recovery_error:
                    raise RuntimeError(row.recovery_error or "Trading is stopped")
                # Serializes admission with stop requests. An already admitted buy
                # may finish before stop commits; the worker then closes it.
                yield row

    async def load(self):
        async with self.sessions() as db:
            records = (await db.execute(select(ExecutionRecord).where(
                ExecutionRecord.scope == self.scope))).scalars().all()
            row = await control_row(db, self.scope)
            state = dict(row.risk_state)
            if records and not state:
                raise RuntimeError("Journal exists without persisted risk state; operator review required")
            await db.commit()
            return [dict(r.payload) for r in records], state

    async def save(self, position, cb):
        payload = position.to_dict()
        payload["timeframe"] = position.timeframe
        async with self.sessions() as db:
            record = await db.get(ExecutionRecord, position.trade_id)
            if record is None:
                if position.signal_key:
                    db.add(DecisionReceipt(fingerprint=position.signal_key, trade_id=position.trade_id))
                record = ExecutionRecord(trade_id=position.trade_id, scope=self.scope)
                db.add(record)
            record.payload = payload
            record.status = position.status.value
            record.updated_at = datetime.utcnow()
            trade = (await db.execute(select(Trade).where(
                Trade.trade_id == position.trade_id))).scalar_one_or_none()
            if trade is None:
                trade = Trade(trade_id=position.trade_id)
                db.add(trade)
            for name in ("contract_id", "symbol", "timeframe", "direction", "contract_type",
                         "entry_price", "stop_loss", "take_profit", "exit_price", "stake",
                         "pnl", "opened_at", "closed_at", "confluence_score", "reason_code"):
                setattr(trade, name, getattr(position, name))
            trade.status = position.status.value
            trade.close_reason = payload["close_reason"]
            trade.pnl_pct = position.pnl_pct
            row = await control_row(db, self.scope)
            row.risk_state = cb.snapshot()
            await db.commit()

    async def has_signal(self, fingerprint):
        async with self.sessions() as db:
            return await db.get(DecisionReceipt, fingerprint) is not None

    async def log_signal(self, decision, strategy_hash):
        breakdown = decision.confluence.breakdown.to_dict() if decision.confluence else {}
        async with self.sessions() as db:
            db.add(Signal(symbol=decision.symbol, timeframe=decision.timeframe,
                direction=decision.direction, score=decision.confluence_score,
                fired=decision.should_trade, reason=decision.reason[:128], eval_ms=decision.eval_ms,
                breakdown_json={"scope": self.scope, "strategy_hash": strategy_hash,
                                "is_safety_order": decision.is_safety_order,
                                "order_index": decision.order_index, "score_breakdown": breakdown}))
            await db.commit()

    async def heartbeat(self, cb, error):
        await self.check_owner()
        async with self.sessions() as db:
            row = await control_row(db, self.scope, lock=True)
            if row.reset_version != row.reset_applied:
                cb.manual_reset()
                row.reset_applied = row.reset_version
            row.risk_state = cb.snapshot()
            row.recovery_error = error
            row.heartbeat = datetime.utcnow()
            enabled = row.enabled
            await db.commit()
            return enabled
