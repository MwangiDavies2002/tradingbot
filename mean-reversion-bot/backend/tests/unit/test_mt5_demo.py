import time
from collections import namedtuple
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.execution.mt5_demo import DemoConfig, MAGIC, MT5DemoRunner, SYMBOL, compare_forward_performance


def test_forward_comparison_waits_for_sample_and_flags_deterioration():
    candidate = {'run_id': 'run-a', 'validated_at': 100, 'loaded_at': 101,
                 'snapshot': {'server': 'Deriv-Demo', 'account': 123, 'currency': 'USD'},
                 'strategy': {'symbol': SYMBOL},
                 'research_baseline': {'holdout': {'profit_factor': 2.0}}}
    orders = [{'account': 'Deriv-Demo:123', 'data': {'order': i + 1, 'symbol': SYMBOL,
               'strategy': candidate['strategy'], 'research_run_id': 'run-a', 'accepted': True}}
              for i in range(20)]
    deals = []
    for i in range(20):
        entry = {'position_id': i + 1, 'entry': 0, 'symbol': SYMBOL, 'time': 102 + i,
                 'order': i + 1, 'magic': MAGIC, 'volume': 1, 'commission': -.1}
        exit_deal = {'position_id': i + 1, 'entry': 1, 'symbol': SYMBOL, 'time': 103 + i,
                     'order': i + 100, 'magic': 0, 'volume': 1, 'profit': -1}
        deals.extend([{'account': 'Deriv-Demo:123', 'data': entry},
                      {'account': 'Deriv-Demo:123', 'data': exit_deal}])
    assert compare_forward_performance(candidate, deals[:2], orders)['status'] == 'insufficient_sample'
    result = compare_forward_performance(candidate, deals, orders)
    assert result['status'] == 'deteriorating' and result['alert'] is True
    assert result['closed_trades'] == 20 and result['total_pnl'] == -22
    assert result['account_scope'] == 'Deriv-Demo:123' and result['research_run_id'] == 'run-a'


def test_demo_comparison_excludes_other_runs_accounts_and_incomplete_positions():
    candidate = {'run_id': 'run-a', 'validated_at': 100, 'loaded_at': 110,
                 'snapshot': {'server': 'demo', 'account': 1, 'currency': 'USD'},
                 'strategy': {'symbol': 'TEST.a'},
                 'research_baseline': {'holdout': {'profit_factor': 2}}}
    orders = [{'account': 'demo:1', 'data': {'order': 10, 'symbol': 'TEST.a',
               'strategy': candidate['strategy'], 'research_run_id': 'run-a', 'accepted': True}},
              {'account': 'demo:1', 'data': {'order': 20, 'symbol': 'TEST.a',
               'strategy': candidate['strategy'], 'research_run_id': 'run-b', 'accepted': True}},
              {'account': 'demo:2', 'data': {'order': 30, 'symbol': 'TEST.a',
               'strategy': candidate['strategy'], 'research_run_id': 'run-a', 'accepted': True}}]
    def deal(account, position, entry, order, volume, time, profit=0):
        return {'account': account, 'data': {'position_id': position, 'entry': entry,
                'symbol': 'TEST.a', 'order': order, 'magic': MAGIC if entry == 0 else 0,
                'volume': volume, 'time': time, 'profit': profit}}
    deals = [deal('demo:1', 1, 0, 10, 1, 111, profit=-.2),
             deal('demo:1', 1, 1, 11, .4, 112, profit=2),
             deal('demo:1', 1, 1, 12, .6, 113, profit=3),
             deal('demo:1', 2, 0, 20, 1, 111), deal('demo:1', 2, 1, 21, 1, 112, profit=99),
             deal('demo:2', 3, 0, 30, 1, 111), deal('demo:2', 3, 1, 31, 1, 112, profit=99),
             deal('demo:1', 4, 0, 10, 1, 109), deal('demo:1', 4, 1, 41, 1, 112, profit=99),
             deal('demo:1', 5, 0, 10, 1, 111), deal('demo:1', 5, 1, 51, .5, 112, profit=99)]
    result = compare_forward_performance(candidate, deals, orders, minimum_sample=1)
    assert result['closed_trades'] == 1 and result['total_pnl'] == 4.8
    assert result['linked_orders'] == 1 and result['incomplete_positions'] == 1
    assert result['status'] == 'observing'


def test_demo_comparison_can_link_entry_by_broker_deal_ticket():
    candidate = {'run_id': 'run-a', 'loaded_at': 100,
                 'snapshot': {'server': 'demo', 'account': 1},
                 'strategy': {'symbol': 'TEST.a'},
                 'research_baseline': {'holdout': {'profit_factor': 2}}}
    orders = [{'account': 'demo:1', 'data': {'order': 0, 'deal': 400,
               'symbol': 'TEST.a', 'strategy': candidate['strategy'],
               'research_run_id': 'run-a', 'accepted': True}}]
    deals = [{'account': 'demo:1', 'data': {'ticket': 400, 'position_id': 4,
              'order': 0, 'entry': 0, 'symbol': 'TEST.a', 'magic': MAGIC,
              'volume': .1, 'time': 101}},
             {'account': 'demo:1', 'data': {'ticket': 401, 'position_id': 4,
              'order': 401, 'entry': 1, 'symbol': 'TEST.a', 'magic': 0,
              'volume': .1, 'time': 102, 'profit': 2}}]
    result = compare_forward_performance(candidate, deals, orders)
    assert result['closed_trades'] == 1 and result['linked_deals'] == 1


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
    mt.symbol_info.return_value = NS(name=SYMBOL, description='Test instrument', trade_mode=4, order_mode=49, trade_exemode=2, trade_tick_size=0.01, point=0.01, digits=2,
                                   trade_stops_level=0, volume_max=100, volume_min=0.01,
                                   volume_step=0.01, filling_mode=1)
    mt.symbol_info_tick.return_value = NS(time=time.time(), ask=100.1, bid=100.0)
    mt.order_calc_profit.side_effect = lambda side, symbol, volume, price, sl: -150 * volume
    mt.symbols_get.return_value = [mt.symbol_info.return_value]
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


@pytest.mark.parametrize('symbol', ['EURUSD.a', 'XAUUSD', 'US100.cash'])
def test_exact_pair_orders_and_persistence(runner, symbol):
    runner.mt5.symbol_info.return_value.name = symbol
    runner.configure(DemoConfig(symbol=symbol))
    runner._send(decision(), None, f'bar:{symbol}')
    assert runner.mt5.order_send.call_args.args[0]['symbol'] == symbol
    runner.mt5.symbol_info_tick.assert_called_with(symbol)
    assert runner.mt5.order_calc_profit.call_args.args[1] == symbol
    assert MT5DemoRunner(runner.path, runner.mt5).config.symbol == symbol


def test_catalog_without_v75_and_unknown_pair(runner):
    runner.mt5.symbol_info.return_value.name = 'EURUSD.a'
    runner.connect()
    assert runner.symbols()['symbols'][0]['name'] == 'EURUSD.a'
    runner.mt5.symbol_info.return_value = None
    with pytest.raises(ValueError, match='unavailable'):
        runner.configure(DemoConfig(symbol='EURUSD'))
    assert runner.config.symbol == SYMBOL
    runner.mt5.order_send.assert_not_called()


def test_stale_start_does_not_launch_worker(runner):
    with pytest.raises(ValueError, match='differs'):
        runner.start('EURUSD.a')
    assert runner.worker is None
    runner.mt5.order_send.assert_not_called()


@pytest.mark.parametrize('kind', ['positions_get', 'orders_get'])
def test_previous_pair_exposure_blocks_new_entries(runner, kind):
    runner.mt5.symbol_info.return_value.name = 'EURUSD.a'
    runner.configure(DemoConfig(symbol='EURUSD.a'))
    getattr(runner.mt5, kind).return_value = [NS(symbol=SYMBOL, magic=MAGIC)]
    runner._send(decision(), None, 'newpair')
    runner.mt5.order_send.assert_not_called()


def test_history_uses_requested_pair_without_changing_saved_pair(runner):
    runner.mt5.symbol_info.return_value.name = 'EURUSD.a'
    runner.mt5.copy_rates_range.return_value = [dict(time=1700000000+i*300, open=1, high=2, low=1, close=1, tick_volume=10) for i in range(100)]
    assert len(runner.history('M5', 7, 'EURUSD.a')) == 100
    assert runner.mt5.copy_rates_range.call_args.args[0] == 'EURUSD.a'
    assert runner.config.symbol == SYMBOL


@pytest.mark.parametrize('field,value', [('trade_mode', 0), ('trade_mode', 3), ('order_mode', 1), ('volume_step', 0)])
def test_unusable_symbol_rejected(runner, field, value):
    setattr(runner.mt5.symbol_info.return_value, field, value)
    with pytest.raises(ValueError):
        runner.configure(DemoConfig())
    runner.mt5.order_send.assert_not_called()


def test_exact_symbol_and_bounded_risk_are_accepted():
    assert DemoConfig(symbol='EURUSD.a').symbol == 'EURUSD.a'
    for value in ({'symbol': '\n'}, {'symbol': ' EURUSD'}, {'risk_pct': 0.2}, {'timeframe': 'M2'},
                  {'use_zscore': False, 'use_lsl': False, 'use_smc': False,
                   'use_rsi': False, 'use_bb': False, 'use_vwap': False, 'use_stoch': False}):
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


def test_demo_order_and_position_keep_loaded_candidate_lineage(runner):
    info = runner.mt5.symbol_info.return_value
    info.trade_contract_size = 100
    snapshot = {'server': 'Deriv-Demo', 'account': 123, 'currency': 'USD',
                'contract_size': 100, 'tick_size': info.trade_tick_size,
                'volume_min': info.volume_min, 'volume_step': info.volume_step,
                'volume_max': info.volume_max}
    evidence = {'run_id': 'research-one', 'validated_at': time.time() - 10,
                'strategy': runner.config.model_dump(), 'snapshot': snapshot,
                'research_baseline': {'holdout': {'profit_factor': 2}}}
    runner.adopt_research_candidate(evidence)
    loaded = runner.status()['research_candidate']
    assert loaded['loaded_at'] >= evidence['validated_at']
    runner.adopt_research_candidate(evidence)
    assert runner.status()['research_candidate']['loaded_at'] == loaded['loaded_at']
    runner._send(decision(), None, 'bar:lineage')
    result = next(row['data'] for row in runner.journal() if row['kind'] == 'order_result')
    assert result['research_run_id'] == 'research-one' and result['accepted'] is True
    for ticket, entry, volume, profit in [(1, 0, .33, 0), (2, 1, .33, -5)]:
        runner.record('deal', {'ticket': ticket, 'position_id': 456, 'entry': entry,
                              'order': 456 if entry == 0 else 789,
                              'magic': MAGIC if entry == 0 else 0, 'symbol': SYMBOL,
                              'time': loaded['loaded_at'] + 1 + ticket,
                              'volume': volume, 'profit': profit})
    comparison = runner.status()['research_comparison']
    assert comparison['closed_trades'] == 1 and comparison['total_pnl'] == -5
    assert comparison['research_run_id'] == 'research-one'
    runner.mt5.account_info.return_value.login = 999
    runner.connect()
    assert runner.status()['research_validated'] is False


def test_demo_preflight_separates_start_readiness_from_live_market_data(runner):
    now = time.time()
    info = runner.mt5.symbol_info.return_value
    info.trade_contract_size = 100
    evidence = {'run_id': 'preflight-run', 'validated_at': now - 10,
                'strategy': runner.config.model_dump(),
                'snapshot': {'server': 'Deriv-Demo', 'account': 123, 'currency': 'USD',
                             'contract_size': 100, 'tick_size': info.trade_tick_size,
                             'volume_min': info.volume_min, 'volume_step': info.volume_step,
                             'volume_max': info.volume_max}}
    runner.adopt_research_candidate(evidence)
    end = int(now // 300) * 300 - 300
    runner.mt5.symbol_select.reset_mock()
    runner.mt5.copy_rates_from_pos.return_value = [
        {'time': end - (99 - i) * 300} for i in range(100)]
    runner.mt5.symbol_info_tick.return_value = NS(time=now, bid=100, ask=100.1)
    ready = runner.preflight()
    assert ready['ready_to_start'] is True and ready['live_market_ready'] is True
    assert ready['research_run_id'] == 'preflight-run'
    assert ready['account_scope'] == 'Deriv-Demo:123'
    assert ready['read_only'] is True
    runner.mt5.symbol_info_tick.return_value.time = now - 120
    runner.mt5.copy_rates_from_pos.return_value[-1]['time'] = end - 3600
    waiting = runner.preflight()
    assert waiting['ready_to_start'] is True and waiting['live_market_ready'] is False
    assert {c['code'] for c in waiting['checks'] if not c['ok']} == {'fresh_quote', 'fresh_candles'}
    runner.mt5.symbol_select.assert_not_called()
    runner.mt5.order_send.assert_not_called()


def test_demo_preflight_reports_missing_candidate_permissions_and_exposure(runner):
    runner.mt5.copy_rates_from_pos.return_value = []
    missing = runner.preflight()
    assert missing['ready_to_start'] is False
    assert any(c['code'] == 'candidate_loaded' and not c['ok'] for c in missing['checks'])
    runner.mt5.terminal_info.return_value.trade_allowed = False
    denied = runner.preflight()
    assert any(c['code'] == 'trading_permissions' and not c['ok'] for c in denied['checks'])
    runner.mt5.positions_get.return_value = [NS(symbol=SYMBOL, magic=MAGIC)]
    exposure = runner.preflight()
    assert any(c['code'] == 'no_exposure' and not c['ok'] for c in exposure['checks'])
    runner.mt5.order_send.assert_not_called()


def test_demo_preflight_is_read_only_when_terminal_is_disconnected(tmp_path):
    mt = terminal()
    store = MT5DemoRunner(tmp_path / 'journal.sqlite3', mt)
    report = store.preflight()
    assert report['ready_to_start'] is False and report['live_market_ready'] is False
    assert {c['code'] for c in report['checks'] if not c['ok']} == {
        'candidate_loaded', 'demo_connected'}
    mt.initialize.assert_not_called()
    mt.symbol_select.assert_not_called()
    mt.order_send.assert_not_called()


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


@pytest.mark.parametrize('symbol', [SYMBOL, 'EURUSD.a'])
def test_journal_recovers_manual_exit_of_bot_position_once(runner, symbol):
    Deal = namedtuple('Deal', 'ticket position_id magic symbol entry profit commission swap fee')
    runner.mt5.history_deals_get.return_value = [
        Deal(1, 100, MAGIC, symbol, 0, 0, -1, 0, 0),
        Deal(2, 100, 0, symbol, 1, 20, -1, 0, 0),
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
    runner.mt5.positions_get.return_value = [NS(symbol=SYMBOL, magic=MAGIC, _asdict=lambda: {'ticket': 1})]
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
    runner.mt5.symbol_info.return_value.name = 'EURUSD.a'
    runner.configure(DemoConfig(symbol='EURUSD.a'))
    runner._tick()
    runner._tick()
    assert engine.evaluate.call_count == 2
    assert engine.evaluate.call_args.kwargs['symbol'] == 'EURUSD.a'
    assert runner.mt5.copy_rates_from_pos.call_args.args[0] == 'EURUSD.a'


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
    assert client.get('/api/mt5/preflight').json()['ready_to_start'] is False
    assert client.put('/api/mt5/strategy', json={'symbol': ''}).status_code == 422
    assert client.post('/api/mt5/start', json={}).status_code == 422
    assert client.get('/api/mt5/symbols', headers={'origin': 'https://untrusted.example'}).status_code == 403
    assert client.get('/api/mt5/preflight', headers={'origin': 'https://untrusted.example'}).status_code == 403


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


@pytest.mark.parametrize('threshold,expected', [(1, True), (2, False), (3, False)])
def test_single_bollinger_signal_respects_dynamic_threshold(threshold, expected):
    from app.core.engine.signal_engine import EngineConfig, SignalEngine
    from app.core.lsl.lsl_detector import Candle
    values = {key: False for key in DemoConfig.model_fields if key.startswith('use_')}
    values['use_bb'] = True
    assert DemoConfig(**values, min_confluence=threshold).min_confluence == threshold
    engine = SignalEngine(EngineConfig(**values, min_confluence=threshold))
    engine.initialise(10000)
    engine.atr_ind.compute = Mock(return_value=NS(value=1, is_spike=False))
    engine.bollinger.compute = Mock(return_value=NS(position='below_lower'))
    candles = [Candle(timestamp=1700000000 + i * 300, open=100, high=101,
                      low=99, close=100, volume=100) for i in range(100)]
    result = engine.evaluate(candles, symbol='1HZ75V', timeframe='M5')
    assert result.direction == 'buy'
    assert result.confluence_score == 1
    assert result.should_trade is expected
