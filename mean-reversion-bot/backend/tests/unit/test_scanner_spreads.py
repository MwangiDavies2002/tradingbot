import hashlib
import json
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.quant.scanner import Scanner, ScanConfig, snapshot
from app.quant.scanner_spreads import capture_spread


def instrument(**changes):
    return dict(provider='mt5', server='demo', account=1, symbol='TEST', captured_at=2101,
                point=.01, trade_tick_size=.01, price_basis='bid') | changes


def evidence(ts, points=10, **changes):
    return capture_spread({'time':ts, 'spread':points}, instrument(**changes), 'M5')


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda:1250)
    decision = dict(bar=900, direction='buy', atr=1, spread=.1, eligible=True, reasons=['test'])
    return Scanner(tmp_path/'scanner.db',
        loader=lambda *args: dict(scope='demo:1', instrument=instrument(), bars=[], spread_observations={900:evidence(900)}),
        evaluator=lambda *args: decision.copy())


def config(mode='candle_proxy_v1'):
    return ScanConfig(assets=[{'symbol':'TEST'}], spread_model=mode)


def bar(ts=1500, **changes):
    return dict(timestamp=ts, open=100, high=100.2, low=99.8, close=100) | changes


def test_adapter_records_raw_points_and_uses_point_not_tick_size():
    mt = Mock(TIMEFRAME_M5=5)
    mt.symbol_info_tick.return_value = NS(bid=100, ask=100.1, time=1250)
    mt.copy_rates_from_pos.return_value = [dict(time=900, open=100, high=101, low=99, close=100, tick_volume=10, spread=17)]
    runner = NS(lock=threading.RLock(), mt5=mt, _require_connection=Mock(return_value=(NS(server='demo',login=1),None,None)),
                _symbol_info=Mock(return_value=NS(point=.001, trade_tick_size=.05, chart_mode=0)))
    value = snapshot(runner,'TEST',config())['spread_observations'][900]
    assert value['spread_points'] == 17
    assert value['point'] == .001
    assert float(value['spread_price']) == .017
    assert value['scope'] == 'demo:1'
    assert value['status'] == 'available_proxy'
    mt.order_send.assert_not_called()


@pytest.mark.parametrize('points,changes', [(0,{}),(-1,{}),(float('nan'),{}),(1.5,{}),(10,{'point':None}),(10,{'price_basis':'unknown_or_last'})])
def test_unconfirmed_spread_blocks_new_entries(store, points, changes):
    store.loader = lambda *args: dict(scope='demo:1', instrument=instrument(), bars=[], spread_observations={900:evidence(900,points,**changes)})
    store.cycle('run',config(),None,'demo:1')
    assert store.ledger()['trades'] == []
    assert store.ledger()['observations'][0]['eligible'] is False


def test_buy_entry_uses_own_candle_spread_and_retains_each_consumed_proxy(store):
    cfg = config()
    store.cycle('run',cfg,None,'demo:1')
    store.resolve('run','TEST',[bar()],cfg,spread_observations={1500:evidence(1500,30)})
    p = store.ledger()['trades'][0]
    assert p['entry'] == 100.32
    assert p['spread'] == .1  # Original observation quote remains intact.
    assert p['entry_spread'] == .3
    reopened = Scanner(store.path)
    reopened.resolve('run','TEST',[bar(1800,high=104)],cfg,spread_observations={1800:evidence(1800,80)})
    p = reopened.ledger()['trades'][0]
    assert p['state'] == 'closed'
    assert p['exit_reason'] == 'target'
    assert p['exit_spread'] == .8
    assert [e['spread_points'] for e in p['spread_history']] == [30,80]
    assert p['r_multiple'] == pytest.approx(2-.02/1.5)
    assert json.loads(''.join(reopened.export()))['trades'][0]['spread_history'] == p['spread_history']


def test_short_widening_spread_triggers_ask_stop(store):
    store.evaluator=lambda *args: dict(bar=900,direction='sell',atr=1,spread=.1,eligible=True,reasons=['test'])
    cfg=config()
    store.cycle('run',cfg,None,'demo:1')
    store.resolve('run','TEST',[bar()],cfg,spread_observations={1500:evidence(1500)})
    store.resolve('run','TEST',[bar(1800)],cfg,spread_observations={1800:evidence(1800,160)})
    p=store.ledger()['trades'][0]
    assert p['state']=='closed'
    assert p['exit_reason']=='stop'
    assert p['exit']==pytest.approx(101.62)
    assert p['r_multiple'] < -1


@pytest.mark.parametrize('bad', [None, 'wrong_scope', 'wrong_price', 'zero'])
def test_missing_or_bad_outcome_spread_never_falls_back(store,bad):
    cfg=config()
    store.cycle('run',cfg,None,'demo:1')
    e=evidence(1500)
    if bad=='wrong_scope': e['scope']='other:1'
    if bad=='wrong_price': e['spread_price']='0.001'
    if bad=='zero': e=evidence(1500,0)
    store.resolve('run','TEST',[bar(high=105,low=95)],cfg,spread_observations={} if bad is None else {1500:e})
    p=store.ledger()['trades'][0]
    assert p['state']=='unresolved'
    assert p['r_multiple'] is None
    assert p['missing_spread_bar']==1500


def test_fixed_model_keeps_legacy_policy_hash_and_ignores_bar_spreads(store):
    cfg=config('fixed_quote')
    old_policy=cfg.model_dump(exclude={'assets','poll_seconds','spread_model','strategy_mode','strategy','research_run_id','candidate_snapshot'}) | {'paper_model':'tick_grid_v2'}
    expected=hashlib.sha256(json.dumps(old_policy,sort_keys=True).encode()).hexdigest()
    store.cycle('run',cfg,None,'demo:1')
    store.resolve('run','TEST',[bar(high=105,low=95)],cfg,spread_observations={1500:evidence(1500,100)})
    p=store.ledger()['trades'][0]
    assert p['policy_id']==expected
    assert p['entry']==100.12
    assert 'spread_history' not in p


def test_pinned_spread_model_survives_later_config_change(store):
    cfg=config()
    store.cycle('run',cfg,None,'demo:1')
    store.resolve('run','TEST',[bar()],config('fixed_quote'),spread_observations={1500:evidence(1500,30)})
    assert store.ledger()['trades'][0]['entry']==100.32
