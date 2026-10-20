"""Hybrid adapter: existing signal/detector pipeline plus opt-in trend pullbacks."""
from dataclasses import dataclass, field, replace
import math

from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.core.hybrid.campaign import Confirmation
from app.core.hybrid.regime import MarketRegime, RegimeConfig, Regime, ema


@dataclass(frozen=True)
class HybridConfig:
    max_trade_risk_percent: float = 1.0
    tranches: tuple[float, ...] = (.25, .25, .25, .25)
    exit_allocations: tuple[float, ...] = (.25, .25, .25, .25)
    confirmation_threshold: int = 6
    reversal_threshold: int = 9
    value_period: int = 50
    value_tolerance_atr: float = .5
    max_extension_atr: float = 2.0
    expansion_atr: float = 1.0
    expansion_lookback: int = 20
    tp3_r: float = 3.0
    tp1_fallback_r: float = 1.0
    tp2_fallback_r: float = 2.0
    trail_mode: str = "structure"
    trail_atr: float = 2.0
    confirmation_max_age_bars: int = 1
    annualization_days: int = 252
    min_sharpe_days: int = 30
    regime: RegimeConfig = field(default_factory=RegimeConfig)

    def __post_init__(self):
        for allocation in (self.tranches, self.exit_allocations):
            if not allocation or any(not math.isfinite(v) or v <= 0 for v in allocation) or not math.isclose(sum(allocation), 1):
                raise ValueError("Allocations must be positive and sum to one")
        if len(self.exit_allocations) != 4:
            raise ValueError("Use TP1, TP2, TP3 and runner allocations")
        for value in (self.max_trade_risk_percent, self.value_tolerance_atr, self.max_extension_atr,
                      self.expansion_atr, self.tp3_r, self.trail_atr):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Hybrid parameters must be finite and positive")
        if (self.max_trade_risk_percent > 100 or self.value_period < 2 or self.expansion_lookback < 2
                or self.confirmation_threshold < 1 or self.reversal_threshold < self.confirmation_threshold
                or self.confirmation_max_age_bars < 1 or self.annualization_days < 1 or self.min_sharpe_days < 3):
            raise ValueError("Invalid hybrid configuration")
        if self.trail_mode not in {"structure", "atr", "ema", "vwap", "vwma"}:
            raise ValueError("Unsupported runner trail")
        if not 0 < self.tp1_fallback_r < self.tp2_fallback_r < self.tp3_r or not math.isfinite(self.tp3_r):
            raise ValueError("Fallback targets must be ordered positive R multiples")


@dataclass
class HybridSetup:
    direction: str
    stop: float
    target: float
    score: float
    reasons: tuple[str, ...]
    confirmation: Confirmation | None
    regime: Regime
    value_areas: tuple[str, ...] = ()


class HybridStrategy:
    def __init__(self, engine_config=None, config=None, cb=None):
        self.cfg = config or HybridConfig()
        original = engine_config or EngineConfig()
        # Dedicated instances leave the user's live strategy and config untouched.
        original = replace(original, use_safety_orders=False, use_trailing_stop=False)
        self.mr = SignalEngine(original, cb=cb)
        self.trend = SignalEngine(replace(original, use_hurst=False), cb=cb)
        self.regime_detector = MarketRegime(self.cfg.regime)

    def initialise(self, balance):
        self.mr.initialise(balance)
        self.trend.initialise(balance)

    def value_levels(self, candles, direction, atr, symbol="", supplied=None):
        if len(candles) < self.cfg.value_period + 1:
            return {}, ()
        prior = candles[:-1]
        prices = [c.close for c in prior]
        levels = {"EMA_PULLBACK": ema(prices, self.cfg.value_period)}
        recent = prior[-self.cfg.value_period:]
        volume = sum(c.volume for c in recent)
        if volume > 0:
            levels["VWMA_PULLBACK"] = sum(c.close * c.volume for c in recent) / volume
        # Ignore indicator fallback volume; VWAP requires actual reported volume.
        session = [c for c in prior if c.timestamp // 86400 == candles[-1].timestamp // 86400]
        if sum(c.volume for c in session) > 0:
            levels["VWAP_PULLBACK"] = sum((c.high + c.low + c.close) / 3 * c.volume for c in session) / sum(c.volume for c in session)
        zones = self.trend.zone_builder.build_all(prior, symbol=symbol, atr=atr)
        candidates = [z for z in (zones.lows if direction == "buy" else zones.highs)
                      if z.zone_type == ("order_block_bullish" if direction == "buy" else "order_block_bearish")
                      and not z.invalidated]
        if candidates:
            levels["DEMAND_ZONE" if direction == "buy" else "SUPPLY_ZONE"] = min(candidates, key=lambda z: abs(z.price - candles[-1].close)).price
        structure = self.trend.bos_detector.detect(prior)
        broken = structure.swing_highs if direction == "buy" else structure.swing_lows
        if broken:
            level = broken[-1].price
            sign = 1 if direction == "buy" else -1
            if any(sign * (c.close - level) > 0 for c in prior[-self.cfg.expansion_lookback:]):
                levels["BREAKOUT_RETEST"] = level
        for reason, price in (supplied or {}).items():
            if reason not in {"PREVIOUS_POC", "PREVIOUS_VAH", "PREVIOUS_VAL", "HVN", "LVN", "BREAKOUT_RETEST"} or not math.isfinite(price) or price <= 0:
                raise ValueError("Invalid supplied causal value level")
            levels[reason] = price
        sign = 1 if direction == "buy" else -1
        current = candles[-1]
        touched = []
        for reason, level in levels.items():
            distance = max(current.low - level, level - current.high, 0)
            expanded = max(sign * (c.close - level) for c in prior[-self.cfg.expansion_lookback:]) >= self.cfg.expansion_atr * atr
            if (distance <= self.cfg.value_tolerance_atr * atr
                    and 0 <= sign * (current.close - level) <= self.cfg.max_extension_atr * atr and expanded):
                touched.append(reason)
        return levels, tuple(touched)

    def confirmation(self, candles, direction, decision, score, levels=None, base_seconds=300):
        current, previous = candles[-2:]
        sign = 1 if direction == "buy" else -1
        reasons, identities = [], []
        structure = self.trend.bos_detector.detect(candles)
        if (structure.bos_detected or structure.choch_detected) and structure.direction == direction and structure.event_candle and structure.event_candle.timestamp == current.timestamp:
            reasons.append("BOS_CONFIRMED")
            identities.append(f"BOS:{structure.event_candle.timestamp}")
        lsl = decision.lsl_signal
        if lsl and lsl.is_confirmed and lsl.direction.value == direction and lsl.trigger_candle.timestamp == current.timestamp:
            reasons.append("LIQUIDITY_SWEEP")
            identities.append(f"LSL:{lsl.trigger_candle.timestamp}:{lsl.zone.price}")
        pivots = structure.swing_lows if direction == "buy" else structure.swing_highs
        if len(pivots) >= 2 and sign * (pivots[-1].price - pivots[-2].price) > 0:
            available_at = pivots[-1].timestamp + self.trend.cfg.swing_lookback * base_seconds
            if available_at == current.timestamp:
                reasons.append("NEW_HIGHER_LOW" if direction == "buy" else "NEW_LOWER_HIGH")
                identities.append(f"PIVOT:{pivots[-1].timestamp}")
        atr = decision.atr.value if decision.atr else 0
        if atr and sign * (current.close - current.open) >= atr * .8 and sign * (current.close - previous.close) > 0:
            reasons.append("BULLISH_DISPLACEMENT" if direction == "buy" else "BEARISH_DISPLACEMENT")
            identities.append(f"DISPLACEMENT:{current.timestamp}")
        vwap = (levels or {}).get("VWAP_PULLBACK")
        if vwap and sign * (previous.close - vwap) <= 0 < sign * (current.close - vwap):
            reasons.append("VWAP_RECLAIM" if direction == "buy" else "VWAP_REJECTION")
            identities.append(f"VWAP:{current.timestamp}")
        retest = (levels or {}).get("BREAKOUT_RETEST")
        if retest and current.low <= retest <= current.high and sign * (current.close - retest) > 0 and sign * (previous.close - retest) > 0:
            reasons.append("SUCCESSFUL_RETEST")
            identities.append(f"RETEST:{current.timestamp}:{retest}")
        if not reasons:
            return None
        return Confirmation("|".join(identities), current.timestamp + base_seconds, direction, score, tuple(reasons))

    def analyse(self, candles, histories, symbol, timeframe, base_seconds, baseline=False, supplied_levels=None):
        regime = self.regime_detector.classify(histories)
        engine = self.mr if baseline or regime.regime in (Regime.RANGE, Regime.UNKNOWN) else self.trend
        decision = engine.evaluate(candles, symbol=symbol, timeframe=timeframe, htf_bias=None if baseline else regime.direction)
        if baseline or regime.regime == Regime.RANGE:
            if not decision.should_trade:
                return None, regime
            event = self.confirmation(candles, decision.direction, decision, decision.confluence_score, base_seconds=base_seconds)
            return HybridSetup(decision.direction, decision.stop_loss, decision.take_profit,
                               decision.confluence_score, (decision.reason,), event, regime.regime), regime
        if regime.regime == Regime.UNKNOWN or not decision.atr or not decision.confluence:
            return None, regime
        # A counter-trend exception must be explicit in the ORIGINAL signal evidence.
        reversal = (decision.should_trade and decision.direction != regime.direction
                    and decision.confluence_score >= self.cfg.reversal_threshold
                    and decision.lsl_signal and decision.lsl_signal.is_confirmed
                    and decision.lsl_signal.direction.value == decision.direction
                    and decision.lsl_signal.trigger_candle.timestamp == candles[-1].timestamp
                    and decision.structure and decision.structure.choch_detected
                    and decision.structure.direction == decision.direction
                    and decision.structure.event_candle
                    and decision.structure.event_candle.timestamp == candles[-1].timestamp)
        if reversal:
            event = self.confirmation(candles, decision.direction, decision, decision.confluence_score, base_seconds=base_seconds)
            return HybridSetup(decision.direction, decision.stop_loss, decision.take_profit,
                               decision.confluence_score, ("HIGH_CONFIDENCE_REVERSAL", decision.reason), event, regime.regime), regime
        direction = regime.direction
        atr = decision.atr.value
        levels, touched = self.value_levels(candles, direction, atr, symbol, supplied_levels)
        structure = engine.bos_detector.detect(candles)
        base = engine.scorer.score(
            direction=direction, z_score=decision.zscore.value if decision.zscore else None,
            rsi=decision.rsi.value if decision.rsi else None,
            bb_position=decision.bollinger.position if decision.bollinger else None,
            vwap_dev=decision.vwap.deviation_atr if decision.vwap else None,
            stoch_k=decision.stoch.k if decision.stoch else None,
            lsl_signal=decision.lsl_signal, bos_choch=structure.direction == direction and (structure.bos_detected or structure.choch_detected),
            order_block=("DEMAND_ZONE" in touched or "SUPPLY_ZONE" in touched),
            htf_aligned=True, volume_ratio=engine._volume_ratio(candles) if engine.cfg.use_volume else None,
            symbol=symbol, timeframe=timeframe)
        event = self.confirmation(candles, direction, decision, base.score, levels, base_seconds)
        scored = engine.scorer.with_hybrid_context(base, touched, event.reasons if event else ())
        if not scored.is_valid_entry or not touched or not event:
            return None, regime
        # Initial entries need liquidity/structure/retest confirmation; displacement alone is an add event.
        initial_confirmations = {"BOS_CONFIRMED", "LIQUIDITY_SWEEP", "NEW_HIGHER_LOW", "NEW_LOWER_HIGH", "SUCCESSFUL_RETEST", "VWAP_RECLAIM", "VWAP_REJECTION"}
        stop = candles[-1].close - (1 if direction == "buy" else -1) * atr * engine.cfg.sl_atr_mult
        pivots = structure.swing_lows if direction == "buy" else structure.swing_highs
        if pivots and (1 if direction == "buy" else -1) * (candles[-1].close - pivots[-1].price) > 0:
            stop = pivots[-1].price - (1 if direction == "buy" else -1) * .1 * atr
        target = candles[-1].close + (1 if direction == "buy" else -1) * abs(candles[-1].close - stop) * engine.cfg.tp_rr
        reasons = regime.reasons + touched + event.reasons
        if not set(event.reasons) & initial_confirmations:
            reasons += ("ADD_ONLY",)
        return HybridSetup(direction, stop, target, scored.score, reasons,
                           replace(event, score=scored.score), regime.regime, touched), regime

    def trail(self, campaign, candles, timestamp):
        """Use information available at this close, effective for subsequent bars."""
        if campaign.terminal or not campaign.total_quantity:
            return False
        current = candles[-1]
        atr = self.trend.atr_ind.compute(candles)
        if not atr:
            return False
        sign = campaign.sign
        mode = self.cfg.trail_mode
        if mode == "structure":
            structure = self.trend.bos_detector.detect(candles)
            pivots = structure.swing_lows if sign == 1 else structure.swing_highs
            if not pivots or pivots[-1].timestamp <= campaign.entries[0].timestamp:
                return False
            stop = pivots[-1].price - sign * .1 * atr.value
            reason = "STRUCTURE_TRAIL"
        elif mode == "atr":
            # ATR trailing is an explicitly configured rule, never an automatic BE jump.
            since_entry = [c for c in candles if c.timestamp >= campaign.entries[0].timestamp]
            extreme = max(c.high for c in since_entry) if sign == 1 else min(c.low for c in since_entry)
            stop, reason = extreme - sign * self.cfg.trail_atr * atr.value, "ATR_TRAIL"
        elif mode == "ema":
            if len(candles) < self.cfg.value_period:
                return False
            stop = ema([c.close for c in candles], self.cfg.value_period) - sign * .1 * atr.value
            reason = "EMA_TRAIL"
        else:
            bars = ([c for c in candles if c.timestamp // 86400 == current.timestamp // 86400]
                    if mode == "vwap" else candles[-self.cfg.value_period:])
            volume = sum(c.volume for c in bars)
            if not volume:
                return False
            value = sum(((c.high + c.low + c.close) / 3 if mode == "vwap" else c.close) * c.volume for c in bars) / volume
            stop, reason = value - sign * .1 * atr.value, "VWAP_TRAIL" if mode == "vwap" else "VWMA_TRAIL"
        return campaign.move_stop(timestamp, current.close, stop, reason)

    def analyse_add(self, campaign, candles, regime, symbol, timeframe, base_seconds):
        """Adds require a fresh event, independently of the initial pullback gate."""
        if regime.regime == Regime.UNKNOWN or (regime.strong and regime.direction != campaign.direction):
            return None
        decision = self.trend.evaluate(candles, symbol=symbol, timeframe=timeframe, htf_bias=campaign.direction)
        if not decision.atr or not decision.confluence:
            return None
        direction = campaign.direction
        levels, touched = self.value_levels(candles, direction, decision.atr.value, symbol)
        structure = self.trend.bos_detector.detect(candles)
        base = self.trend.scorer.score(
            direction, z_score=decision.zscore.value if decision.zscore else None,
            rsi=decision.rsi.value if decision.rsi else None,
            bb_position=decision.bollinger.position if decision.bollinger else None,
            vwap_dev=decision.vwap.deviation_atr if decision.vwap else None,
            stoch_k=decision.stoch.k if decision.stoch else None,
            lsl_signal=decision.lsl_signal,
            bos_choch=structure.direction == direction and (structure.bos_detected or structure.choch_detected),
            htf_aligned=regime.direction == direction,
            volume_ratio=self.trend._volume_ratio(candles) if self.trend.cfg.use_volume else None)
        event = self.confirmation(candles, direction, decision, base.score, levels, base_seconds)
        if not event:
            return None
        score = self.trend.scorer.with_hybrid_context(base, touched, event.reasons).score
        if score < self.cfg.confirmation_threshold:
            return None
        stop = max(e.stop for e in campaign.entries if e.remaining) if campaign.sign == 1 else min(e.stop for e in campaign.entries if e.remaining)
        pivots = structure.swing_lows if campaign.sign == 1 else structure.swing_highs
        if pivots and pivots[-1].timestamp > campaign.entries[-1].timestamp:
            structural_stop = pivots[-1].price - campaign.sign * .1 * decision.atr.value
            if campaign.sign * (structural_stop - stop) > 0 and campaign.sign * (candles[-1].close - structural_stop) > 0:
                stop = structural_stop
        return replace(event, score=score), stop

    def targets(self, campaign, candles):
        entry, stop = campaign.entries[0].price, campaign.entries[0].stop
        sign, distance = campaign.sign, abs(entry - stop)
        fallback1 = entry + sign * distance * self.cfg.tp1_fallback_r
        fallback2 = entry + sign * distance * self.cfg.tp2_fallback_r
        tp3 = entry + sign * distance * self.cfg.tp3_r
        swing_map = self.trend.swing_mapper.build(candles, symbol=campaign.symbol)
        opposing = swing_map.highs if sign == 1 else swing_map.lows
        nearby = [z.price for z in opposing if 0 < sign * (z.price - entry) <= distance * self.cfg.tp1_fallback_r]
        tp1 = min(nearby, key=lambda p: abs(p - entry)) if nearby else fallback1
        current_day = candles[-1].timestamp // 86400
        previous_days = [c.timestamp // 86400 for c in candles if c.timestamp // 86400 < current_day]
        prior_session = [c for c in candles if previous_days and c.timestamp // 86400 == max(previous_days)]
        previous_objective = ((max(c.high for c in prior_session) if sign == 1 else min(c.low for c in prior_session))
                              if prior_session else None)
        tp2 = previous_objective if previous_objective and 0 < sign * (previous_objective - tp1) and sign * (tp3 - previous_objective) > 0 else fallback2
        if sign * (tp2 - tp1) <= 0:
            tp1, tp2 = fallback1, fallback2
        return [("TP1", tp1, "OPPOSING_LIQUIDITY" if nearby else "TP1_R_FALLBACK"),
                ("TP2", tp2, "PREVIOUS_SESSION_OBJECTIVE" if tp2 == previous_objective else "TP2_R_FALLBACK"),
                ("TP3", tp3, "R_OBJECTIVE")]
