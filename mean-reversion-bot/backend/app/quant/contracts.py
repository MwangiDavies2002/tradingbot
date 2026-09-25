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


class ContractBacktest(BacktestEngine):
    def __init__(self, config, profile, initial_balance=10000, stress=1):
        super().__init__(SignalEngine(config), initial_balance=initial_balance, max_open=1)
        self.profile = profile
        self.stress = stress
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

    def quote(self, price, bar, buy):
        spread = self.spread(bar)
        adjustment = (spread if buy else 0) if self.profile.price_basis == 'bid' else (spread / 2 if buy else -spread / 2)
        slip = self.profile.slippage_ticks * self.profile.tick_size * self.stress * (1 if buy else -1)
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
        loss = abs(entry - stop) * self.profile.contract_size * self.conversion(timestamp)
        loss += self.profile.commission_per_lot * self.stress
        raw = min(budget / max(loss, 1e-12), self.profile.volume_max)
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
                if stop or target or i == len(bars)-1:
                    if stop:
                        price = min(op, position.stop_loss) if buy else max(op, position.stop_loss)
                        reason = 'stop_loss'
                    elif target:
                        price, reason = position.take_profit, 'take_profit'
                    else:
                        price, reason = b.close+shift, 'end_of_data'
                    price += self.profile.slippage_ticks * self.profile.tick_size * self.stress * (-1 if buy else 1)
                    pnl = self.cash_pnl(position, price, b.timestamp)
                    position.exit_bar, position.exit_ts, position.exit_price = i, b.timestamp, price
                    position.pnl, position.close_reason = pnl, reason
                    balance += pnl
                    cb.record_trade(pnl=pnl, account_balance=balance)
                    cb.record_trade_close()
                    position = None
            marked = balance + (self.cash_pnl(position, self.quote(b.close, b, position.direction != 'buy'), b.timestamp) if position else 0)
            equity.append({'ts': b.timestamp, 'balance': balance, 'equity': marked})
            cb.mark_equity(marked)
            self.engine.sizer.update_balance(max(0, marked))
            if position or i == len(bars)-1 or marked <= 0 or not cb.is_trading_allowed():
                continue
            d = self.engine.evaluate(candles[max(0, i-499):i+1], symbol=symbol, timeframe=timeframe)
            if not d.should_trade or d.direction not in ('buy', 'sell') or not d.atr:
                continue
            buy = d.direction == 'buy'
            if self.profile.trade_mode == 3 or (self.profile.trade_mode == 1 and not buy) or (self.profile.trade_mode == 2 and buy):
                continue
            nxt = bars[i+1]
            entry = self.quote(nxt.open, nxt, buy)
            distance = d.atr.value * self.engine.cfg.sl_atr_mult
            tick = self.profile.tick_size
            stop = round((entry - distance if buy else entry + distance) / tick) * tick
            target = round((entry + distance*self.engine.cfg.tp_rr if buy else entry-distance*self.engine.cfg.tp_rr) / tick) * tick
            if min(stop, target) <= 0 or abs(entry-stop) <= self.profile.minimum_stop + self.spread(nxt):
                continue
            size = self.lots(min(balance, marked) * self.engine.cfg.risk_pct, entry, stop, nxt.timestamp)
            if size <= 0:
                continue
            position = BTTrade(trade_id=f'Q{i+1}', symbol=symbol, direction=d.direction,
                               entry_price=entry, stop_loss=stop, take_profit=target, stake=size,
                               entry_bar=i+1, entry_ts=nxt.timestamp, confluence_score=d.confluence_score,
                               reason_code=d.reason, regime=d.hurst.regime if d.hurst else 'unknown')
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
                           'limitations': 'OHLC stop-first approximation; financing sampled at configured rollovers; no liquidity, margin liquidation, queue or market-impact simulation'}
        return report
