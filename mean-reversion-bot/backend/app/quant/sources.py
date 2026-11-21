"""Read-only source adapters. No connect, configure, start or order calls."""
import asyncio
import time
from datetime import datetime, timezone

from app.data.historical_fetcher import fetch_public_candles
from app.quant.schemas import Bar
from app.quant.instruments import classify_instrument, specification_fingerprint, specification_issues


def mt5_snapshot(runner, asset, request):
    with runner.lock:
        account, _, _ = runner._require_connection()
        info = runner._market_info(asset.symbol)
        timeframe = asset.timeframe or request.timeframe
        mt5_timeframe = getattr(runner.mt5, f'TIMEFRAME_{timeframe}')
        current_bar = runner.mt5.copy_rates_from_pos(asset.symbol, mt5_timeframe, 0, 1)
        if current_bar is None or len(current_bar) != 1:
            raise ValueError(f'{asset.symbol} {timeframe}: cannot determine the current broker candle boundary')
        history_end = int(current_bar[0]['time'])
        history_start = history_end - request.days * 86400
        rates = runner.mt5.copy_rates_range(
            asset.symbol, mt5_timeframe,
            datetime.fromtimestamp(history_start, timezone.utc),
            datetime.fromtimestamp(history_end-1, timezone.utc))
        if rates is None or len(rates) < 100:
            raise ValueError('At least 100 historical candles are required; load more MT5 chart history')
        if len(rates) > 10000:
            raise ValueError('Use a shorter lookback or larger timeframe (10,000 candles per asset maximum)')
        p = asset.profile.model_copy(deep=True)
        bars = [Bar(timestamp=int(r['time']), open=float(r['open']), high=float(r['high']),
                    low=float(r['low']), close=float(r['close']), volume=float(r['tick_volume']),
                    spread=float(r['spread']) * info.point) for r in rates
                if history_start <= int(r['time']) < history_end]
        p.contract_size, p.tick_size = info.trade_contract_size, info.trade_tick_size
        p.volume_min, p.volume_max, p.volume_step = info.volume_min, info.volume_max, info.volume_step
        p.point, p.digits = info.point, info.digits
        p.tick_value = getattr(info, 'trade_tick_value', None)
        p.calculation_mode = info.trade_calc_mode
        p.order_mode = info.order_mode
        p.profit_currency, p.account_currency = info.currency_profit, account.currency
        p.minimum_stop, p.trade_mode = info.trade_stops_level * info.point, info.trade_mode
        p.specification_source = f'MT5 symbol_info ({account.server})'
        p.asset_class = classify_instrument(info, runner.mt5)
        p.broker_group = getattr(info, 'path', '') or ''
        p.specification_fingerprint = specification_fingerprint(info)
        p.price_basis = 'bid'
        rollover_day = getattr(info, 'swap_rollover3days', None)
        if isinstance(rollover_day, int) and 0 <= rollover_day <= 6:
            rollover_weights = list(p.rollover_weights)
            rollover_weights[(rollover_day - 1) % 7] = 3.
            p.rollover_weights = rollover_weights
        # Only broker modes whose linear P&L can be calculated are eligible.
        linear_modes = {0, 1, 2, 3, 4, 5, 32}
        linear = info.trade_calc_mode in linear_modes
        issues = specification_issues(info)
        p.specification_confirmed = linear and not issues
        warnings = list(issues)
        if not linear:
            warnings.append('This broker calculation mode is not a supported linear contract')
        if not p.session.confirmed:
            warnings.append('Instrument trading sessions and holidays are unverified')
        if not p.costs_confirmed:
            warnings.append('Instrument commission and financing costs are unverified')
        if not p.slippage_confirmed:
            warnings.append('Instrument slippage scenario is unverified')
        swap_mode = getattr(info, 'swap_mode', None)
        swap_mode_name = next((name for name in dir(runner.mt5)
                               if name.startswith('SYMBOL_SWAP_MODE_')
                               and getattr(runner.mt5, name, None) == swap_mode), None)
        cash_swap_mode = getattr(runner.mt5, 'SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT', None)
        if swap_mode is None or cash_swap_mode is None or swap_mode != cash_swap_mode:
            warnings.append('Broker swap mode is not account-currency cash; the fixed per-lot financing model cannot price it')
        if not p.rollover_confirmed:
            warnings.append('Instrument rollover time and weights are unverified')
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
                rows = runner.mt5.copy_rates_range(fx.name, getattr(runner.mt5, f'TIMEFRAME_{timeframe}'),
                    datetime.fromtimestamp(history_start-request.interval*2, timezone.utc),
                    datetime.fromtimestamp(history_end-1, timezone.utc))
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
                    'symbol': asset.symbol, 'captured_at': time.time(),
                    'history_start': history_start, 'history_end': history_end,
                    'calculation_mode': info.trade_calc_mode,
                    'asset_class': p.asset_class, 'broker_group': p.broker_group,
                    'specification_fingerprint': p.specification_fingerprint,
                    'specification_issues': issues,
                    'contract_size': p.contract_size, 'tick_size': p.tick_size, 'volume_min': p.volume_min,
                    'volume_max': p.volume_max, 'volume_step': p.volume_step,
                    'point': info.point, 'digits': info.digits,
                    'tick_value': getattr(info, 'trade_tick_value', None),
                    'swap_mode': getattr(info, 'swap_mode', None),
                    'swap_mode_name': swap_mode_name,
                    'swap_long': getattr(info, 'swap_long', None),
                    'swap_short': getattr(info, 'swap_short', None),
                    'swap_rollover3days': getattr(info, 'swap_rollover3days', None),
                    'spread_points_at_snapshot': info.spread,
                    'spread_price_at_snapshot': info.spread * info.point,
                    'commission_source': 'MT5 symbol_info does not expose a commission schedule',
                    'slippage_source': 'Slippage is not a fixed symbol specification; use a measured or explicit scenario',
                    'historical_fx_symbol': fx_source, 'spread_source': 'MT5 candle spread points',
                    'warnings': warnings}
        # Revalidate copied broker numbers before arithmetic.
        p = type(p).model_validate(p.model_dump())
        return bars, p, snapshot, exposure


def load_asset(asset, request, runner, start, end):
    if request.source == 'mt5':
        if runner is None:
            raise ValueError('Connect the MT5 demo terminal before analyzing its symbols')
        return mt5_snapshot(runner, asset, request)
    if request.source == 'import':
        return asset.bars, asset.profile, {'source': 'import'}, request.exposures.get(asset.symbol, 0)
    count = (end-start)//request.interval
    if count > 10000:
        raise ValueError('Use a shorter lookback or larger timeframe (10,000 candles per asset maximum)')
    raw = asyncio.run(fetch_public_candles(asset.symbol, request.interval, max(100, count)))
    bars = [Bar(timestamp=int(r['epoch']), open=float(r['open']), high=float(r['high']), low=float(r['low']),
                close=float(r['close']), volume=float(r.get('volume', 0))) for r in raw if start <= int(r['epoch']) < end]
    return bars, asset.profile, {'source': 'Deriv public candles; instrument contract supplied by user'}, request.exposures.get(asset.symbol, 0)
