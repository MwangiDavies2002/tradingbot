"""Retained MT5 bar-spread proxies, not historical executable ask quotes."""
from decimal import Decimal, InvalidOperation
import math


SOURCE = 'mt5_copy_rates_spread_points_v1'


def capture_spread(rate, instrument, timeframe):
    try:
        points = float(rate['spread'])
    except (KeyError, IndexError, ValueError, TypeError):
        points = None
    if points is not None and not math.isfinite(points):
        points = None
    point = instrument.get('point')
    if not isinstance(point, (int, float)) or isinstance(point, bool) or not math.isfinite(point) or point <= 0:
        point = None
    price = str(Decimal(str(points)) * Decimal(str(point))) if points is not None and points > 0 and points.is_integer() and point else None
    return dict(source=SOURCE, scope=f'{instrument["server"]}:{instrument["account"]}', symbol=instrument['symbol'],
                timeframe=timeframe, timestamp=int(rate['time']), captured_at=instrument['captured_at'],
                price_basis=instrument['price_basis'], spread_points=points, point=point, spread_price=price,
                status='available_proxy' if price is not None and instrument['price_basis'] == 'bid' else 'unavailable_or_unconfirmed')


def candle_spread(evidence, trade, timestamp):
    if not evidence or evidence.get('source') != SOURCE or evidence.get('status') != 'available_proxy':
        raise ValueError('Historical candle spread missing or unconfirmed; no fixed-spread fallback')
    for field, expected in [('scope', trade['scope']), ('symbol', trade['symbol']), ('timeframe', trade['timeframe']),
                            ('timestamp', timestamp), ('price_basis', 'bid')]:
        if evidence.get(field) != expected:
            raise ValueError(f'Historical spread provenance mismatch: {field}')
    try:
        points, point, price = (Decimal(str(evidence.get(k))) for k in ('spread_points', 'point', 'spread_price'))
        if not all(v.is_finite() and v > 0 for v in (points, point, price)) or points != points.to_integral_value() or points * point != price:
            raise ValueError()
        value = float(price)
        if not math.isfinite(value) or value <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError('Historical spread conversion is invalid or unconfirmed') from None
    return value
