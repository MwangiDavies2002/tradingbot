import json
import math
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from app.quant.scanner import Scanner, ScanConfig, evaluate, snapshot


def config():
    return ScanConfig(assets=[{'symbol': 'EURUSD.a'}, {'symbol': 'XAUUSD'}])


def decision(data, cfg, symbol, now):
    return dict(bar=900, direction='buy', raw_score=8, score=40, deviation=-2, hurst=.3,
                atr=1, spread=.1, regime='RANGE', volatility='normal', news='unknown',
                session='UTC 00-06', setup='mean_reversion_v1', reasons=['test'], eligible=True)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1250)
    return Scanner(tmp_path/'scanner.sqlite3', loader=lambda *args: {'scope':'demo:1', 'bars':[], 'instrument': {'trade_tick_size': .01}}, evaluator=decision)


def test_selected_pairs_persist_once_per_candle(store):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    store.cycle('run', cfg, None, 'demo:1')
    assert len(store.ledger()['observations']) == 2
    assert len(store.ledger()['trades']) == 2
    assert {r['symbol'] for r in store.ledger()['trades']} == {'EURUSD.a','XAUUSD'}
    reopened = Scanner(store.path)
    assert len(reopened.ledger()['observations']) == 2
    assert reopened.analytics()['states'] == {'pending': 2}


def test_one_asset_failure_does_not_hide_other(store):
    def loader(runner, symbol, cfg):
        if symbol == 'EURUSD.a':
            raise ValueError('No fresh quote')
        return {'scope':'demo:1', 'bars':[], 'instrument': {'trade_tick_size': .01}}
    store.loader = loader
    store.cycle('run', config(), None, 'demo:1')
    assert len(store.ledger()['observations']) == 2
    assert len(store.ledger()['trades']) == 1
    assert any(r.get('error') for r in store.status()['latest'])
    failed = next(r for r in store.records()['items'] if r.get('error'))
    assert failed['id']
    exported = json.loads(''.join(store.export()))
    assert next(r for r in exported['observations'] if r.get('error'))['id'] == failed['id']


def test_account_change_blocks_paper_entries(store):
    store.cycle('run', config(), None, 'different:2')
    assert store.ledger()['trades'] == []
    assert all(r['error'] for r in store.status()['latest'])


def test_future_entry_and_stop_first_ambiguity(store):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    store.resolve('run','EURUSD.a',[dict(timestamp=1200,open=100,high=105,low=95,close=100)],cfg)
    assert next(p for p in store.ledger()['trades'] if p['symbol']=='EURUSD.a')['state']=='pending'
    store.resolve('run','EURUSD.a',[dict(timestamp=1500,open=100,high=105,low=95,close=100)],cfg)
    p=next(p for p in store.ledger()['trades'] if p['symbol']=='EURUSD.a')
    assert p['state']=='closed'
    assert p['entry']==pytest.approx(100.12)
    assert p['r_multiple'] < -1
    assert p['exit_reason']=='stop_first_ambiguous'
    assert store.analytics()['overall']['count']==1
    assert store.analytics()['groups']['news']['unknown']['count']==1


def test_outcome_gap_stays_unresolved(store):
    store.cycle('run', config(), None, 'demo:1')
    store.resolve('run','EURUSD.a',[dict(timestamp=1800,open=100,high=105,low=95,close=100)],config())
    p=next(p for p in store.ledger()['trades'] if p['symbol']=='EURUSD.a')
    assert p['state']=='unresolved'
    assert p['r_multiple'] is None
    assert store.analytics()['overall']['count']==0


def test_existing_paper_exposure_prevents_second_entry(store):
    store.cycle('run', config(), None, 'demo:1')
    store.evaluator=lambda *args: decision(*args) | {'bar':1200}
    store.cycle('run', config(), None, 'demo:1')
    assert len(store.ledger()['observations'])==4
    assert len(store.ledger()['trades'])==2


def test_restart_does_not_resume_and_recovers_exposure(store):
    with store.db() as db:
        db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?)', ('run',1,'running',config().model_dump_json(),'operator',None))
    store.cycle('run', config(), None, 'demo:1')
    restarted=Scanner(store.path)
    assert restarted.status()['run']['status']=='interrupted'
    assert all(p['state']=='unresolved' for p in restarted.ledger()['trades'])
    assert restarted.worker is None


def test_process_lock_prevents_second_scanner(store):
    handle=store.acquire()
    try:
        with pytest.raises(ValueError,match='already running'):
            Scanner(store.path).acquire()
    finally:
        handle.close()


@pytest.mark.parametrize('assets', [[{'symbol':' EURUSD'}], [{'symbol':'EURUSD'},{'symbol':'EURUSD'}]])
def test_symbol_config_rejects_ambiguity(assets):
    with pytest.raises(ValidationError):
        ScanConfig(assets=assets)


def valid_data():
    return {'scope':'demo:1','bid':100,'ask':100.01,'quote_time':30010,
            'bars':[dict(timestamp=i*300, open=100+math.sin(i), high=102,low=98,close=100+math.sin(i),volume=100) for i in range(100)]}


def test_real_engine_emits_finite_research_metrics():
    result=evaluate(valid_data(),config(),'EURUSD.a',30010)
    assert 0<=result['score']<=100
    assert result['news']=='unknown'
    assert result['regime'] in {'RANGE','TREND','UNCERTAIN','HIGH_VOLATILITY','LOW_LIQUIDITY'}
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('case', ['stale','gap','future','ohlc','quote'])
def test_bad_data_rejected_before_evaluation(case):
    data=valid_data()
    if case=='stale': data['bars']=data['bars'][:-3]
    if case=='gap': data['bars'][-5]['timestamp']+=1
    if case=='future': data['bars'][-1]['timestamp']=30000
    if case=='ohlc': data['bars'][-1]['low']=105
    if case=='quote': data['quote_time']=100
    with pytest.raises(ValueError):
        evaluate(data,config(),'EURUSD.a',30010)


def test_snapshot_reads_exact_symbols_without_execution():
    mt=Mock()
    mt.TIMEFRAME_M5=5
    mt.symbol_info_tick.return_value=NS(bid=100,ask=100.1,time=30010)
    mt.copy_rates_from_pos.return_value=[dict(time=29700,open=100,high=101,low=99,close=100,tick_volume=10)]
    runner=NS(lock=threading.RLock(),mt5=mt,_require_connection=Mock(return_value=(NS(server='demo',login=1),None,None)),_symbol_info=Mock())
    result=snapshot(runner,'EURUSD.a',config())
    assert result['scope']=='demo:1'
    mt.copy_rates_from_pos.assert_called_once_with('EURUSD.a',5,1,500)
    mt.order_send.assert_not_called()


def test_restarting_same_policy_does_not_recount_same_signal(store):
    store.cycle('run1',config(),None,'demo:1')
    store.cycle('run2',config(),None,'demo:1')
    assert len(store.ledger()['observations'])==2
    assert len(store.ledger()['trades'])==2


def test_thread_start_stop_never_submits_orders(store):
    runner=NS(lock=threading.RLock(),_require_connection=Mock(return_value=(NS(server='demo',login=1),None,None)),_symbol_info=Mock(),mt5=Mock())
    assert store.start(config(),runner,'operator')['run']['status']=='running'
    assert store.stop()['run']['status']=='stopped'
    runner.mt5.order_send.assert_not_called()
    assert store.handle is None


def test_scanner_api_enforces_roles_and_origin(store, monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.scanner import router
    from app.api.security import protect_api
    from app.config import settings
    for role in ('operator','viewer'):
        monkeypatch.setattr(settings, f'API_{role.upper()}_KEY_HASH', hashlib.sha256((role+'x'*32).encode()).hexdigest())
    app=FastAPI()
    app.state.scanner=store
    app.middleware('http')(protect_api)
    app.include_router(router,prefix='/api/scanner')
    client=TestClient(app)
    headers={'Authorization':'Bearer viewer'+'x'*32}
    assert client.get('/api/scanner').status_code==401
    assert client.get('/api/scanner',headers=headers).status_code==200
    assert client.get('/api/scanner/records?limit=201',headers=headers).status_code==422
    assert client.get('/api/scanner/records?kind=invalid',headers=headers).status_code==422
    assert client.get('/api/scanner/records',headers=headers).json()['items']==[]
    assert client.get('/api/scanner/export',headers=headers).json()['execution_enabled'] is False
    assert client.get('/api/scanner/export').status_code==401
    assert client.post('/api/scanner/start',headers=headers,json=config().model_dump()).status_code==403
    assert client.post('/api/scanner/stop',headers=headers,json={}).status_code==403
    headers={'Authorization':'Bearer operator'+'x'*32}
    assert client.post('/api/scanner/stop',headers=headers,json={}).status_code==200
    assert client.get('/api/scanner',headers=headers|{'Origin':'https://untrusted.example'}).status_code==403

@pytest.mark.parametrize('hurst,spread,spike,expected', [(.3,.01,False,'RANGE'),(.7,.01,False,'TREND'),(.5,.01,False,'UNCERTAIN'),(.3,1.,False,'LOW_LIQUIDITY'),(.3,.01,True,'HIGH_VOLATILITY')])
def test_regime_gate_blocks_unsuitable_conditions(monkeypatch,hurst,spread,spike,expected):
    import app.quant.scanner as module
    engine=Mock()
    engine.evaluate.return_value=NS(should_trade=True,direction='buy',reason='zscore',confluence_score=8)
    engine.atr_ind.compute.return_value=NS(value=2,is_spike=spike)
    engine.hurst_ind.compute.return_value=NS(value=hurst)
    engine.zscore.compute.return_value=NS(value=-2)
    monkeypatch.setattr(module,'SignalEngine',lambda cfg:engine)
    data=valid_data(); data['ask']=data['bid']+spread
    result=evaluate(data,config(),'EURUSD.a',30010)
    assert result['regime']==expected
    assert result['eligible']==(expected=='RANGE')


def test_short_paper_target_includes_spread_and_slippage(store):
    store.evaluator=lambda *args: decision(*args)|{'direction':'sell'}
    store.cycle('run',config(),None,'demo:1')
    store.resolve('run','EURUSD.a',[dict(timestamp=1500,open=100,high=100.2,low=96,close=97)],config())
    p=next(p for p in store.ledger()['trades'] if p['symbol']=='EURUSD.a')
    assert p['entry']==pytest.approx(99.98)
    assert p['exit_reason']=='target'
    assert 1.9<p['r_multiple']<2


def seed_records(store, count=505):
    with store.db() as db:
        db.execute('INSERT OR IGNORE INTO scans VALUES(?,?,?,?,?,?)', ('seed',1,'stopped',config().model_dump_json(),'operator',None))
        for i in range(count):
            data=dict(id=f'seed-{i}',symbol='EURUSD.a',scope='demo:1',observed=i,reasons=['seed'],r_multiple=1,score=40,regime='RANGE',session='UTC 00-06',setup='test',volatility='normal',news='unknown')
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',(data['id'],'seed','EURUSD.a',i,i,json.dumps(data)))
            db.execute('INSERT INTO paper VALUES(?,?,?,?,?)',(data['id'],'seed','EURUSD.a','closed',json.dumps(data)))


@pytest.mark.parametrize('kind',['observations','trades'])
def test_cursor_pages_cover_history_without_new_insert_drift(store,kind):
    seed_records(store)
    page=store.records(kind,200)
    ceiling=page['through']
    seen=[r['id'] for r in page['items']]
    # Inserts while browsing must not shift the older pages or change their total.
    with store.db() as db:
        data=json.dumps({'id':'later','observed':999,'symbol':'EURUSD.a'})
        db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',('later','seed','EURUSD.a',999,999,data))
        db.execute('INSERT INTO paper VALUES(?,?,?,?,?)',('later','seed','EURUSD.a','pending',data))
    while page['next_before'] is not None:
        page=store.records(kind,200,page['next_before'],ceiling)
        assert page['total']==505
        seen.extend(r['id'] for r in page['items'])
    assert len(seen)==len(set(seen))==505
    assert 'later' not in seen
    assert store.records(kind,1)['items'][0]['id']=='later'


def test_export_is_complete_consistent_and_preserves_authoritative_state(store):
    seed_records(store)
    stream=store.export()
    first=next(stream)  # Capture the read transaction before concurrent writes.
    with store.db() as db:
        db.execute("UPDATE paper SET state='unresolved' WHERE id='seed-0'")
        db.execute("DELETE FROM observations WHERE id='seed-0'")
    result=json.loads(first+''.join(stream))
    assert result['execution_enabled'] is False
    assert result['runs'][0]['config']['timeframe']=='M5'
    assert len(result['observations'])==len(result['trades'])==505
    assert result['trades'][0]['state']=='closed'
    latest=json.loads(''.join(store.export()))
    assert latest['trades'][0]['state']=='unresolved'
    assert len(latest['observations'])==504


def test_pagination_validates_kind_and_bounds(store):
    for args in [('scans',50),('observations',201),('trades',0),('trades',1,-1)]:
        with pytest.raises(ValueError):
            store.records(*args)
    assert store.records()['items']==[]
    assert json.loads(''.join(store.export()))['trades']==[]


def test_captured_identity_distinguishes_accounts_and_contracts():
    mt=Mock(); mt.TIMEFRAME_M5=5
    mt.symbol_info_tick.return_value=NS(bid=100,ask=100.1,time=30010)
    mt.copy_rates_from_pos.return_value=[]
    account=NS(server='Broker-Demo',login=1,currency='USD')
    info=NS(trade_tick_size=.00001,trade_contract_size=100000,currency_base='EUR',currency_profit='USD')
    runner=NS(lock=threading.RLock(),mt5=mt,_require_connection=Mock(return_value=(account,None,None)),_symbol_info=Mock(return_value=info))
    first=snapshot(runner,'EURUSD.a',config())['instrument']
    assert first['trade_contract_size']==100000
    assert first['account_currency']=='USD'
    assert first['volume_step'] is None
    account.login=2
    second=snapshot(runner,'EURUSD.a',config())['instrument']
    assert first['identity']!=second['identity']
    third=snapshot(runner,'EURUSD',config())['instrument']
    assert second['identity']!=third['identity']
    mt.order_send.assert_not_called()


@pytest.mark.parametrize('tick', [None, 0, -1, 'NaN', 'Infinity', 'invalid', True])
def test_invalid_tick_preserves_rejected_observations(store, tick):
    store.loader = lambda *args: {'scope': 'demo:1', 'bars': [], 'instrument': {'trade_tick_size': tick}}
    store.cycle('run', config(), None, 'demo:1')
    assert store.ledger()['trades'] == []
    assert len(store.ledger()['observations']) == 2
    assert all(not r['eligible'] and 'tick size' in r['reasons'][-1] for r in store.ledger()['observations'])


@pytest.mark.parametrize('side,entry,stop,target,exit_price', [
    ('buy', 100.25, 98.75, 103.25, 103), ('sell', 99.75, 101.25, 96.75, 97),
])
def test_quarter_tick_target_fills(store, side, entry, stop, target, exit_price):
    store.loader = lambda *args: {'scope': 'demo:1', 'bars': [], 'instrument': {'trade_tick_size': .25}}
    store.evaluator = lambda *args: decision(*args) | {'direction': side}
    store.cycle('run', config(), None, 'demo:1')
    bar = dict(timestamp=1500, open=100, high=104 if side == 'buy' else 100, low=100 if side == 'buy' else 96, close=100)
    store.resolve('run', 'EURUSD.a', [bar], config())
    p = next(p for p in store.ledger()['trades'] if p['symbol'] == 'EURUSD.a')
    assert p['state'] == 'closed'
    assert (p['entry'], p['stop'], p['target'], p['exit']) == (entry, stop, target, exit_price)
    assert p['exit_reason'] == 'target'
    assert p['r_multiple'] == pytest.approx(2.75 / 1.5)
    assert p['policy']['paper_model'] == p['paper_model'] == 'tick_grid_v2'


@pytest.mark.parametrize('side,entry,stop,target,exit_price', [
    ('buy', 101, 99, 105, 99), ('sell', 99, 101, 95, 101),
])
def test_coarse_ticks_use_actual_risk_and_round_time_exit(store, side, entry, stop, target, exit_price):
    store.loader = lambda *args: {'scope': 'demo:1', 'bars': [], 'instrument': {'trade_tick_size': 1}}
    store.evaluator = lambda *args: decision(*args) | {'direction': side}
    cfg = config().model_copy(update={'max_hold_bars': 1})
    store.cycle('run', cfg, None, 'demo:1')
    store.resolve('run', 'EURUSD.a', [dict(timestamp=1500, open=100, high=100.5, low=99.5, close=100)], cfg)
    p = next(p for p in store.ledger()['trades'] if p['symbol'] == 'EURUSD.a')
    assert (p['entry'], p['stop'], p['target'], p['exit']) == (entry, stop, target, exit_price)
    assert p['exit_reason'] == 'time_limit'
    assert p['requested_risk_distance'] == 1.5
    assert p['risk_distance'] == 2
    assert p['r_multiple'] == -1


@pytest.mark.parametrize('side,opening,exit_price', [('buy', 98, 97.75), ('sell', 102, 102.25)])
def test_gap_stop_grid_survives_reopen(store, side, opening, exit_price):
    store.loader = lambda *args: {'scope': 'demo:1', 'bars': [], 'instrument': {'trade_tick_size': .25}}
    store.evaluator = lambda *args: decision(*args) | {'direction': side}
    store.cycle('run', config(), None, 'demo:1')
    store.resolve('run', 'EURUSD.a', [dict(timestamp=1500, open=100, high=100.5, low=99.5, close=100)], config())
    reopened = Scanner(store.path)
    reopened.resolve('run', 'EURUSD.a', [dict(timestamp=1800, open=opening, high=opening+.5, low=opening-.5, close=opening)], config())
    p = next(p for p in reopened.ledger()['trades'] if p['symbol'] == 'EURUSD.a')
    assert p['exit'] == exit_price
    assert p['exit_reason'] == 'stop'
    assert p['r_multiple'] < -1


def test_legacy_pending_evidence_keeps_original_prices(store):
    store.cycle('run', config(), None, 'demo:1')
    with store.db() as db:
        for key, raw in db.execute('SELECT id,payload FROM paper').fetchall():
            p = json.loads(raw)
            p.pop('paper_model')
            p.pop('instrument')
            db.execute('UPDATE paper SET payload=? WHERE id=?', (json.dumps(p), key))
    store.resolve('run', 'EURUSD.a', [dict(timestamp=1500, open=100, high=105, low=95, close=100)], config())
    p = next(p for p in store.ledger()['trades'] if p['symbol'] == 'EURUSD.a')
    assert p['entry'] == pytest.approx(100.12)
    assert p['exit'] == pytest.approx(98.60)
    assert 'requested_risk_distance' not in p


def test_nonpositive_rounded_levels_remain_unresolved(store):
    store.cycle('run', config(), None, 'demo:1')
    store.resolve('run', 'EURUSD.a', [dict(timestamp=1500, open=1, high=2, low=.5, close=1)], config())
    p = next(p for p in store.ledger()['trades'] if p['symbol'] == 'EURUSD.a')
    assert p['state'] == 'unresolved'
    assert p['r_multiple'] is None
    assert store.analytics()['overall']['count'] == 0
