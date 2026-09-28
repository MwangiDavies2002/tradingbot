"""Pinned catalog aliases for MT5 broker-lot contracts, never automatic aliases."""
from decimal import Decimal, InvalidOperation
import json
import time
from typing import Literal

from pydantic import Field, model_validator

from app.institutional.data import fingerprint
from app.institutional.instruments import InstrumentSpec
from app.quant.schemas import Record


class MappingRequest(Record):
    provider: Literal['mt5'] = 'mt5'
    server: str = Field(min_length=1, max_length=128)
    account: int = Field(gt=0, le=9223372036854775807, strict=True)
    symbol: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=500)
    spec_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    quantity_unit: Literal['broker_lot']
    currency_base: str = Field(min_length=1, max_length=32)
    trade_calc_mode: int = Field(ge=0, strict=True)

    @model_validator(mode='after')
    def exact(self):
        for value in (self.server, self.symbol, self.revision, self.source, self.currency_base):
            if not value.strip() or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError('Mapping identity and provenance must be exact nonblank text')
        return self


def mapping_content(body, spec):
    if fingerprint(spec.model_dump(mode='json')) != body.spec_hash:
        raise ValueError('Catalog specification hash does not match mapping')
    if spec.venue != body.server or spec.venue_symbol != body.symbol:
        raise ValueError('Catalog venue/symbol must match the exact broker server/symbol')
    if spec.product != 'linear_contract':
        raise ValueError('MT5 scanner mappings require a linear-contract spec in broker-lot units')
    return {'mapping': body.model_dump(), 'spec': spec.model_dump(mode='json')}


def validate_mapping_record(record):
    content = mapping_content(MappingRequest.model_validate(record['mapping']), InstrumentSpec.model_validate(record['spec']))
    if fingerprint(content) != record['id']:
        raise ValueError('Stored instrument mapping failed its integrity check')
    return content


def check_mapping(record, instrument, now):
    validate_mapping_record(record)
    body, spec = record['mapping'], record['spec']
    for field in ('provider', 'server', 'account', 'symbol', 'currency_base', 'trade_calc_mode'):
        if instrument.get(field) != body[field]:
            raise ValueError(f'Mapped broker metadata mismatch or unavailable: {field}')
    if now < record['registered_at']:
        raise ValueError('Instrument mapping was not registered at observation time')
    if spec['published_ms'] > now * 1000 or not spec['valid_from_ms'] <= now * 1000 < spec['valid_until_ms']:
        raise ValueError('Mapped catalog specification is unavailable or expired')
    if instrument.get('currency_profit') != spec['quote_currency']:
        raise ValueError('Mapped broker metadata mismatch or unavailable: currency_profit')
    for broker, catalog in [('trade_contract_size', 'contract_size'), ('trade_tick_size', 'tick_size'),
                            ('volume_min', 'min_quantity'), ('volume_max', 'max_quantity'), ('volume_step', 'quantity_step')]:
        try:
            value = Decimal(str(instrument.get(broker)))
        except InvalidOperation:
            raise ValueError(f'Mapped broker metadata mismatch or unavailable: {broker}') from None
        if not value.is_finite() or value != Decimal(spec[catalog]):
            raise ValueError(f'Mapped broker metadata mismatch or unavailable: {broker}')


def compare_mappings(left, right):
    validate_mapping_record(left)
    validate_mapping_record(right)
    fields = ('instrument_id', 'product', 'underlying_unit', 'quote_currency', 'contract_size',
              'tick_size', 'quantity_step', 'min_quantity', 'max_quantity', 'min_notional')
    decimals = {'contract_size', 'tick_size', 'quantity_step', 'min_quantity', 'max_quantity', 'min_notional'}
    differences = {}
    for field in fields:
        a, b = left['spec'][field], right['spec'][field]
        differs = Decimal(a) != Decimal(b) if field in decimals else a != b
        if differs:
            differences[field] = {'left': a, 'right': b}
    for field in ('quantity_unit', 'currency_base', 'trade_calc_mode'):
        a, b = left['mapping'][field], right['mapping'][field]
        if a != b:
            differences[field] = {'left': a, 'right': b}
    return {'left': left['id'], 'right': right['id'], 'differences': differences,
            'status': 'incompatible_supplied_terms' if differences else 'matching_supplied_terms',
            'equivalence_verified': False, 'execution_enabled': False,
            'note': 'Comparison of supplied contract terms only. Sessions, fees, financing, settlement, liquidity and legal rights are not proven equivalent. No data is merged or provider switched.'}


class MappingCatalog:
    def __init__(self, db):
        self.db = db

    def register(self, body, spec, role):
        if role != 'admin':
            raise ValueError('Only admin can register scanner mappings')
        content = mapping_content(body, spec)
        key = fingerprint(content)
        record = content | {'id': key, 'registered_at': time.time(), 'registered_by_role': role}
        with self.db() as db:
            inserted = db.execute('INSERT OR IGNORE INTO instrument_mappings VALUES(?,?,?,?,?,?,?)',
                                  (key, body.server, body.account, body.symbol, body.revision,
                                   record['registered_at'], json.dumps(record, allow_nan=False))).rowcount
            row = db.execute('SELECT payload FROM instrument_mappings WHERE server=? AND account=? AND symbol=? AND revision=?',
                             (body.server, body.account, body.symbol, body.revision)).fetchone()
            existing = json.loads(row[0])
            validate_mapping_record(existing)
            if existing['id'] != key:
                raise ValueError('Mapping revision already exists with different content; publish a new revision')
        return existing, bool(inserted)

    def get(self, key):
        with self.db() as db:
            row = db.execute('SELECT payload FROM instrument_mappings WHERE id=?', (key,)).fetchone()
        if row is None:
            raise KeyError('Instrument mapping not found')
        record = json.loads(row[0])
        validate_mapping_record(record)
        if record['id'] != key:
            raise ValueError('Stored instrument mapping identity mismatch')
        return record

    def list(self, limit=50, offset=0):
        with self.db() as db:
            rows = db.execute('SELECT id FROM instrument_mappings ORDER BY registered_at DESC,id LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        return [self.get(row[0]) for row in rows]
