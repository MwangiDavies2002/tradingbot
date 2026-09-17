from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.api.security import protect_api
from app.core.engine.signal_engine import TradeDecision
from app.core.risk.position_sizer import PositionSizer
from app.core.risk.circuit_breaker import CircuitBreaker, BreakerState
from app.database.models import Base
from app.execution.safety import ExecutionStore, account_scope, control_row, validate_account
from app.execution.order_manager import OrderManager, PositionStatus


@pytest_asyncio.fixture
async def system():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = ExecutionStore(sessions, account_scope(settings))
    store.check_owner = AsyncMock()  # PostgreSQL ownership tested separately.
    broker = SimpleNamespace(
        state=SimpleNamespace(connected=True, authenticated=True, account_id="VRTC123",
                              is_virtual=True, currency="USD", balance=1000,
                              connect_time=datetime.utcnow()),
        get_portfolio=AsyncMock(return_value=[]), get_balance=AsyncMock(return_value=1000),
        get_contract=AsyncMock(return_value={"is_sold": 0, "bid_price": 10}),
        buy_contract=AsyncMock(return_value={"contract_id": 123}),
        sell_contract=AsyncMock(return_value={"sold_for": 15}),
    )
    cb = CircuitBreaker(); cb.initialise(1000)
    manager = OrderManager(broker, cb, store=store, settings=settings)
    assert await manager.recover(initial=True)
    async with sessions() as db:
        row = await control_row(db, store.scope)
        row.enabled = True
        await db.commit()
    yield manager, broker, store, sessions
    await engine.dispose()


def decision():
    sizing = PositionSizer(1000).calculate(entry=100, atr=1, direction="buy")
    return TradeDecision(symbol="R_75", timeframe="M5", direction="buy",
                         should_trade=True, reason="test", entry_price=100, sizing=sizing)


@pytest.mark.asyncio
async def test_order_is_durable_and_restored(system):
    manager, broker, store, _ = system
    p = await manager.execute(decision())
    assert p and p.contract_id == 123
    records, _ = await store.load()
    assert records[0]["status"] == "open"
    broker.get_portfolio.return_value = [{"contract_id": 123}]
    recovered = OrderManager(broker, CircuitBreaker(), store=store, settings=settings)
    assert await recovered.recover(initial=True)
    assert recovered.open_positions[0].trade_id == p.trade_id
    assert recovered.cb._open_positions == 1
    assert broker.buy_contract.await_count == 1
    assert broker.buy_contract.call_args.kwargs["limit_order"]["stop_loss"] > 0


@pytest.mark.asyncio
async def test_buy_intent_committed_before_broker_call(system):
    manager, broker, store, _ = system
    async def buy(**kwargs):
        rows, _ = await store.load()
        assert rows[0]["status"] == "pending"
        return {"contract_id": 123}
    broker.buy_contract.side_effect = buy
    assert await manager.execute(decision())


@pytest.mark.asyncio
async def test_timeout_blocks_retries_across_restart(system):
    manager, broker, store, _ = system
    broker.buy_contract.side_effect = TimeoutError("unknown outcome")
    assert await manager.execute(decision()) is None
    assert not await manager.recover(initial=True)
    assert await manager.execute(decision()) is None
    assert broker.buy_contract.await_count == 1
    rows, _ = await store.load()
    assert rows[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_definitive_rejection_is_not_an_unknown_buy(system):
    from app.execution.deriv_client import BrokerRejectedError
    manager, broker, store, _ = system
    broker.buy_contract.side_effect = BrokerRejectedError("Contract validation failed")
    assert await manager.execute(decision()) is None
    assert (await store.load())[0][0]["status"] == "cancelled"
    assert manager.ready


@pytest.mark.asyncio
async def test_persisted_stop_blocks_entries(system):
    manager, broker, store, sessions = system
    async with sessions() as db:
        row = await control_row(db, store.scope)
        row.enabled = False
        await db.commit()
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()
    assert manager.all_positions[0].status == PositionStatus.CANCELLED


@pytest.mark.asyncio
async def test_unknown_broker_contract_blocks_entries(system):
    manager, broker, _, _ = system
    broker.get_portfolio.return_value = [{"contract_id": 999}]
    assert not await manager.recover()
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()


@pytest.mark.asyncio
async def test_pnl_uses_cash_returned_not_underlying_price(system):
    manager, broker, store, _ = system
    p = await manager.execute(decision())
    stake = p.stake
    closed = await manager.close_position(p.trade_id)
    assert closed.pnl == 15 - stake
    assert closed.exit_price is None
    assert (await store.load())[0][0]["status"] == "closed"


@pytest.mark.asyncio
async def test_broker_closed_position_reconciled_once(system):
    manager, broker, _, _ = system
    p = await manager.execute(decision())
    broker.get_contract.return_value = {"is_sold": 1, "profit": -5,
                                        "exit_tick": 99, "sell_time": 1700000000}
    assert await manager.recover()
    assert manager.get_position(p.trade_id).pnl == -5
    assert manager.cb._consecutive_losses == 1
    assert await manager.recover()
    assert manager.cb._consecutive_losses == 1


@pytest.mark.asyncio
async def test_database_outage_prevents_buy(system):
    manager, broker, store, _ = system
    store.save = AsyncMock(side_effect=RuntimeError("database unavailable"))
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_blocks_entry_until_recovered(system):
    manager, broker, _, _ = system
    broker.state.connect_time = datetime(2030, 1, 1)
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()


@pytest.mark.asyncio
async def test_exposure_limit_enforced_at_execution(system, monkeypatch):
    manager, broker, _, _ = system
    monkeypatch.setattr(settings, "MAX_TOTAL_RISK_PCT", 0.001)
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_account_never_trades(system):
    manager, broker, _, _ = system
    broker.state.account_id = "CR123"
    assert await manager.execute(decision()) is None
    broker.buy_contract.assert_not_called()


def test_demo_flag_and_live_opt_in():
    state = SimpleNamespace(connected=True, authenticated=True, account_id="VRTC123",
                            is_virtual=False, currency="USD")
    with pytest.raises(RuntimeError, match="demo/live"):
        validate_account(settings, state)
    cfg = settings.model_copy(update={"DERIV_DEMO": False})
    with pytest.raises(RuntimeError, match="disabled"):
        validate_account(cfg, state)


def test_minimum_stake_is_skipped_not_rounded_up():
    result = PositionSizer(10).calculate(entry=100, atr=10, direction="buy")
    assert result.stake == 0 and not result.is_valid


def test_risk_state_roundtrip_preserves_halt():
    cb = CircuitBreaker(); cb.initialise(1000)
    cb.record_trade(-150, 850)
    restored = CircuitBreaker(); restored.restore(cb.snapshot())
    assert restored._state == BreakerState.HALTED
    assert not restored.is_trading_allowed()
    assert restored._week_start_balance == 1000


def test_authentication_roles_and_defaults(monkeypatch):
    app = FastAPI()
    app.middleware("http")(protect_api)
    @app.api_route("/api/bot/stop", methods=["GET", "POST"])
    def stop(): return {"ok": True}
    @app.put("/api/config/test")
    def config(): return {"ok": True}
    client = TestClient(app)
    assert client.post("/api/bot/stop").status_code == 401
    for role in ("viewer", "operator", "admin"):
        token = role * 32
        monkeypatch.setattr(settings, f"API_{role.upper()}_KEY_HASH",
                            hashlib.sha256(token.encode()).hexdigest())
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/bot/stop", headers=headers).status_code == 200
        assert client.post("/api/bot/stop", headers=headers).status_code == (403 if role == "viewer" else 200)
        assert client.put("/api/config/test", headers=headers).status_code == (200 if role == "admin" else 403)


@pytest.mark.asyncio
async def test_same_candle_cannot_replay_after_restart(system):
    manager, broker, store, _ = system
    assert await manager.execute(decision(), signal_key="a" * 64)
    broker.get_portfolio.return_value = [{"contract_id": 123}]
    recovered = OrderManager(broker, CircuitBreaker(), store=store, settings=settings)
    assert await recovered.recover(initial=True)
    assert await recovered.execute(decision(), signal_key="a" * 64) is None
    assert broker.buy_contract.await_count == 1


@pytest.mark.asyncio
async def test_control_routes_and_performance_use_real_schema(system, monkeypatch):
    import httpx
    from app.main import create_app
    from app.database.session import get_db
    from app.database.models import Signal
    manager, broker, store, sessions = system
    p = await manager.execute(decision())
    await manager.close_position(p.trade_id)
    async with sessions() as db:
        db.add(Signal(symbol="R_75", timeframe="M5", score=1, fired=False, reason="fixture"))
        await db.commit()
    token = "test-admin-key-" * 4
    monkeypatch.setattr(settings, "API_ADMIN_KEY_HASH", hashlib.sha256(token.encode()).hexdigest())
    app = create_app()
    async def database():
        async with sessions() as db:
            yield db
            await db.commit()
    app.dependency_overrides[get_db] = database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post('/api/bot/stop')).status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        performance = await client.get('/api/bot/performance')
        assert performance.status_code == 200
        assert performance.json()["stats"]["total_trades"] == 1
        assert (await client.get('/api/signals')).status_code == 200
        assert (await client.get('/api/metrics')).status_code == 200
        assert (await client.get('/api/config/SECRET_KEY')).status_code == 403
        assert (await client.post('/api/bot/stop')).status_code == 200
        assert (await client.post('/api/bot/start')).status_code == 409  # No heartbeat


@pytest.mark.asyncio
async def test_receiver_keeps_processing_replies_during_callback():
    import asyncio
    from app.execution.deriv_client import DerivClient
    client = DerivClient()
    client._running = True
    client.state.authenticated = True
    waiting = asyncio.Event()
    future = asyncio.get_running_loop().create_future()
    client._pending[99] = future
    async def callback(msg):
        waiting.set()
        await future
    client._subscriptions['sub'] = callback
    task = asyncio.create_task(client._handle_messages())
    try:
        await client._dispatch({"subscription": {"id": "sub"}})
        await asyncio.wait_for(waiting.wait(), 1)
        await client._dispatch({"req_id": 99, "buy": {"contract_id": 1}})
        await asyncio.wait_for(client._messages.join(), 1)
        assert future.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
