"""Read projection of independent paper ledgers; no combined return metric."""
import base64
import asyncio
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.database.models import PaperTrade
from app.api.routes.paper_trades import serialize


def encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode_cursor(token, source):
    if not token:
        return None
    try:
        value = json.loads(base64.b64decode(token, altchars=b'-_', validate=True))
        if not isinstance(value, dict) or value.get('source') != source:
            raise ValueError()
        if source == 'manual':
            if set(value) != {'source', 'before_time', 'before_id'}:
                raise ValueError()
            stamp = datetime.fromisoformat(value['before_time'])
            if stamp.tzinfo is not None or not isinstance(value['before_id'], str) or not 1 <= len(value['before_id']) <= 64:
                raise ValueError()
        else:
            if set(value) != {'source', 'before', 'through'} or any(type(value[k]) is not int or value[k] < 0 for k in ('before', 'through')):
                raise ValueError()
        return value
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, 'Invalid paper evidence cursor for selected source') from None


def project(source, native):
    manual = source == 'manual'
    recorded_at = None
    if manual and native.get('created_at'):
        stamp = datetime.fromisoformat(native['created_at'])
        recorded_at = stamp.replace(tzinfo=timezone.utc).isoformat() if stamp.tzinfo is None else stamp.isoformat()
    elif not manual and native.get('observed') is not None:
        recorded_at = datetime.fromtimestamp(native['observed'], timezone.utc).isoformat()
    return {
        'id': f'{source}:{native["id"]}', 'source': source, 'source_id': native['id'],
        'symbol': native.get('symbol'), 'timeframe': native.get('timeframe'), 'direction': native.get('direction'),
        'state': native.get('status' if manual else 'state'),
        'recorded_at': recorded_at,
        'entry': native.get('entry_price' if manual else 'entry'),
        'stop': native.get('stop_loss' if manual else 'stop'),
        'target': native.get('take_profit' if manual else 'target'),
        'exit': native.get('exit_price' if manual else 'exit'),
        'outcome': {'value': native.get('pnl' if manual else 'r_multiple'),
                    'unit': 'price_times_quantity_currency_unspecified' if manual else 'R'},
        'account_scope': None if manual else native.get('scope'),
        'policy_id': None if manual else native.get('policy_id'),
        'approval_status': native.get('approval_status') if manual else None,
        'native': native,
    }


async def evidence_page(source, limit, cursor, db, store):
    position = decode_cursor(cursor, source)
    next_cursor = None
    if source == 'scanner':
        page = await asyncio.to_thread(store.records, 'trades', limit,
                                       position['before'] if position else None, position['through'] if position else None)
        records = page['items']
        if page['next_before'] is not None:
            next_cursor = encode_cursor({'source': source, 'before': page['next_before'], 'through': page['through']})
    else:
        query = select(PaperTrade).order_by(PaperTrade.created_at.desc(), PaperTrade.id.desc()).limit(limit + 1)
        if position:
            stamp = datetime.fromisoformat(position['before_time'])
            query = query.where(or_(PaperTrade.created_at < stamp,
                                   and_(PaperTrade.created_at == stamp, PaperTrade.id < position['before_id'])))
        rows = (await db.execute(query)).scalars().all()
        records = [serialize(row) for row in rows[:limit]]
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor({'source': source, 'before_time': last.created_at.isoformat(), 'before_id': last.id})
    return {'source': source, 'items': [project(source, row) for row in records], 'next_cursor': next_cursor,
            'execution_enabled': False,
            'note': 'Read-only source projection. Outcomes retain native units; no pooled performance. Records can change state during browsing. Sources are not a joint snapshot.'}
