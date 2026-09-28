import hashlib
import json
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.routes.scanner import router
from app.api.security import protect_api
from app.config import settings
from app.database.models import Base
from app.database.session import get_db
from app.institutional.catalog import register_spec
from app.institutional.data import fingerprint
from app.institutional.instruments import InstrumentSpec
from app.quant.scanner import Scanner, ScanConfig
from app.quant.scanner_mappings import MappingRequest, check_mapping, compare_mappings


def spec(**changes):
    return InstrumentSpec.model_validate(dict(instrument_id='GOLD', venue='demo', venue_symbol='XAUUSD.a', revision='r1',
        source='synthetic broker specification', product='linear_contract', underlying_unit='ounce', quote_currency='USD',
        contract_size='100', tick_size='0.01', quantity_step='0.01', min_quantity='0.01', max_quantity='10', min_notional='0',
        published_ms=0, valid_from_ms=0, valid_until_ms=7200000, sessions=[dict(open_ms=0, close_ms=7200000)]) | changes)


def request(contract=None, **changes):
    contract = contract or spec()
    return MappingRequest.model_validate(dict(server=contract.venue, account=1, symbol=contract.venue_symbol,
        revision='r1', source='synthetic mapping evidence', spec_hash=fingerprint(contract.model_dump(mode='json')),
        quantity_unit='broker_lot', currency_base='XAU', trade_calc_mode=0) | changes)


def metadata(**changes):
    return dict(provider='mt5', server='demo', account=1, symbol='XAUUSD.a', currency_base='XAU', currency_profit='USD',
                trade_calc_mode=0, trade_contract_size=100, trade_tick_size=.01, volume_min=.01, volume_max=10, volume_step=.01) | changes


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('app.quant.scanner.time.time', lambda: 1250)
    return Scanner(tmp_path / 'scanner.sqlite3')


def register(store, contract=None, **changes):
    contract = contract or spec()
    return store.mappings.register(request(contract, **changes), contract, 'admin')[0]


def test_mapping_is_immutable_idempotent_and_survives_reopen(store):
    first = register(store)
    duplicate, created = store.mappings.register(request(), spec(), 'admin')
    assert duplicate == first and not created
    with pytest.raises(ValueError, match='new revision'):
        register(store, source='changed assertion')
    second = register(store, revision='r2', source='new assertion')
    assert first['id'] != second['id']
    reopened = Scanner(store.path)
    assert reopened.mappings.get(first['id']) == first
    assert len(reopened.mappings.list()) == 2
    assert len(json.loads(''.join(reopened.export()))['mappings']) == 2


@pytest.mark.parametrize('field,value', [('server', 'other'), ('symbol', 'XAUUSD'), ('spec_hash', '0'*64)])
def test_registration_rejects_catalog_identity_mismatch(store, field, value):
    with pytest.raises(ValueError):
        store.mappings.register(request(**{field: value}), spec(), 'admin')
    assert store.mappings.list() == []


def test_spot_spec_cannot_be_silently_interpreted_as_broker_lots(store):
    with pytest.raises(ValueError, match='broker-lot'):
        register(store, spec(product='spot', contract_size='1'))


@pytest.mark.parametrize('field,value', [
    ('provider', 'other'), ('server', 'other'), ('account', 2), ('symbol', 'XAUUSD'),
    ('currency_base', None), ('currency_profit', 'EUR'), ('trade_calc_mode', 1),
    ('trade_contract_size', 1), ('trade_tick_size', .1), ('volume_min', None),
    ('volume_max', 100), ('volume_step', .1), ('trade_tick_size', float('nan')),
])
def test_live_contract_mismatch_is_not_an_alias(store, field, value):
    record = register(store)
    with pytest.raises(ValueError, match=field):
        check_mapping(record, metadata(**{field: value}), 1250)


@pytest.mark.parametrize('now', [1249, 7200])
def test_unavailable_mapping_or_expired_spec_rejected(store, now):
    with pytest.raises(ValueError):
        check_mapping(register(store), metadata(), now)


def test_future_source_publication_rejected(store):
    record = register(store, spec(published_ms=1250001))
    with pytest.raises(ValueError, match='unavailable'):
        check_mapping(record, metadata(), 1250)


def test_corrupt_pinned_spec_rejected(store):
    record = register(store)
    record['spec']['contract_size'] = '1'
    with store.db() as db:
        db.execute('UPDATE instrument_mappings SET payload=? WHERE id=?', (json.dumps(record), record['id']))
    with pytest.raises(ValueError, match='hash'):
        store.mappings.get(record['id'])


def test_matching_terms_across_accounts_do_not_claim_verified_equivalence(store):
    a = register(store)
    b = register(store, spec(venue='other', venue_symbol='GOLD.b'), account=2)
    result = compare_mappings(a, b)
    assert result['status'] == 'matching_supplied_terms'
    assert result['differences'] == {}
    assert result['equivalence_verified'] is False
    assert result['execution_enabled'] is False


@pytest.mark.parametrize('change', [{'contract_size': '1'}, {'tick_size': '0.1'}, {'quote_currency': 'EUR'}, {'instrument_id': 'OTHER'}])
def test_similar_names_or_shared_instrument_id_do_not_hide_contract_differences(store, change):
    a = register(store)
    b = register(store, spec(venue='other', venue_symbol='GOLD.b', **change))
    result = compare_mappings(a, b)
    assert result['status'] == 'incompatible_supplied_terms'
    assert next(iter(change)) in result['differences']


def test_scanner_pins_mapping_and_contract_drift_unresolves_exposure(store):
    record = register(store)
    cfg = ScanConfig(assets=[dict(symbol='XAUUSD.a', mapping_id=record['id'])])
    store.loader = lambda *args: dict(scope='demo:1', bars=[], instrument=metadata())
    store.evaluator = lambda *args: dict(bar=900, direction='buy', atr=1, spread=.1, eligible=True, reasons=['test'])
    store.cycle('run', cfg, None, 'demo:1')
    p = store.ledger()['trades'][0]
    assert p['catalog_mapping'] == record
    assert p['policy']['mapping_id'] == record['id']
    store.loader = lambda *args: dict(scope='demo:1', instrument=metadata(trade_contract_size=1),
                                    bars=[dict(timestamp=1500, open=100, high=105, low=95, close=100)])
    store.cycle('run', cfg, None, 'demo:1')
    assert store.ledger()['trades'][0]['state'] == 'unresolved'
    assert store.ledger()['trades'][0]['r_multiple'] is None
    assert 'trade_contract_size' in store.ledger()['trades'][0]['exit_reason']
    assert store.status()['latest'][0]['mapping_id'] == record['id']


def test_start_checks_mapping_before_spawning_or_submitting_orders(store):
    record = register(store)
    cfg = ScanConfig(assets=[dict(symbol='XAUUSD.a', mapping_id=record['id'])])
    runner = NS(lock=threading.RLock(), _require_connection=Mock(return_value=(NS(server='demo', login=2), None, None)),
                _symbol_info=Mock(return_value=NS(**metadata())), mt5=Mock())
    with pytest.raises(ValueError, match='account'):
        store.start(cfg, runner, 'operator')
    assert store.worker is None
    runner.mt5.order_send.assert_not_called()


@pytest.mark.asyncio
async def test_api_uses_real_catalog_and_enforces_roles(store, tmp_path, monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///' + (tmp_path / 'catalog.sqlite3').as_posix())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def db():
        async with sessions() as session:
            yield session
    async with sessions() as session:
        await register_spec(session, spec(), 'admin')
    app = FastAPI()
    app.middleware('http')(protect_api)
    app.include_router(router, prefix='/api/scanner')
    app.dependency_overrides[get_db] = db
    app.state.scanner = store
    for role in ('admin', 'operator', 'viewer'):
        monkeypatch.setattr(settings, f'API_{role.upper()}_KEY_HASH', hashlib.sha256((role+'x'*32).encode()).hexdigest())
    def auth(role):
        return {'Authorization': 'Bearer '+role+'x'*32}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1)), base_url='http://localhost') as client:
            for role in ('operator', 'viewer'):
                assert (await client.post('/api/scanner/mappings', json=request().model_dump(), headers=auth(role))).status_code == 403
            missing = await client.post('/api/scanner/mappings', json=request(spec_hash='0'*64).model_dump(), headers=auth('admin'))
            assert missing.status_code == 404
            result = await client.post('/api/scanner/mappings', json=request().model_dump(), headers=auth('admin'))
            assert result.status_code == 201
            key = result.json()['id']
            assert (await client.post('/api/scanner/mappings', json=request().model_dump(), headers=auth('admin'))).status_code == 200
            assert (await client.post('/api/scanner/mappings', json=request(source='changed').model_dump(), headers=auth('admin'))).status_code == 409
            assert (await client.get('/api/scanner/mappings', headers=auth('viewer'))).json()['mappings'][0]['id'] == key
            assert (await client.get(f'/api/scanner/mappings/{key}', headers=auth('viewer'))).status_code == 200
            compared = await client.get(f'/api/scanner/mappings/compare?left={key}&right={key}', headers=auth('viewer'))
            assert compared.json()['status'] == 'matching_supplied_terms'
            assert (await client.get('/api/scanner/mappings/unknown', headers=auth('viewer'))).status_code == 404
            assert (await client.get('/api/scanner/mappings')).status_code == 401
            assert (await client.get('/api/scanner/mappings', headers=auth('viewer') | {'Origin': 'https://untrusted.example'})).status_code == 403
    finally:
        await engine.dispose()
