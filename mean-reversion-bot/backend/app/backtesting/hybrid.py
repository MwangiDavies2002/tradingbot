"""Offline A/B/C/D comparison under one linear-instrument execution model.

Never imports a broker or places a live order. Original BacktestEngine.run remains
the legacy Deriv multiplier path; all comparison variants share this simulator.
"""
from bisect import bisect_right
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import mean, median, stdev

from app.core.engine.signal_engine import EngineConfig
from app.core.hybrid.campaign import TradeCampaign, InstrumentSpec
from app.core.hybrid.regime import Regime, completed_bars
from app.core.hybrid.strategy import HybridStrategy, HybridConfig
from app.core.lsl.lsl_detector import Candle
from app.core.risk.circuit_breaker import CircuitBreaker
from app.data.validation import validate_candles


VARIANTS = {
    "A": "Existing mean-reversion signals",
    "B": "Hybrid without pyramiding",
    "C": "Hybrid with confirmed scale-in",
    "D": "Hybrid with scale-in and partial exits",
}


def regime_group(regime):
    if regime in (Regime.BULLISH, Regime.BEARISH):
        return "TREND"
    return regime.value


def performance(campaigns, curve, initial_balance, config):
    trades = [c for c in campaigns if c.entries and c.terminal]
    pnl = [c.realized_pnl for c in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    rs = [c.R_realized for c in trades]
    peak, drawdown = initial_balance, 0.0
    daily = {}
    for point in curve:
        equity = point["equity"]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak if peak else 0)
        daily[point["ts"] // 86400] = equity
    values = list(daily.values())
    sharpe = None
    if len(values) >= config.min_sharpe_days + 1 and all(v > 0 for v in values):
        returns = [b / a - 1 for a, b in zip(values, values[1:])]
        deviation = stdev(returns)
        if deviation > 0:
            sharpe = mean(returns) / deviation * math.sqrt(config.annualization_days)
    return dict(total_trades=len(trades), win_rate=len(wins) / len(trades) if trades else 0,
                average_winner=mean(wins) if wins else 0, average_loser=mean(losses) if losses else 0,
                expectancy=mean(pnl) if pnl else 0, profit_factor=sum(wins) / -sum(losses) if losses else None,
                maximum_drawdown=drawdown, average_R=mean(rs) if rs else 0, median_R=median(rs) if rs else 0,
                maximum_campaign_risk=max((c.maximum_risk_used for c in trades), default=0),
                maximum_campaign_risk_percent=max((c.maximum_risk_used / c.equity_at_setup * 100 for c in trades), default=0),
                total_pnl=sum(pnl), sharpe_ratio=sharpe, sharpe_observed_days=max(0, len(values) - 1))


class CampaignBacktester:
    def __init__(self, engine_config=None, config=None, initial_balance=10000,
                 slippage_pct=.0005, spread_price=0, warmup_bars=60,
                 strategy_factory=HybridStrategy):
        self.engine_config = engine_config or EngineConfig()
        self.cfg = config or HybridConfig()
        self.initial_balance = initial_balance
        self.slippage_pct = slippage_pct
        self.spread_price = spread_price
        self.warmup_bars = warmup_bars
        self.strategy_factory = strategy_factory
        if (not math.isfinite(initial_balance) or initial_balance <= 0 or warmup_bars < 30
                or any(not math.isfinite(v) or v < 0 for v in (slippage_pct, spread_price))
                or slippage_pct >= 1):
            raise ValueError("Invalid simulator configuration")
        if self.engine_config.use_safety_orders:
            raise ValueError("Hybrid comparison requires existing adverse-distance safety orders disabled")

    def fill(self, price, direction, closing=False):
        sign = 1 if direction == "buy" else -1
        result = price + (-sign if closing else sign) * (price * self.slippage_pct + self.spread_price / 2)
        if result <= 0:
            raise ValueError("Execution costs produce a nonpositive fill")
        return result

    def run(self, candles: list[Candle], spec: InstrumentSpec, timeframe="M5", base_seconds=300, variant="D"):
        validate_candles(candles)
        if variant not in VARIANTS or len(candles) <= self.warmup_bars:
            raise ValueError("Invalid variant or insufficient history")
        if base_seconds <= 0 or any(c.timestamp % base_seconds for c in candles):
            raise ValueError("Use UTC-aligned candle-open timestamps")
        if any((b.timestamp - a.timestamp) % base_seconds for a, b in zip(candles, candles[1:])):
            raise ValueError("Candle timestamps do not match the base timeframe")
        simulated_now = datetime.fromtimestamp(candles[0].timestamp, timezone.utc)
        cb = CircuitBreaker(clock=lambda: simulated_now, max_open_positions=2,
                            max_consecutive_losses=self.engine_config.cb_max_losses,
                            daily_drawdown_pct=self.engine_config.cb_daily_dd,
                            weekly_drawdown_pct=self.engine_config.cb_weekly_dd)
        cb.initialise(self.initial_balance)
        strategy = self.strategy_factory(self.engine_config, self.cfg, cb=cb)
        strategy.initialise(self.initial_balance)
        # Preaggregate, then expose only bars whose CLOSE precedes the decision.
        higher = {tf: completed_bars(candles, tf, base_seconds, candles[-1].timestamp + base_seconds)
                  for tf in self.cfg.regime.timeframes}
        higher_closes = {tf: [c.timestamp + tf for c in bars] for tf, bars in higher.items()}
        campaigns, curve = [], []
        active, queued = None, None
        management = {}
        balance, equity = self.initial_balance, self.initial_balance
        curve.append(dict(ts=candles[self.warmup_bars - 1].timestamp + base_seconds,
                          balance=balance, equity=equity,
                          regime_equity={g: equity for g in ("TREND", "RANGE", "UNKNOWN")}))

        def cash_balance():
            return self.initial_balance + sum(c.realized_pnl for c in campaigns)

        def finished(campaign):
            cb.record_trade(pnl=campaign.realized_pnl, account_balance=cash_balance())
            cb.record_trade_close()

        for i in range(self.warmup_bars, len(candles)):
            bar = candles[i]
            close_ts = bar.timestamp + base_seconds
            simulated_now = datetime.fromtimestamp(bar.timestamp, timezone.utc)
            window = candles[max(0, i - 499):i + 1]
            # Signals generated at a close are executed only at a subsequent open.
            if queued:
                order = queued
                queued = None
                c = order["campaign"]
                c.pending_orders.pop(order["id"], None)
                price = self.fill(bar.open, c.direction, order["kind"] == "EXIT")
                if order["kind"] == "EXIT":
                    c.invalidate(bar.timestamp, price, order["reason"])
                    finished(c)
                    active = None
                elif bar.timestamp - order["confirmation_ts"] > self.cfg.confirmation_max_age_bars * base_seconds:
                    c.reject(bar.timestamp, price, "STALE_CONFIRMATION")
                    if order["kind"] == "PROBE":
                        c.invalidate(bar.timestamp, price, "STALE_SETUP")
                elif not cb.is_trading_allowed():
                    c.reject(bar.timestamp, price, "CIRCUIT_BREAKER")
                    if order["kind"] == "PROBE":
                        c.invalidate(bar.timestamp, price, "CIRCUIT_BREAKER")
                else:
                    current_equity = cash_balance()
                    if active:
                        active.mark(bar.open)
                        current_equity += active.unrealized_pnl
                    proposed_risk = c.risk_limit * order["fraction"]
                    if current_equity <= 0 or (c.current_open_risk + proposed_risk) / current_equity > self.engine_config.max_total_exposure:
                        c.reject(bar.timestamp, price, "TOTAL_EXPOSURE_LIMIT")
                        if order["kind"] == "PROBE":
                            c.invalidate(bar.timestamp, price, "TOTAL_EXPOSURE_LIMIT")
                    elif order["kind"] == "PROBE":
                        setup = order["setup"]
                        if c.sign * (setup.target - price) <= 0:
                            c.invalidate(bar.timestamp, price, "GAP_BEYOND_TARGET")
                        elif c.open_probe(order["id"], bar.timestamp, price, setup.stop,
                                          order["fraction"], setup.score, setup.reasons):
                            active = c
                            cb.record_trade_open()
                            management[c.campaign_id] = dict(target=setup.target,
                                targets=strategy.targets(c, candles[:i]), base_quantity=None, hit=set())
                            c.initial_signal["targets"] = management[c.campaign_id]["targets"]
                        else:
                            c.invalidate(bar.timestamp, price, "PROBE_REJECTED")
                    elif active is c and not c.terminal:
                        c.add(order["confirmation"], bar.timestamp, price, order["stop"],
                              order["fraction"], self.cfg.confirmation_threshold, len(self.cfg.tranches))

            # Stop-first OHLC policy; stops set at this close cannot affect this bar.
            if active:
                live = [e for e in active.entries if e.remaining]
                stop = max(e.stop for e in live) if active.sign == 1 else min(e.stop for e in live)
                stop_hit = bar.low <= stop if active.sign == 1 else bar.high >= stop
                if stop_hit:
                    raw = min(bar.open, stop) if active.sign == 1 else max(bar.open, stop)
                    active.invalidate(bar.timestamp, self.fill(raw, active.direction, True), "STOP_LOSS")
                    finished(active)
                    active = None
                elif variant != "D":
                    target = management[active.campaign_id]["target"]
                    hit = bar.high >= target if active.sign == 1 else bar.low <= target
                    if hit:
                        raw = max(bar.open, target) if active.sign == 1 else min(bar.open, target)
                        active.close(f"TP:{bar.timestamp}", bar.timestamp, self.fill(raw, active.direction, True), "TAKE_PROFIT")
                        finished(active)
                        active = None
                else:
                    m = management[active.campaign_id]
                    for index, (name, target, reason) in enumerate(m["targets"]):
                        if name in m["hit"]:
                            continue
                        hit = bar.high >= target if active.sign == 1 else bar.low <= target
                        if not hit:
                            break
                        if m["base_quantity"] is None:
                            m["base_quantity"] = active.total_quantity
                        raw = max(bar.open, target) if active.sign == 1 else min(bar.open, target)
                        quantity = m["base_quantity"] * self.cfg.exit_allocations[index]
                        accepted = active.partial_exit(name, bar.timestamp, self.fill(raw, active.direction, True), quantity, name, target)
                        m["hit"].add(name)  # sub-minimum slices are retained for the runner
                        active.log(bar.timestamp, "TARGET" if accepted else "TARGET_SKIPPED", raw, 0, (name, reason), target=target)
                    if len(m["hit"]) == 3:
                        active.start_runner(bar.timestamp, bar.close)

            simulated_now = datetime.fromtimestamp(close_ts, timezone.utc)
            histories = {tf: bars[:bisect_right(higher_closes[tf], close_ts)] for tf, bars in higher.items()}
            regime = strategy.regime_detector.classify(histories)
            if active:
                active.mark(bar.close)
            balance = cash_balance()
            equity = balance + (active.unrealized_pnl if active else 0)
            cb.mark_equity(equity)
            strategy.mr.sizer.update_balance(max(equity, 0))
            strategy.trend.sizer.update_balance(max(equity, 0))
            if active and variant != "A":
                # A strong opposing regime invalidates even a profitable campaign.
                if regime.strong and regime.direction != active.direction and "HIGH_CONFIDENCE_REVERSAL" not in active.initial_signal["reasons"]:
                    order_id = f"REGIME_EXIT:{close_ts}"
                    queued = dict(kind="EXIT", id=order_id, campaign=active, reason="HTF_INVALIDATION")
                    active.pending_orders[order_id] = {"kind": "EXIT", "timestamp": close_ts}
                    active.log(close_ts, "QUEUE_EXIT", bar.close, active.total_quantity, ("HTF_INVALIDATION",))
                else:
                    strategy.trail(active, window, close_ts)
                    if (variant in ("C", "D") and not active.partial_exits
                            and len(active.entries) < len(self.cfg.tranches) and cb.is_trading_allowed()
                            and i < len(candles) - 1):
                        result = strategy.analyse_add(active, window, regime, spec.symbol, timeframe, base_seconds)
                        if result:
                            confirmation, stop = result
                            if confirmation.event_id not in active.seen_events:
                                fraction = self.cfg.tranches[len(active.entries)]
                                queued = dict(kind="ADD", campaign=active, id=confirmation.event_id,
                                              confirmation_ts=confirmation.timestamp, confirmation=confirmation,
                                              stop=stop, fraction=fraction)
                                active.pending_orders[confirmation.event_id] = {"kind": "ADD", "timestamp": close_ts}
                                active.log(close_ts, "QUEUE_ADD", bar.close, 0, confirmation.reasons,
                                           confirmation.score, stop=stop)
            if not active and not queued and i < len(candles) - 1 and equity > 0 and cb.is_trading_allowed():
                setup, _ = strategy.analyse(window, histories, spec.symbol, timeframe, base_seconds, baseline=variant == "A")
                if setup and "ADD_ONLY" not in setup.reasons:
                    c = TradeCampaign(f"{spec.symbol}:{variant}:{close_ts}", spec.symbol, setup.direction,
                                      setup.regime, dict(timestamp=close_ts, score=setup.score, reasons=list(setup.reasons), target=setup.target),
                                      spec, equity, self.cfg.max_trade_risk_percent, timeframe,
                                      self.slippage_pct, self.spread_price / 2)
                    c.setup(close_ts, bar.close)
                    campaigns.append(c)
                    event_id = f"PROBE:{close_ts}:{setup.direction}"
                    fraction = 1.0 if variant == "A" else self.cfg.tranches[0]
                    queued = dict(kind="PROBE", id=event_id, campaign=c, setup=setup,
                                  confirmation_ts=close_ts, fraction=fraction)
                    c.pending_orders[event_id] = {"kind": "PROBE", "timestamp": close_ts}
                    c.log(close_ts, "QUEUE_PROBE", bar.close, 0, setup.reasons, setup.score, stop=setup.stop, target=setup.target)
            group_equity = {}
            for group in ("TREND", "RANGE", "UNKNOWN"):
                group_equity[group] = self.initial_balance + sum(c.realized_pnl + (c.unrealized_pnl if c is active else 0)
                    for c in campaigns if regime_group(c.market_regime) == group)
            curve.append(dict(ts=close_ts, balance=balance, equity=equity, regime_equity=group_equity))

        last = candles[-1]
        if active:
            active.close("END_OF_DATA", last.timestamp + base_seconds, self.fill(last.close, active.direction, True), "END_OF_DATA")
            finished(active)
        balance = cash_balance()
        curve[-1].update(balance=balance, equity=balance,
            regime_equity={g: self.initial_balance + sum(c.realized_pnl for c in campaigns if regime_group(c.market_regime) == g)
                           for g in ("TREND", "RANGE", "UNKNOWN")})
        metrics = performance(campaigns, curve, self.initial_balance, self.cfg)
        groups = {}
        for group in ("TREND", "RANGE", "UNKNOWN"):
            selected = [c for c in campaigns if regime_group(c.market_regime) == group]
            grouped_curve = [dict(ts=p["ts"], equity=p["regime_equity"][group]) for p in curve]
            groups[group] = performance(selected, grouped_curve, self.initial_balance, self.cfg)
        metadata = dict(model="linear-next-open-campaign-v1", variant=VARIANTS[variant],
                        engine_config=asdict(self.engine_config), hybrid_config=asdict(self.cfg),
                        instrument=asdict(spec), slippage_pct=self.slippage_pct, spread_price=self.spread_price,
                        base_seconds=base_seconds, timeframe=timeframe, warmup_bars=self.warmup_bars,
                        initial_balance=self.initial_balance,
                        intrabar_policy="stop_first", R_denominator="initial_probe_risk_including_fees",
                        timestamp_policy="Candle-open UTC epochs; decisions at close; intrabar fills assigned bar-open timestamp",
                        sharpe_min_days=self.cfg.min_sharpe_days, sharpe_annualization_days=self.cfg.annualization_days,
                        limitations="OHLC approximation; gaps can exceed stop-based risk; no liquidity/latency model. A uses original MR signals with the same linear sizing/cost model as B-D, not Deriv settlement.")
        metadata["data_sha256"] = hashlib.sha256(json.dumps([asdict(c) for c in candles], sort_keys=True).encode()).hexdigest()
        metadata["config_sha256"] = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        return dict(variant=variant, symbol=spec.symbol, initial_balance=self.initial_balance,
                    final_balance=balance, metrics=metrics, by_regime=groups,
                    by_instrument={spec.symbol: metrics}, campaigns=[c.to_dict() for c in campaigns],
                    equity_curve=curve, metadata=metadata)

    def compare(self, datasets: dict[str, list[Candle]], specs: dict[str, InstrumentSpec],
                timeframe="M5", base_seconds=300):
        if not datasets or set(datasets) != set(specs) or any(specs[s].symbol != s for s in datasets):
            raise ValueError("Provide matching datasets and explicit instrument specifications")
        return dict(model="Independent per-instrument runs; not a shared portfolio", variants={
            variant: {symbol: self.run(candles, specs[symbol], timeframe, base_seconds, variant)
                      for symbol, candles in datasets.items()}
            for variant in VARIANTS})
