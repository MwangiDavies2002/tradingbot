"""Read-only source adapters. No connect, configure, start or order calls."""
import asyncio
import time
from datetime import datetime, timezone

from app.data.historical_fetcher import fetch_public_candles
from app.quant.schemas import Bar


def mt5_snapshot(runner, asset, request, start, end):
    with runner.lock:
        account, _, _ = runner._require_connection()
        info = runner._symbol_info(asset.symbol)
        rates = runner.mt5.copy_rates_range(asset.symbol, getattr(runner.mt5, f'TIMEFRAME_{request.timeframe}'),
                datetime.fromtimestamp(start, timezone.utc), datetime.fromtimestamp(end-1, timezone.utc))
        if rates is None or len(rates) < 100:
            raise ValueError('At least 100 historical candles are required; load more MT5 chart history')
        if len(rates) > 10000:
            raise ValueError('Use a shorter lookback or larger timeframe (10,000 candles per asset maximum)')
        p = asset.profile.model_copy(deep=True)
        bars = [Bar(timestamp=int(r['time']), open=float(r['open']), high=float(r['high']),
                    low=float(r['low']), close=float(r['close']), volume=float(r['tick_volume']),
                    spread=float(r['spread']) * info.point) for r in rates if start <= int(r['time']) < end]
        p.contract_size, p.tick_size = info.trade_contract_size, info.trade_tick_size
        p.volume_min, p.volume_max, p.volume_step = info.volume_min, info.volume_max, info.volume_step
        p.profit_currency, p.account_currency = info.currency_profit, account.currency
        p.minimum_stop, p.trade_mode = info.trade_stops_level * info.point, info.trade_mode
        p.price_basis = 'bid'
        # Only documented linear profit formulas are supported; futures/options need distinct models.
        linear = info.trade_calc_mode in (0, 2, 3, 4, 5, 32)
        p.specification_confirmed = linear and p.contract_size > 0
        warnings = [] if linear else ['This broker calculation mode is not a supported linear contract']
        fx_source = None
        if p.profit_currency != p.account_currency and not p.fx_rates:
            catalog = runner.mt5.symbols_get()
            if catalog is None:
                raise ValueError('Cannot discover a historical FX conversion symbol')
            candidates = [(s, False) for s in catalog if s.currency_base == p.profit_currency and s.currency_profit == p.account_currency]
            candidates += [(s, True) for s in catalog if s.currency_base == p.account_currency and s.currency_profit == p.profit_currency]
            if candidates:
                fx, inverse = sorted(candidates, key=lambda pair: pair[0].name)[0]
                if not runner.mt5.symbol_select(fx.name, True):
                    raise ValueError('Cannot select historical FX conversion symbol')
                rows = runner.mt5.copy_rates_range(fx.name, getattr(runner.mt5, f'TIMEFRAME_{request.timeframe}'),
                    datetime.fromtimestamp(start-request.interval*2, timezone.utc), datetime.fromtimestamp(end-1, timezone.utc))
                if rows is not None:
                    # The close becomes available only after its candle has finished.
                    p.fx_rates = {int(r['time']) + request.interval: (1/float(r['close']) if inverse else float(r['close']))
                                  for r in rows if float(r['close']) > 0}
                    p.fx_max_age_seconds = request.interval * 2
                    fx_source = fx.name
            if not p.fx_rates:
                warnings.append('No historical conversion series available; costed validation will fail closed')
        positions = runner.mt5.positions_get()
        if positions is None:
            raise ValueError('Cannot read the position snapshot for exposure warnings')
        exposure = sum(p.volume * (1 if p.type == 0 else -1) for p in positions if p.symbol == asset.symbol)
        snapshot = {'account': account.login, 'server': account.server, 'currency': account.currency,
                    'symbol': asset.symbol, 'captured_at': time.time(), 'calculation_mode': info.trade_calc_mode,
                    'contract_size': p.contract_size, 'tick_size': p.tick_size, 'volume_min': p.volume_min,
                    'volume_max': p.volume_max, 'volume_step': p.volume_step,
                    'historical_fx_symbol': fx_source, 'spread_source': 'MT5 candle spread points',
                    'warnings': warnings}
        # Revalidate copied broker numbers before arithmetic.
        p = type(p).model_validate(p.model_dump())
        return bars, p, snapshot, exposure


def load_asset(asset, request, runner, start, end):
    if request.source == 'mt5':
        if runner is None:
            raise ValueError('Connect the MT5 demo terminal before analyzing its symbols')
        return mt5_snapshot(runner, asset, request, start, end)
    if request.source == 'import':
        return asset.bars, asset.profile, {'source': 'import'}, request.exposures.get(asset.symbol, 0)
    count = (end-start)//request.interval
    if count > 10000:
        raise ValueError('Use a shorter lookback or larger timeframe (10,000 candles per asset maximum)')
    raw = asyncio.run(fetch_public_candles(asset.symbol, request.interval, max(100, count)))
    bars = [Bar(timestamp=int(r['epoch']), open=float(r['open']), high=float(r['high']), low=float(r['low']),
                close=float(r['close']), volume=float(r.get('volume', 0))) for r in raw if start <= int(r['epoch']) < end]
    return bars, asset.profile, {'source': 'Deriv public candles; instrument contract supplied by user'}, request.exposures.get(asset.symbol, 0)
