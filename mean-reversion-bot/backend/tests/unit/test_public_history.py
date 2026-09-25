import json
from unittest.mock import AsyncMock, Mock

import pytest
from websockets.exceptions import InvalidStatusCode

from app.data import historical_fetcher as history


@pytest.mark.asyncio
async def test_public_history_retries_520_without_credentials(monkeypatch):
    ws = AsyncMock()
    ws.recv.return_value = json.dumps({'candles': [{'epoch': 100}]})
    connection = AsyncMock()
    connection.__aenter__.return_value = ws
    connect = Mock(side_effect=[InvalidStatusCode(520, {}), connection])
    monkeypatch.setattr(history.websockets, 'connect', connect)
    pause = AsyncMock()
    monkeypatch.setattr(history.asyncio, 'sleep', pause)
    assert await history._history_page('1HZ75V', 300, 200, 1000) == [{'epoch': 100}]
    assert connect.call_count == 2
    assert connect.call_args.args == (history.PUBLIC_HISTORY_ENDPOINT,)
    request = json.loads(ws.send.call_args.args[0])
    assert request['ticks_history'] == '1HZ75V'
    assert 'authorize' not in request
    pause.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_outage_is_bounded_and_actionable(monkeypatch):
    connect = Mock(side_effect=InvalidStatusCode(520, {}))
    monkeypatch.setattr(history.websockets, 'connect', connect)
    monkeypatch.setattr(history.asyncio, 'sleep', AsyncMock())
    with pytest.raises(ValueError, match='3 attempts.*HTTP 520.*Connected MT5'):
        await history._history_page('1HZ75V', 300, 200, 1000)
    assert connect.call_count == 3


@pytest.mark.asyncio
async def test_invalid_symbol_not_retried(monkeypatch):
    ws = AsyncMock()
    ws.recv.return_value = json.dumps({'error': {'message': 'Invalid symbol'}})
    connection = AsyncMock()
    connection.__aenter__.return_value = ws
    connect = Mock(return_value=connection)
    monkeypatch.setattr(history.websockets, 'connect', connect)
    with pytest.raises(ValueError, match='Invalid symbol'):
        await history._history_page('bad', 300, 200, 1000)
    assert connect.call_count == 1


@pytest.mark.asyncio
async def test_closed_candles_paginate_beyond_provider_limit(monkeypatch):
    monkeypatch.setattr(history.time, 'time', lambda: 1800300)
    first = [{'epoch': i * 300} for i in range(1001, 6001)]
    second = [{'epoch': 1000 * 300}]
    page = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(history, '_history_page', page)
    rows = await history.fetch_public_candles('1HZ75V', 300, 5001)
    assert len(rows) == 5001
    assert page.call_args_list[0].args == ('1HZ75V', 300, 5000, 1800299)
    assert page.call_args_list[1].args == ('1HZ75V', 300, 1, 300299)
    assert rows[0]['epoch'] < rows[-1]['epoch']

@pytest.mark.asyncio
async def test_public_candles_cache_in_local_sqlite(monkeypatch):
    from sqlalchemy import select, func
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from app.database.models import Candle
    raw = [{'epoch': 1700000000 + i * 300, 'open': 100, 'high': 101,
            'low': 99, 'close': 100} for i in range(288)]
    monkeypatch.setattr(history, 'fetch_public_candles', AsyncMock(return_value=raw))
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Candle.__table__.create)
        async with AsyncSession(engine) as db:
            await history.fetch_and_cache_symbol(db, '1HZ75V', 300, 1)
            await history.fetch_and_cache_symbol(db, '1HZ75V', 300, 1)
            assert await db.scalar(select(func.count()).select_from(Candle)) == 288
    finally:
        await engine.dispose()
