import json
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.execution.mt5_demo import DemoConfig
from app.quant.scanner import ScanConfig, Scanner, evaluate


def strategy(**changes):
    return DemoConfig(**(dict(symbol='TEST.a', timeframe='M5', min_confluence=9,
                      use_zscore=True, use_rsi=False, use_bb=False, use_vwap=False,
                      use_hurst=False, use_lsl=False, use_smc=False, use_volume=False) | changes))


def config(**changes):
    return ScanConfig(**(dict(assets=[{'symbol': 'TEST.a'}], timeframe='M5', threshold=9,
                      strategy_mode='research_candidate') | changes))


def broker(contract_size=100, login=1):
    account = NS(server='demo', login=login, balance=10000)
    info = NS(name='TEST.a', trade_contract_size=contract_size, trade_tick_size=.01,
              volume_min=.01, volume_step=.01, volume_max=10)
    return account, info


def candidate(account=None, contract_size=100, validated_at=1000):
    account = account or broker()[0]
    return dict(run_id='validated-run', validated_at=validated_at,
                strategy=strategy().model_dump(),
                snapshot=dict(server=account.server, account=account.login,
                              contract_size=contract_size, tick_size=.01,
                              volume_min=.01, volume_step=.01, volume_max=10))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1250)
    store = Scanner(tmp_path/'scanner.db', loader=lambda *args: dict(scope='demo:1', bars=[]),
                    evaluator=lambda *args: dict(bar=900, direction='buy', eligible=False, reasons=['fixture']))
    account, info = broker()
    runner = NS(lock=threading.RLock(), config=strategy(), state={'running': False},
                _require_connection=Mock(return_value=(account,None,None)),
                _symbol_info=Mock(return_value=info),
                _research_candidate=Mock(return_value=candidate(account)), mt5=Mock())
    return store, runner


def test_validated_start_loads_server_candidate_and_pins_strategy(setup):
    store, runner = setup
    body = config(strategy=strategy(min_confluence=9).model_copy(update={'risk_pct': .01}),
                  research_run_id='user-supplied', candidate_snapshot={'fake': True})
    result = store.start(body, runner, 'operator')
    assert result['run']['config']['strategy'] == runner.config.model_dump()
    assert result['run']['config']['research_run_id'] == 'validated-run'
    assert result['run']['config']['candidate_snapshot'] == candidate()['snapshot']
    store.stop()
    assert len(store.ledger()['trades']) == 0
    runner.mt5.order_send.assert_not_called()


@pytest.mark.parametrize('case,match', [
    ('missing','passing research'), ('expired','passing research'), ('future','passing research'),
    ('symbol','Selected pair'), ('timeframe','Selected pair'), ('threshold','Selected pair'),
    ('changed_strategy','Selected pair'), ('account','different demo account'),
    ('contract','broker contract changed'), ('running','Stop demo execution'),
])
def test_invalid_candidate_cannot_start_or_submit_orders(setup, case, match):
    store, runner = setup
    cfg = config()
    if case == 'missing': runner._research_candidate.return_value = None
    if case == 'expired': runner._research_candidate.return_value = candidate(validated_at=1250-7*86400-1)
    if case == 'future': runner._research_candidate.return_value = candidate(validated_at=1251)
    if case == 'symbol': cfg = config(assets=[{'symbol':'OTHER.a'}])
    if case == 'timeframe': cfg = config(timeframe='M15')
    if case == 'threshold': cfg = config(threshold=8)
    if case == 'changed_strategy': runner.config = strategy().model_copy(update={'risk_pct': .01})
    if case == 'account': runner._require_connection.return_value = (broker(login=2)[0],None,None)
    if case == 'contract': runner._symbol_info.return_value = broker(contract_size=1)[1]
    if case == 'running': runner.state['running'] = True
    with pytest.raises(ValueError, match=match):
        store.start(cfg, runner, 'operator')
    assert store.worker is None
    assert store.ledger()['trades'] == []
    runner.mt5.order_send.assert_not_called()


def test_manual_mode_cannot_claim_research_evidence_and_candidate_is_one_pair():
    with pytest.raises(ValidationError):
        ScanConfig(assets=[{'symbol':'TEST.a'}], strategy=strategy())
    with pytest.raises(ValidationError):
        config(assets=[{'symbol':'TEST.a'},{'symbol':'OTHER.a'}])


def test_engine_uses_research_signal_toggles_and_threshold(monkeypatch):
    import app.quant.scanner as scanner
    observed = []
    engine = Mock()
    engine.evaluate.return_value = NS(should_trade=True,direction='buy',reason='fixture',confluence_score=9)
    engine.atr_ind.compute.return_value = NS(value=1,is_spike=False)
    engine.hurst_ind.compute.return_value = NS(value=.3)
    engine.zscore.compute.return_value = NS(value=-1)
    monkeypatch.setattr(scanner, 'SignalEngine', lambda settings: observed.append(settings) or engine)
    cfg = config(strategy=strategy())
    bars = [dict(timestamp=i*300,open=100,high=101,low=99,close=100,volume=100) for i in range(100)]
    data = dict(scope='demo:1', bars=bars, bid=100,ask=100.01,quote_time=30010,balance=12345)
    evaluate(data,cfg,'TEST.a',30010)
    assert observed[0].min_confluence == cfg.strategy.min_confluence
    assert observed[0].use_rsi is False and observed[0].use_bb is False
    assert observed[0].use_zscore is True
    engine.initialise.assert_called_once_with(12345)


def test_contract_drift_unresolves_candidate_exposure(setup):
    store, runner = setup
    cfg=config()
    store.start(cfg,runner,'operator')
    with store.db() as db:
        p={'id':'trade','symbol':'TEST.a','direction':'buy','state':'pending','r_multiple':None}
        db.execute('INSERT INTO paper VALUES(?,?,?,?,?)',('trade',store.status()['run']['id'],'TEST.a','pending',json.dumps(p)))
    store.loader = lambda *args: dict(scope='demo:1', bars=[], instrument=dict(
        trade_contract_size=1,trade_tick_size=.01,volume_min=.01,volume_step=.01,volume_max=10))
    store.cycle(store.status()['run']['id'],cfg,None,'demo:1')
    result=next(p for p in store.ledger()['trades'] if p['id']=='trade')
    assert result['state']=='unresolved'
    assert 'contract changed' in result['exit_reason']
    store.stop()


def test_forward_review_counts_are_scoped_to_account_pair_and_policy(tmp_path):
    store = Scanner(tmp_path/'scanner.db')
    with store.db() as db:
        for i in range(300):
            policy = 'policy-a' if i < 100 or i >= 200 else 'policy-b'
            account = 'demo:1' if i < 200 else 'demo:2'
            symbol = 'TEST.a' if i < 200 else 'TEST.b'
            record = dict(id=f'trade-{i}', run_id=f'scan-{account}-{policy}', symbol=symbol,
                          scope=account, timeframe='M5', policy_id=policy,
                          policy={'research_run_id': f'research-{policy}'},
                          observed=i, score=60, regime='RANGE', session='UTC 00-06',
                          setup='mean_reversion_v1', volatility='normal', news='unknown',
                          r_multiple=1 if i % 2 else -1)
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',
                       (record['id'], record['run_id'], record['symbol'], i, i, json.dumps(record)))
            db.execute('INSERT INTO paper VALUES(?,?,?,?,?)',
                       (record['id'], record['run_id'], record['symbol'], 'closed', json.dumps(record)))
        pending = dict(id='pending', run_id='scan-demo:1-policy-a', symbol='TEST.a', scope='demo:1',
                       timeframe='M5', policy_id='policy-a', observed=301)
        db.execute('INSERT INTO paper VALUES(?,?,?,?,?)',
                   ('pending', pending['run_id'], pending['symbol'], 'pending', json.dumps(pending)))
    evidence = store.analytics()
    assert evidence['overall']['count'] == 300
    assert evidence['overall']['sample'] == 'review_required'
    assert len(evidence['per_pair_policy']) == 3
    assert {item['scope'] for item in evidence['per_pair_policy']} == {'demo:1', 'demo:2'}
    assert {(item['symbol'], item['policy_id']) for item in evidence['per_pair_policy']} == {
        ('TEST.a', 'policy-a'), ('TEST.a', 'policy-b'), ('TEST.b', 'policy-a')}
    assert all(item['count'] == 100 and item['sample'] == 'exploratory'
               for item in evidence['per_pair_policy'])
    first = next(item for item in evidence['per_pair_policy'] if item['scope'] == 'demo:1'
                 and item['policy_id'] == 'policy-a')
    assert first['research_run_id'] == 'research-policy-a'
    assert first['observations'] == 100
    assert first['states'] == {'closed': 100, 'pending': 1}
