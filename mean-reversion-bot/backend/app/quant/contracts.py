"""One-position linear-contract simulator with account-currency cash accounting."""
from bisect import bisect_right
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo
import math
import time

from app.backtesting.backtest_engine import BacktestEngine, BacktestReport, BTTrade
from app.core.engine.signal_engine import SignalEngine
from app.core.lsl.lsl_detector import Candle
from app.core.risk.circuit_breaker import CircuitBreaker
from app.data.validation import validate_candles
from app.quant.research_sessions import effective_bounds, in_window, market_is_open


class ContractBacktest(BacktestEngine):
    def __init__(self, config, profile, initial_balance=10000, stress=1, research_scope=None, interval=300):
        super().__init__(SignalEngine(config), initial_balance=initial_balance, max_open=1)
        self.profile = profile
        self.stress = stress
        self.research_scope = research_scope or {'sessions': [], 'setup': 'strategy_signals'}
        self.interval = interval
        self.fx_times = sorted(profile.fx_rates)
        if any(v is None for v in (profile.commission_per_lot, profile.financing_long, profile.financing_short)):
            raise ValueError('Enter commission and both financing rates before costed validation')

    def conversion(self, timestamp):
        if self.profile.profit_currency == self.profile.account_currency:
            return 1.
        i = bisect_right(self.fx_times, timestamp) - 1
        if i < 0 or timestamp - self.fx_times[i] > self.profile.fx_max_age_seconds:
            raise ValueError('Missing point-in-time FX conversion; current exchange rates cannot price historical P&L')
        return self.profile.fx_rates[self.fx_times[i]]

    def spread(self, bar):
        value = self.profile.spread_price if self.profile.spread_price is not None else bar.spread
        if value is None:
            raise ValueError('Missing historical spread; supply a confirmed spread scenario')
        return value * self.stress

    def quote(self, price, bar, buy, lots=0):
        spread = self.spread(bar)
        adjustment = (spread if buy else 0) if self.profile.price_basis == 'bid' else (spread / 2 if buy else -spread / 2)
        slippage = self.profile.slippage_ticks + self.profile.market_impact_ticks_per_lot * lots
        slip = slippage * self.profile.tick_size * self.stress * (1 if buy else -1)
        value = price + adjustment + slip
        if value <= 0:
            raise ValueError('Costs exceed the instrument price')
        return value

    def financing(self, trade, timestamp):
        p = self.profile
        zone = ZoneInfo(p.rollover_timezone)
        day = datetime.fromtimestamp(trade.entry_ts, zone).date()
        last = datetime.fromtimestamp(timestamp, zone).date()
        count = 0.
        while day <= last:
            dt = datetime(day.year, day.month, day.day, p.rollover_minute // 60, p.rollover_minute % 60, tzinfo=zone)
            if trade.entry_ts < dt.timestamp() <= timestamp:
                count += p.rollover_weights[day.weekday()]
            day += timedelta(days=1)
        charge = p.financing_long if trade.direction == 'buy' else p.financing_short
        # Positive values are costs, negative values are credits. Stress never amplifies credits.
        return trade.stake * count * charge * (self.stress if charge > 0 else 1)

    def cash_pnl(self, trade, price, timestamp):
        direction = 1 if trade.direction == 'buy' else -1
        gross = direction * (price - trade.entry_price) * trade.stake * self.profile.contract_size * self.conversion(timestamp)
        return gross - trade.stake * self.profile.commission_per_lot * self.stress - self.financing(trade, timestamp)

    def lots(self, budget, entry, stop, timestamp):
        p = self.profile
        conversion = self.conversion(timestamp)
        fixed_per_lot = (abs(entry - stop) * p.contract_size * conversion
                         + p.commission_per_lot * self.stress
                         + p.slippage_ticks * p.tick_size * p.contract_size * conversion * self.stress)
        impact_per_lot_squared = p.market_impact_ticks_per_lot * p.tick_size * p.contract_size * conversion * self.stress
        def risk(size):
            return fixed_per_lot * size + impact_per_lot_squared * size * size
        low, high = 0., p.volume_max
        for _ in range(60):
            middle = (low + high) / 2
            if risk(middle) <= budget:
                low = middle
            else:
                high = middle
        raw = low
        step = Decimal(str(self.profile.volume_step))
        size = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
        return size if size >= self.profile.volume_min else 0

    def run(self, bars, symbol='', timeframe=''):
        validate_candles(bars)
        if len(bars) <= self.warmup_bars + 1:
            raise ValueError('Insufficient candles after indicator warmup')
        self.engine = SignalEngine(self.engine.cfg)
        self.engine.initialise(self.initial_balance)
        now = datetime.fromtimestamp(bars[0].timestamp, timezone.utc)
        cb = CircuitBreaker(clock=lambda: now, max_open_positions=1,
                            max_consecutive_losses=self.engine.cfg.cb_max_losses,
                            daily_drawdown_pct=self.engine.cfg.cb_daily_dd,
                            weekly_drawdown_pct=self.engine.cfg.cb_weekly_dd)
        cb.initialise(self.initial_balance)
        self.engine.cb = cb
        candles = [Candle(timestamp=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume) for b in bars]
        balance, trades, position = self.initial_balance, [], None
        timestamp_index = {bar.timestamp: index for index, bar in enumerate(bars)}
        orb_used = set()
        orb_volume_stats = {'breakout_closes': 0, 'volume_confirmed': 0, 'volume_rejected': 0, 'volume_unavailable': 0}
        ambiguous_exit_bars = 0
        equity = [{'ts': bars[self.warmup_bars-1].timestamp, 'balance': balance, 'equity': balance}]
        started = time.perf_counter()
        for i in range(self.warmup_bars, len(bars)):
            b = bars[i]
            now = datetime.fromtimestamp(b.timestamp, timezone.utc)
            if position:
                buy = position.direction == 'buy'
                # SL/TP triggers on the executable quote side. Gaps execute at the worse open.
                spread = self.spread(b)
                shift = (0 if buy else spread) if self.profile.price_basis == 'bid' else (-spread/2 if buy else spread/2)
                lo, hi, op = b.low+shift, b.high+shift, b.open+shift
                stop = lo <= position.stop_loss if buy else hi >= position.stop_loss
                target = hi >= position.take_profit if buy else lo <= position.take_profit
                if stop and target:
                    ambiguous_exit_bars += 1
                if stop or target or i == len(bars)-1:
                    if stop:
                        price = min(op, position.stop_loss) if buy else max(op, position.stop_loss)
                        reason = 'stop_loss'
                    elif target:
                        price, reason = position.take_profit, 'take_profit'
                    else:
                        price, reason = b.close+shift, 'end_of_data'
                    slippage_ticks = self.profile.slippage_ticks + self.profile.market_impact_ticks_per_lot * position.stake
                    price += slippage_ticks * self.profile.tick_size * self.stress * (-1 if buy else 1)
                    pnl = self.cash_pnl(position, price, b.timestamp)
                    position.exit_bar, position.exit_ts, position.exit_price = i, b.timestamp, price
                    position.pnl, position.close_reason = pnl, reason
                    balance += pnl
                    cb.record_trade(pnl=pnl, account_balance=balance)
                    cb.record_trade_close()
                    position = None
            marked = balance + (self.cash_pnl(position, self.quote(b.close, b, position.direction != 'buy', position.stake), b.timestamp) if position else 0)
            equity.append({'ts': b.timestamp, 'balance': balance, 'equity': marked})
            cb.mark_equity(marked)
            self.engine.sizer.update_balance(max(0, marked))
            if position or i == len(bars)-1 or marked <= 0 or not cb.is_trading_allowed():
                continue
            if not market_is_open(b.timestamp, self.profile.session):
                continue
            d = self.engine.evaluate(candles[max(0, i-499):i+1], symbol=symbol, timeframe=timeframe)
            setup = self.research_scope.get('setup', 'strategy_signals')
            direction = d.direction if setup != 'opening_range_breakout' and d.should_trade else None
            orb_range = None
            orb_session = self.research_scope.get('opening_range_session', 'new_york')
            if setup == 'opening_range_breakout':
                start_ts, session_end = effective_bounds(b.timestamp, orb_session, self.profile.session)
                duration = self.research_scope.get('opening_range_minutes', 15) * 60
                range_end = start_ts + duration
                key = (orb_session, start_ts)
                range_times = range(start_ts, range_end, self.interval)
                indices = [timestamp_index.get(ts) for ts in range_times]
                # Use only a complete, contiguous opening range made of bars already closed.
                if (key not in orb_used and b.timestamp >= range_end and b.timestamp < session_end
                        and all(index is not None and index < i and market_is_open(bars[index].timestamp, self.profile.session) for index in indices)):
                    opening_bars = [bars[index] for index in indices]
                    high = max(item.high for item in opening_bars)
                    low = min(item.low for item in opening_bars)
                    previous = bars[i-1]
                    if previous.timestamp == b.timestamp - self.interval:
                        if previous.close <= high < b.close:
                            direction, orb_range = 'buy', (high, low)
                        elif previous.close >= low > b.close:
                            direction, orb_range = 'sell', (high, low)
                        if (direction and self.research_scope.get('opening_range_indicator_confirmation')
                                and (not d.should_trade or d.direction != direction)):
                            direction, orb_range = None, None
                        if direction:
                            orb_used.add(key)
                            orb_volume_stats['breakout_closes'] += 1
                            if self.research_scope.get('opening_range_volume_filter'):
                                lookback = 20
                                prior_volumes = [item.volume for item in bars[max(0, i-lookback):i]]
                                if b.volume <= 0 or len(prior_volumes) < lookback or any(value <= 0 for value in prior_volumes):
                                    orb_volume_stats['volume_unavailable'] += 1
                                    direction, orb_range = None, None
                                elif b.volume < (sum(prior_volumes) / lookback) * self.research_scope.get('opening_range_volume_multiple', 1.5):
                                    orb_volume_stats['volume_rejected'] += 1
                                    direction, orb_range = None, None
                                else:
                                    orb_volume_stats['volume_confirmed'] += 1
            sessions = self.research_scope.get('sessions') or []
            if sessions and not any(in_window(b.timestamp, name) for name in sessions):
                continue
            if setup != 'opening_range_breakout' and (not d.should_trade or d.direction not in ('buy', 'sell')):
                continue
            if (not direction or direction not in ('buy', 'sell')
                    or (setup != 'opening_range_breakout' and not d.atr)):
                continue
            buy = direction == 'buy'
            if self.profile.trade_mode == 3 or (self.profile.trade_mode == 1 and not buy) or (self.profile.trade_mode == 2 and buy):
                continue
            nxt = bars[i+1]
            if not market_is_open(nxt.timestamp, self.profile.session):
                continue
            if sessions and not any(in_window(nxt.timestamp, name) for name in sessions):
                continue
            if orb_range and nxt.timestamp >= session_end:
                continue
            entry = self.quote(nxt.open, nxt, buy)
            if orb_range:
                # Do not fill a breakout if the next bar has already returned inside the range.
                boundary = orb_range[0] if buy else orb_range[1]
                if (buy and nxt.open <= boundary) or (not buy and nxt.open >= boundary):
                    continue
                stop = orb_range[1] if buy else orb_range[0]
                distance = abs(entry - stop)
            else:
                distance = d.atr.value * self.engine.cfg.sl_atr_mult
                stop = entry - distance if buy else entry + distance
            tick = self.profile.tick_size
            size = 0
            stable_size = False
            for _ in range(20):
                entry = self.quote(nxt.open, nxt, buy, size)
                stop_price = (orb_range[1] if buy else orb_range[0]) if orb_range else (entry - distance if buy else entry + distance)
                stop = round(stop_price / tick) * tick
                target = round((entry + abs(entry-stop)*self.engine.cfg.tp_rr if buy else entry-abs(entry-stop)*self.engine.cfg.tp_rr) / tick) * tick
                if min(stop, target) <= 0 or abs(entry-stop) <= self.profile.minimum_stop + self.spread(nxt):
                    size = 0
                    break
                next_size = self.lots(min(balance, marked) * self.engine.cfg.risk_pct, entry, stop, nxt.timestamp)
                if next_size == size:
                    stable_size = True
                    break
                size = next_size
            if size <= 0 or not stable_size:
                continue
            position = BTTrade(trade_id=f'Q{i+1}', symbol=symbol, direction=direction,
                               entry_price=entry, stop_loss=stop, take_profit=target, stake=size,
                               entry_bar=i+1, entry_ts=nxt.timestamp, confluence_score=d.confluence_score,
                               reason_code=('opening_range_breakout' if orb_range else d.reason), regime=d.hurst.regime if d.hurst else 'unknown')
            trades.append(position)
            cb.record_trade_open()
        report = BacktestReport(symbol=symbol, timeframe=timeframe, initial_balance=self.initial_balance,
                                final_balance=balance, date_from=datetime.fromtimestamp(bars[0].timestamp, timezone.utc),
                                date_to=now, trades=trades, equity_curve=equity, run_duration_sec=time.perf_counter()-started)
        self._compute_metrics(report)
        factor = math.sqrt(self.profile.annualization / 365)
        report.sharpe_ratio *= factor
        report.sortino_ratio *= factor
        report.metadata = {'model_version': 'linear-contract-next-open-v1', 'quantity_unit': 'lots',
                           'annualization': self.profile.annualization, 'profile': self.profile.model_dump(mode='json', exclude={'fx_rates'}),
                           'config': asdict(self.engine.cfg), 'stress_multiplier': self.stress,
                           'commission_basis': 'round trip account currency per lot',
                           'research_scope': self.research_scope,
                           'market_impact_model': {'method': 'user-supplied linear size-based impact',
                               'extra_ticks_per_fill': 'market_impact_ticks_per_lot × filled lots',
                               'configured_ticks_per_lot': self.profile.market_impact_ticks_per_lot,
                               'note': 'This is an explicit scenario input, not inferred from historical depth. Zero disables size-based impact.'},
                           'opening_range_volume': orb_volume_stats if self.research_scope.get('setup') == 'opening_range_breakout' else None,
                           'intrabar_ambiguity': {'same_bar_stop_and_target': ambiguous_exit_bars,
                               'resolution': 'Assume stop occurs first; intrabar price sequence is unavailable from OHLC bars.'},
                           'limitations': 'OHLC stop-first approximation; financing sampled at configured rollovers; no order-book depth, queue position or margin liquidation simulation'}
        return report
