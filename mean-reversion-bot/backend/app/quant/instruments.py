"""Broker-derived instrument classification and specification identity."""
import hashlib
import json
import math

TIMEFRAME_SECONDS = {
    'M1': 60, 'M2': 120, 'M3': 180, 'M4': 240, 'M5': 300, 'M6': 360,
    'M10': 600, 'M12': 720, 'M15': 900, 'M20': 1200, 'M30': 1800,
    'H1': 3600, 'H2': 7200, 'H3': 10800, 'H4': 14400, 'H6': 21600,
    'H8': 28800, 'H12': 43200, 'D1': 86400, 'W1': 604800,
}


def timeframe_seconds(timeframe):
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f'Unsupported MT5 timeframe: {timeframe}') from exc


_SPEC_FIELDS = (
    'trade_calc_mode', 'trade_contract_size', 'trade_tick_size',
    'trade_tick_value', 'point', 'digits', 'volume_min', 'volume_max',
    'volume_step', 'currency_base', 'currency_profit', 'currency_margin',
    'trade_mode', 'order_mode', 'trade_exemode', 'trade_stops_level',
    'trade_freeze_level', 'path', 'swap_mode', 'swap_long', 'swap_short',
    'swap_rollover3days', 'trade_tick_value_profit', 'trade_tick_value_loss',
)


def _value(info, name):
    value = getattr(info, name, None)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def specification_payload(info):
    return {name: _value(info, name) for name in _SPEC_FIELDS}


def specification_fingerprint(info):
    return configuration_fingerprint(specification_payload(info))


def configuration_fingerprint(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def specification_issues(info):
    issues = []
    for name in ('trade_contract_size', 'trade_tick_size', 'trade_tick_value',
                 'point', 'volume_min', 'volume_max', 'volume_step'):
        value = _value(info, name)
        if not isinstance(value, (int, float)) or value <= 0:
            issues.append(f'Missing or invalid broker field: {name}')
    if not isinstance(_value(info, 'digits'), int) or not 0 <= info.digits <= 12:
        issues.append('Missing or invalid broker field: digits')
    if not isinstance(_value(info, 'trade_calc_mode'), int):
        issues.append('Missing broker calculation mode')
    if not getattr(info, 'currency_profit', None):
        issues.append('Missing broker profit currency')
    if getattr(info, 'volume_max', 0) < getattr(info, 'volume_min', 0):
        issues.append('Invalid broker volume bounds')
    if not getattr(info, 'trade_mode', 0) in (1, 2, 4):
        issues.append('Broker does not permit new positions')
    if getattr(info, 'order_mode', 0) & 49 != 49:
        issues.append('Broker does not support market orders with stop loss and take profit')
    return issues


def classify_instrument(info, _mt5=None):
    """Classify only from broker metadata; never infer a class from the symbol name."""
    path = (getattr(info, 'path', '') or '').replace('/', '\\').lower()
    if any(token in path for token in ('metal', 'bullion')):
        return 'metal'
    if any(token in path for token in ('synthetic', 'derived', 'volatility index',
                                       'volatility indices', 'boom', 'crash')):
        return 'synthetic'
    if any(token in path for token in ('commodity', 'commodities', 'energy', 'agriculture')):
        return 'commodity'
    if any(token in path for token in ('index', 'indices', 'cash index')):
        return 'index'
    if any(token in path for token in ('future', 'futures')):
        return 'future'
    if any(token in path for token in ('stock', 'equity', 'equities', 'shares')):
        return 'equity'
    if 'forex' in path:
        return 'forex'
    return 'unknown'
