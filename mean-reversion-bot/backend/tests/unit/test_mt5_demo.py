import time
from collections import namedtuple
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.execution.mt5_demo import DemoConfig, MAGIC, MT5DemoRunner, SYMBOL


def terminal():
    mt = Mock()
    mt.ACCOUNT_TRADE_MODE_DEMO = 0
    mt.ORDER_TYPE_BUY = 0
    mt.ORDER_TYPE_SELL = 1
    mt.ORDER_FILLING_FOK = 0
    mt.ORDER_FILLING_IOC = 1
    mt.ORDER_FILLING_RETURN = 2
    mt.TRADE_ACTION_DEAL = 1
    mt.ORDER_TIME_GTC = 0
    mt.TRADE_RETCODE_DONE = 10009
    mt.TRADE_RETCODE_DONE_PARTIAL = 10010
    mt.TIMEFRAME_M5 = 5
    mt.initialize.return_value = True
    mt.terminal_info.return_value = NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
    mt.account_info.return_value = NS(login=123, server='Deriv-Demo', trade_mode=0,
                                     balance=10000, equity=10000, trade_allowed=True, trade_expert=True)
    mt.symbol_select.return_value = True
    mt.history_deals_get.return_value = []
    mt.positions_get.return_value = []
    mt.orders_get.return_value = []
    mt.symbol_info.return_value = NS(trade_tick_size=0.01, point=0.01, digits=2,
                                   trade_stops_level=0, volume_max=100, volume_min=0.01,
                                   volume_step=0.01, filling_mode=1)
    mt.symbol_info_tick.return_value = NS(time=time.time(), ask=100.1, bid=100.0)
    mt.order_calc_profit.return_value = -150
    mt.order_check.return_value = NS(retcode=0)
    Result = namedtuple('Result', 'retcode order')
    mt.order_send.return_value = Result(10009, 456)
    return mt


@pytest.fixture
def runner(tmp_path):
    instance = MT5DemoRunner(tmp_path / 'journal.sqlite3', terminal())
    instance.connect()
    return instance


def decision():
    return NS(direction='buy', atr=NS(value=1))


def test_only_v751s_and_bounded_risk_are_accepted():
    for value in ({'symbol': 'R_75'}, {'risk_pct': 0.2}, {'timeframe': 'M2'},
                  {'use_zscore': False, 'use_lsl': False, 'use_smc': False}):
        with pytest.raises(ValidationError):
            DemoConfig(**value)


def test_real_account_and_account_switch_block_orders(runner):
    runner.mt5.account_info.return_value.trade_mode = 2
    with pytest.raises(ValueError, match='Demo account required'):
        runner._send(decision(), None, 'bar1')
    runner.mt5.account_info.return_value.trade_mode = 0
    runner.mt5.account_info.return_value.login = 999
    with pytest.raises(ValueError, match='account changed'):
        runner._send(decision(), None, 'bar1')
    runner.mt5.order_send.assert_not_called()


def test_order_uses_broker_risk_and_protective_stops(runner):
    runner._send(decision(), None, 'bar1')
    request = runner.mt5.order_send.call_args.args[0]
    assert request['symbol'] == SYMBOL
    assert request['magic'] == MAGIC
    assert request['sl'] < request['price'] < request['tp']
    assert request['volume'] == 0.33  # $50 budget / $150 per lot, rounded down
    assert request['volume'] * 150 <= 10000 * runner.config.risk_pct
    runner._send(decision(), None, 'bar1')
    assert runner.mt5.order_send.call_count == 1


def test_minimum_lot_and_stale_ticks_do_not_send(runner):
    runner.mt5.symbol_info.return_value.volume_min = 1
    runner._send(decision(), None, 'bar1')
    runner.mt5.order_send.assert_not_called()
    runner.mt5.symbol_info_tick.return_value.time = time.time() - 120
    with pytest.raises(ValueError, match='fresh'):
        runner._send(decision(), None, 'bar2')
    runner.mt5.order_send.assert_not_called()


def test_daily_limit_persists_and_latches_after_restart(runner):
    account = runner.mt5.account_info.return_value
    assert runner._daily_guard(account)
    account.equity = 9600
    assert not runner._daily_guard(account)
    restarted = MT5DemoRunner(runner.path, runner.mt5)
    restarted.connect()
    account.equity = 10000
    assert not restarted._daily_guard(account)


def test_journal_recovers_manual_exit_of_bot_position_once(runner):
    Deal = namedtuple('Deal', 'ticket position_id magic symbol entry profit commission swap fee')
    runner.mt5.history_deals_get.return_value = [
        Deal(1, 100, MAGIC, SYMBOL, 0, 0, -1, 0, 0),
        Deal(2, 100, 0, SYMBOL, 1, 20, -1, 0, 0),
        Deal(3, 200, 0, SYMBOL, 1, 40, 0, 0, 0),
    ]
    runner._sync_deals()
    runner._sync_deals()
    rows = [r for r in runner.journal() if r['kind'] == 'deal']
    assert len(rows) == 2
    assert {r['data']['ticket'] for r in rows} == {1, 2}


def test_ambiguous_order_response_is_journaled_and_never_retried(runner):
    runner.mt5.order_send.return_value = None
    with pytest.raises(ValueError, match='no automatic retry'):
        runner._send(decision(), None, 'bar1')
    restarted = MT5DemoRunner(runner.path, runner.mt5)
    restarted.connect()
    restarted._send(decision(), None, 'bar1')
    assert runner.mt5.order_send.call_count == 1
    assert {'order_request', 'order_result'} <= {r['kind'] for r in runner.journal()}


def test_positions_and_failed_queries_prevent_evaluation(runner):
    runner.engine = Mock()
    runner.mt5.positions_get.return_value = [NS(_asdict=lambda: {'ticket': 1})]
    runner._tick()
    runner.engine.evaluate.assert_not_called()
    runner.mt5.positions_get.return_value = None
    with pytest.raises(ValueError, match='Cannot verify'):
        runner._tick()


def test_same_closed_candle_is_not_replayed_after_restart(runner):
    end = int(time.time() // 300) * 300 - 300
    runner.mt5.copy_rates_from_pos.return_value = [
        dict(time=end - (99 - i) * 300, open=100, high=101, low=99, close=100, tick_volume=300)
        for i in range(100)
    ]
    engine = Mock()
    engine.evaluate.return_value = NS(direction=None, confluence_score=0, reason='no_clear_direction',
                                      should_trade=False, confluence=None)
    runner.engine = engine
    runner._tick()
    restarted = MT5DemoRunner(runner.path, runner.mt5)
    restarted.connect()
    restarted.engine = engine
    restarted._tick()
    assert engine.evaluate.call_count == 1
    assert runner.mt5.copy_rates_from_pos.call_args.args[2] == 1


def test_strategy_persists_and_cannot_change_while_running(runner):
    config = DemoConfig(use_volume=False, min_confluence=7)
    runner.configure(config)
    assert MT5DemoRunner(runner.path, runner.mt5).config == config
    runner.state['running'] = True
    with pytest.raises(ValueError, match='Stop'):
        runner.configure(DemoConfig())


def test_external_browser_origin_blocked(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.mt5 import router
    app = FastAPI()
    app.state.mt5_demo = MT5DemoRunner(tmp_path / 'api.sqlite3', terminal())
    app.include_router(router, prefix='/api/mt5')
    client = TestClient(app)
    assert client.post('/api/mt5/connect', headers={'origin': 'https://untrusted.example'}).status_code == 403
    assert client.get('/api/mt5/status').json()['running'] is False
    assert client.put('/api/mt5/strategy', json={'symbol': 'EURUSD'}).status_code == 422


def test_shared_signal_engine_and_backtest_evaluate_fixture_candles():
    import math
    from app.core.engine.signal_engine import EngineConfig, SignalEngine
    from app.core.lsl.lsl_detector import Candle
    from app.backtesting.backtest_engine import BacktestEngine
    # Deterministic test data, never supplied to the live runner.
    candles = []
    for i in range(250):
        price = 100 + math.sin(i / 8) * 4
        candles.append(Candle(timestamp=1700000000 + i * 300, open=price,
                              high=price + 0.5, low=price - 0.5,
                              close=price + math.sin(i) * 0.2, volume=300))
    engine = SignalEngine(EngineConfig(use_hurst=False))
    engine.initialise(10000)
    result = engine.evaluate(candles, symbol='1HZ75V', timeframe='M5')
    assert isinstance(result.should_trade, bool)
    report = BacktestEngine(signal_engine=engine, initial_balance=10000).run(
        candles, symbol='1HZ75V', timeframe='M5')
    assert isinstance(report.trades, list)
