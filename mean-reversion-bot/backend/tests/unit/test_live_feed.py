from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.data.tick_consumer import TickConsumer


@pytest.fixture
def feed(monkeypatch):
    clock = [1200]
    monkeypatch.setattr("time.time", lambda: clock[0])
    client = SimpleNamespace(subscribe_candles=AsyncMock(return_value="sub"),
                             forget_subscription=AsyncMock())
    manager = SimpleNamespace(monitor_tick=AsyncMock(), open_positions=[],
                              data_errors={}, ready=True)
    consumer = TickConsumer(client, None, manager, min_candles=1)
    consumer._evaluate_and_act = AsyncMock()
    return consumer, clock


async def send(consumer, clock, timestamp, close=101, **values):
    clock[0] = timestamp
    candle = dict(epoch=timestamp, open_time=timestamp // 60 * 60,
                  open=100, high=105, low=95, close=close)
    candle.update(values)
    await consumer._handle_candle_message({"ohlc": candle}, "R_75", 60)


@pytest.mark.asyncio
async def test_only_completed_candle_is_evaluated_once(feed):
    consumer, clock = feed
    await consumer.subscribe("R_75", 60)
    await send(consumer, clock, 1200)
    await send(consumer, clock, 1220, close=103)
    consumer._evaluate_and_act.assert_not_awaited()
    await send(consumer, clock, 1260)
    await send(consumer, clock, 1261)
    consumer._evaluate_and_act.assert_awaited_once()
    candles = consumer.get_buffer("R_75", 60)
    assert [(c.timestamp, c.close) for c in candles] == [(1200, 103)]
    assert consumer.manager.monitor_tick.await_count == 4


@pytest.mark.asyncio
async def test_gap_blocks_entries(feed):
    consumer, clock = feed
    await consumer.subscribe("R_75", 60)
    await send(consumer, clock, 1200)
    with pytest.raises(ValueError, match="gap"):
        await send(consumer, clock, 1320)
    assert not consumer.manager.ready
    assert "R_75" in consumer.manager.data_errors
    consumer._evaluate_and_act.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_and_invalid_updates_do_not_trigger_orders(feed):
    consumer, clock = feed
    await consumer.subscribe("R_75", 60)
    await send(consumer, clock, 1200, epoch=1100)
    consumer.manager.monitor_tick.assert_not_awaited()
    with pytest.raises(ValueError):
        await send(consumer, clock, 1200, close=float("nan"))
    consumer._evaluate_and_act.assert_not_awaited()
    assert consumer.get_buffer("R_75", 60) == []


@pytest.mark.asyncio
async def test_resubscribe_does_not_reuse_old_forming_candle(feed):
    consumer, clock = feed
    await consumer.subscribe("R_75", 60)
    await send(consumer, clock, 1200)
    await consumer.unsubscribe("R_75", 60)
    assert ("R_75", 60) not in consumer._forming
    await consumer.subscribe("R_75", 60)
    await send(consumer, clock, 1800)
    assert consumer.manager.ready
    consumer._evaluate_and_act.assert_not_awaited()
