import hashlib
import json
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.routes.scanner import router
from app.api.security import protect_api
from app.config import settings
from app.database.models import Base, PaperTrade
from app.database.session import get_db
from app.quant.paper_evidence import evidence_page, decode_cursor, encode_cursor
from app.quant.scanner import Scanner


def manual(key, stamp):
    return PaperTrade(id=key, symbol='TEST', timeframe='M5', direction='buy', entry_price=100,
                      stop_loss=99, take_profit=102, quantity=2, status='closed', pnl=4,
                      created_by_role='operator', created_at=stamp)


@pytest_asyncio.fixture
async def ledgers(tmp_path):
    engine = create_async_engine('sqlite+aiosqlite:///' + (tmp_path/'manual.db').as_posix())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = Scanner(tmp_path/'scanner.db')
    async with sessions() as db:
        stamp = datetime(2026, 1, 1)
        db.add_all([manual(f'{i:04}', stamp) for i in range(505)])
        await db.commit()
        with store.db() as conn:
            for i in range(505):
                record = dict(id=f'{i:04}', symbol='TEST', timeframe='M5', observed=100+i, direction='buy',
                              scope='demo:1', policy_id='policy', r_multiple=None if i == 504 else 1.5)
                conn.execute('INSERT INTO paper VALUES(?,?,?,?,?)',
                             (record['id'], 'run', 'TEST', 'unresolved' if i == 504 else 'closed', json.dumps(record)))
        yield db, store, sessions
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['manual', 'scanner'])
async def test_pages_exceed_500_preserve_units_state_and_source(ledgers, source):
    db, store, _ = ledgers
    seen = []
    page = await evidence_page(source, 200, None, db, store)
    first = page['items'][0]
    assert first['id'] == f'{source}:0504'
    if source == 'manual':
        assert first['outcome'] == {'value': 4, 'unit': 'price_times_quantity_currency_unspecified'}
        assert first['account_scope'] is None
        assert first['native']['created_at'] == '2026-01-01T00:00:00'
        assert first['recorded_at'].endswith('+00:00')
    else:
        assert first['state'] == first['native']['state'] == 'unresolved'
        assert first['outcome'] == {'value': None, 'unit': 'R'}
    # Newly created records must not shift the continuation to older records.
    db.add(manual('newer', datetime(2026, 1, 2)))
    await db.commit()
    with store.db() as conn:
        conn.execute('INSERT INTO paper VALUES(?,?,?,?,?)', ('newer', 'run', 'TEST', 'pending', json.dumps({'id':'newer'})))
    while True:
        seen.extend(row['source_id'] for row in page['items'])
        if not page['next_cursor']:
            break
        page = await evidence_page(source, 200, page['next_cursor'], db, store)
    assert len(seen) == len(set(seen)) == 505
    assert 'newer' not in seen


@pytest.mark.parametrize('token,source', [
    ('garbage', 'manual'), (encode_cursor([]), 'manual'),
    (encode_cursor({'source':'scanner','before':1,'through':1}), 'manual'),
    (encode_cursor({'source':'scanner','before':True,'through':1}), 'scanner'),
    (encode_cursor({'source':'scanner','before':-1,'through':1}), 'scanner'),
    (encode_cursor({'source':'manual','before_time':'wrong','before_id':'a'}), 'manual'),
    (encode_cursor({'source':'manual','before_time':'2026-01-01T00:00:00+00:00','before_id':'a'}), 'manual'),
])
def test_invalid_cursor_rejected(token, source):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(token, source)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_api_is_viewer_readable_local_and_has_no_mutation(ledgers, monkeypatch):
    db, store, sessions = ledgers
    async def session():
        async with sessions() as value:
            yield value
    monkeypatch.setattr(settings, 'API_VIEWER_KEY_HASH', hashlib.sha256(b'v'*32).hexdigest())
    app = FastAPI()
    app.middleware('http')(protect_api)
    app.include_router(router, prefix='/api/scanner')
    app.dependency_overrides[get_db] = session
    app.state.scanner = store
    headers = {'Authorization':'Bearer '+'v'*32}
    before = ''.join(store.export())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1',1)), base_url='http://localhost') as client:
        assert (await client.get('/api/scanner/paper-evidence')).status_code == 401
        for source in ('manual','scanner'):
            response = await client.get('/api/scanner/paper-evidence', params={'source':source,'limit':2}, headers=headers)
            assert response.status_code == 200
            assert len(response.json()['items']) == 2
            assert response.json()['execution_enabled'] is False
        for query in ('source=all','limit=201','cursor=invalid'):
            assert (await client.get('/api/scanner/paper-evidence?'+query, headers=headers)).status_code == 422
        assert (await client.post('/api/scanner/paper-evidence', json={}, headers=headers)).status_code == 403
        assert (await client.get('/api/scanner/paper-evidence', headers=headers | {'Origin':'https://outside.example'})).status_code == 403
    after = ''.join(store.export())
    assert json.loads(before)['trades'] == json.loads(after)['trades']
    assert (await db.get(PaperTrade,'0504')).pnl == 4
