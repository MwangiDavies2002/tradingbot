from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api.routes import backtest, mt5


@pytest.mark.parametrize('values', [
    {'symbols': ['']}, {'symbols': [' EURUSD']},
    {'symbols': ['1HZ75V'], 'timeframe': 'D1'},
])
def test_mt5_rejects_mislabeled_history(values):
    with pytest.raises(ValidationError, match='MT5 history'):
        backtest.BacktestRequest(data_source='mt5', **values)


@pytest.mark.parametrize('source,uploaded', [('mt5', False), ('deriv', False), ('mt5', True)])
@pytest.mark.asyncio
async def test_history_routing_and_persisted_source(monkeypatch, source, uploaded):
    candles = [NS(timestamp=1700000000, open=100, high=101, low=99, close=100, volume=10)]
    runner = NS(history=MagicMock(return_value=[]))
    monkeypatch.setattr(mt5, 'get_runner', lambda request: runner)
    monkeypatch.setattr(backtest, 'rows_to_candles', lambda rows: candles)
    fetch = AsyncMock()
    load = AsyncMock(return_value=candles)
    monkeypatch.setattr(backtest, 'ensure_candles_for_symbols', fetch)
    monkeypatch.setattr(backtest, 'load_candles_for_symbol', load)
    report = NS(trades=[], win_rate=0, profit_factor=0, sharpe_ratio=0,
                max_drawdown_pct=0, total_pnl=0, total_pnl_pct=0, metadata={}, equity_curve=[])
    monkeypatch.setattr(backtest.BacktestEngine, 'run', lambda *args, **kwargs: report)
    db = NS(add=MagicMock(), commit=AsyncMock(), rollback=AsyncMock())
    request = Request({'type': 'http', 'client': ('127.0.0.1', 1234), 'headers': []})
    symbol = 'EURUSD.a' if source == 'mt5' else '1HZ75V'
    req = backtest.BacktestRequest(data_source=source, symbols=[symbol],
                                  csv_data='supplied-file' if uploaded else None)
    result = await backtest.run_backtest(req, request, db)
    effective = 'import' if uploaded else source
    assert result[0]['data_source'] == effective
    assert db.add.call_args.args[0].params_json['input_source'] == effective
    assert runner.history.call_count == (1 if source == 'mt5' and not uploaded else 0)
    if source == 'mt5' and not uploaded:
        runner.history.assert_called_once_with(req.timeframe, req.days, symbol)
    assert fetch.await_count == (1 if source == 'deriv' and not uploaded else 0)
    assert load.await_count == (0 if source == 'mt5' and not uploaded else 1)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_mt5_history_does_not_fallback(monkeypatch):
    runner = NS(history=MagicMock(side_effect=ValueError('Connect MT5 demo first')))
    monkeypatch.setattr(mt5, 'get_runner', lambda request: runner)
    fetch = AsyncMock()
    monkeypatch.setattr(backtest, 'ensure_candles_for_symbols', fetch)
    db = NS(rollback=AsyncMock())
    request = Request({'type': 'http', 'client': ('127.0.0.1', 1234), 'headers': []})
    with pytest.raises(HTTPException) as error:
        await backtest.run_backtest(backtest.BacktestRequest(data_source='mt5', symbols=['1HZ75V']), request, db)
    assert error.value.status_code == 422
    assert 'Connect MT5' in error.value.detail
    fetch.assert_not_awaited()
