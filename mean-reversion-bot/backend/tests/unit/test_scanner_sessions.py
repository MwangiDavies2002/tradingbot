import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import threading

import pytest
from pydantic import ValidationError

from app.quant.scanner import Scanner, ScanConfig, evaluate
from app.quant.scanner_sessions import ScanCalendar


def calendar(**updates):
    return dict(scope='demo:1', symbol='EURUSD.a', source='supplied test schedule',
                revision='r1', published_at=0, valid_from=0, valid_until=7200,
                windows=[dict(open=0, close=1800), dict(open=3600, close=7200)]) | updates


def config(schedule=None):
    return ScanConfig(assets=[dict(symbol='EURUSD.a', calendar=schedule or calendar())])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1250)
    decision = dict(bar=900, direction='buy', raw_score=8, score=40, atr=1, spread=.1,
                    regime='RANGE', volatility='normal', news='unknown', session='UTC 00-06',
                    setup='test', reasons=['test'], eligible=True)
    return Scanner(tmp_path / 'scanner.sqlite3',
                   loader=lambda *args: dict(scope='demo:1', bars=[], instrument={'trade_tick_size': .01}),
                   evaluator=lambda *args: decision.copy())


@pytest.mark.parametrize('changes', [
    {'source': ' '}, {'revision': ''}, {'valid_until': 0}, {'published_at': -1},
    {'windows': []}, {'windows': [{'open': 300, 'close': 300}]},
    {'windows': [{'open': 0, 'close': 7500}]},
    {'windows': [{'open': 3600, 'close': 7200}, {'open': 0, 'close': 1800}]},
    {'windows': [{'open': 0, 'close': 1800}, {'open': 1700, 'close': 3600}]},
    {'windows': [{'open': 0, 'close': 1800}, {'open': 1800, 'close': 3600}]},
    {'windows': [{'open': True, 'close': 1800}]},
])
def test_invalid_calendar_contract(changes):
    with pytest.raises(ValidationError):
        ScanCalendar.model_validate(calendar(**changes))


@pytest.mark.parametrize('changes', [{'symbol': 'EURUSD'}, {'windows': [{'open': 1, 'close': 1800}]}])
def test_config_rejects_symbol_or_grid_mismatch(changes):
    with pytest.raises(ValidationError):
        config(calendar(**changes))


@pytest.mark.parametrize('changes', [{'scope': 'other:1'}, {'published_at': 1251}, {'valid_until': 1200, 'windows': [{'open': 0, 'close': 1200}]}])
def test_runtime_scope_and_availability_reject_without_broker_orders(store, changes):
    cfg = config(calendar(**changes))
    runner = NS(lock=threading.RLock(), _require_connection=Mock(return_value=(NS(server='demo', login=1), None, None)),
                _symbol_info=Mock(), mt5=Mock())
    with pytest.raises(ValueError):
        store.start(cfg, runner, 'operator')
    assert store.worker is None
    assert store.ledger()['trades'] == []
    runner.mt5.order_send.assert_not_called()
    store.cycle('run', cfg, None, 'demo:1')
    assert store.ledger()['observations'][0]['calendar'] == cfg.assets[0].calendar.model_dump()
    assert store.ledger()['trades'] == []


def history():
    bars = [dict(timestamp=i*300 + (1800 if i >= 90 else 0), open=100, high=102,
                 low=98, close=100, volume=100) for i in range(100)]
    data = dict(scope='demo:1', bid=100, ask=100.01, quote_time=31810, bars=bars)
    cfg = config(calendar(valid_until=36000, windows=[dict(open=0, close=27000), dict(open=28800, close=36000)]))
    return data, cfg


def test_scheduled_closure_passes_real_engine_but_unknown_calendar_rejects():
    data, cfg = history()
    assert evaluate(data, cfg, 'EURUSD.a', 31810)['regime'] == 'LOW_LIQUIDITY'
    unknown = ScanConfig(assets=[dict(symbol='EURUSD.a')])
    with pytest.raises(ValueError, match='Recent candle gap'):
        evaluate(data, unknown, 'EURUSD.a', 31810)


@pytest.mark.parametrize('case', ['missing', 'outside', 'closed_now', 'unpublished'])
def test_calendar_does_not_hide_missing_candles_or_closed_sessions(case):
    data, cfg = history()
    now = 31810
    if case == 'missing':
        # Keep 100 samples while replacing one expected slot with an older slot.
        data['bars'][91]['timestamp'] += 300
        data['bars'][92]['timestamp'] += 300
        data['bars'].pop(93)
        data['bars'].append(dict(timestamp=31800, open=100, high=102, low=98, close=100))
        now = 32110
        data['quote_time'] = now
    elif case == 'outside':
        data['bars'][90]['timestamp'] = 27000
    elif case == 'closed_now':
        cfg = config(calendar(valid_until=36000, windows=[dict(open=0, close=27000), dict(open=28800, close=31800)]))
    else:
        cfg.assets[0].calendar.published_at = 31811
    with pytest.raises(ValueError):
        evaluate(data, cfg, 'EURUSD.a', now)


def test_pinned_calendar_skips_closure_and_fills_reopening_gap(store):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    store.resolve('run', 'EURUSD.a', [dict(timestamp=1500, open=100, high=100.5, low=99.5, close=100)], cfg)
    assert store.ledger()['trades'][0]['state'] == 'open'
    # A later config does not rewrite the calendar pinned to this trade.
    cfg.assets[0].calendar = None
    reopened = Scanner(store.path)
    reopened.resolve('run', 'EURUSD.a', [dict(timestamp=3600, open=98, high=98.5, low=97.5, close=98)], cfg)
    p = reopened.ledger()['trades'][0]
    assert p['state'] == 'closed'
    assert p['exit_reason'] == 'stop'
    assert p['exit'] == 97.98
    assert p['bars_held'] == 2
    assert p['r_multiple'] < -1
    exported = json.loads(''.join(reopened.export()))['trades'][0]
    assert exported['policy']['calendar']['revision'] == 'r1'


def test_missing_open_session_bar_stays_unresolved(store):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    # The 1500 candle was scheduled open; a closure must not excuse its loss.
    store.resolve('run', 'EURUSD.a', [dict(timestamp=3600, open=100, high=101, low=99, close=100)], cfg)
    assert store.ledger()['trades'][0]['state'] == 'unresolved'
    assert store.ledger()['trades'][0]['r_multiple'] is None


def test_pending_entry_waits_for_next_scheduled_full_bar(store, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1750)
    store.cycle('run', config(), None, 'demo:1')
    assert store.ledger()['trades'][0]['enter_after'] == 3600


def test_no_future_coverage_blocks_entry_and_expiry_preserves_unresolved(store, monkeypatch):
    cfg = config(calendar(valid_until=1800, windows=[dict(open=0, close=1800)]))
    store.cycle('run', cfg, None, 'demo:1')
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1801)
    store.cycle('run', cfg, None, 'demo:1')
    assert store.ledger()['trades'][0]['state'] == 'unresolved'
    assert 'expired' in store.ledger()['trades'][0]['exit_reason']
    other = Scanner(store.path.parent / 'other.sqlite3', loader=store.loader, evaluator=store.evaluator)
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1750)
    other.cycle('run', cfg, None, 'demo:1')
    assert other.ledger()['trades'] == []
    assert other.ledger()['observations'][0]['eligible'] is False


def test_calendar_revision_separates_evidence_policy_and_dedup(store):
    store.cycle('run1', config(), None, 'demo:1')
    store.cycle('run2', config(calendar(revision='r2')), None, 'demo:1')
    observations = store.ledger()['observations']
    assert len(observations) == 2
    assert observations[0]['policy_id'] != observations[1]['policy_id']


def test_entry_gate_failure_still_resolves_validated_closed_history(store, monkeypatch):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1810)
    store.loader = lambda *args: dict(scope='demo:1', bars=[dict(timestamp=1500, open=100, high=105, low=95, close=100)])
    store.evaluator = Mock(side_effect=ValueError('Stale quote'))
    store.cycle('run', cfg, None, 'demo:1')
    assert store.ledger()['trades'][0]['state'] == 'closed'
    assert store.status()['latest'][0]['error']


def test_forming_candle_cannot_resolve_existing_trade(store):
    cfg = config()
    store.cycle('run', cfg, None, 'demo:1')
    store.loader = lambda *args: dict(scope='demo:1', bars=[dict(timestamp=1500, open=100, high=105, low=95, close=100)])
    store.cycle('run', cfg, None, 'demo:1')
    assert store.ledger()['trades'][0]['state'] == 'pending'
    assert 'Forming' in store.status()['latest'][0]['reasons'][0]


def test_calendar_api_validation_and_readonly_permissions(monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.scanner import router
    from app.api.security import protect_api
    from app.config import settings

    app = FastAPI()
    app.middleware('http')(protect_api)
    app.include_router(router, prefix='/api/scanner')
    app.state.scanner = Mock()
    app.state.scanner.start.return_value = {'execution_enabled': False}
    app.state.mt5_demo = object()
    for role in ('operator', 'viewer'):
        monkeypatch.setattr(settings, f'API_{role.upper()}_KEY_HASH', hashlib.sha256((role+'x'*32).encode()).hexdigest())
    client = TestClient(app)
    body = config().model_dump()
    operator = {'Authorization': 'Bearer operator'+'x'*32}
    viewer = {'Authorization': 'Bearer viewer'+'x'*32}
    assert client.post('/api/scanner/start', json=body, headers=viewer).status_code == 403
    assert client.post('/api/scanner/start', json=body, headers=operator).status_code == 200
    captured = app.state.scanner.start.call_args.args[0]
    assert captured.assets[0].calendar.model_dump() == calendar()
    body['assets'][0]['calendar']['windows'][0]['open'] = 1
    assert client.post('/api/scanner/start', json=body, headers=operator).status_code == 422
    assert app.state.scanner.start.call_count == 1
