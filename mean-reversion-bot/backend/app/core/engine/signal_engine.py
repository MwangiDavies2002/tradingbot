"""
signal_engine.py
────────────────────────────────────────────────────────────────────────────────
Signal Engine — Main Orchestration Layer
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    The signal engine is the brain of the bot. It takes a list of candles,
    runs every indicator and detector, feeds all results into the confluence
    scorer, and returns a single TradeDecision object — either a valid entry
    signal or a "no trade" with a reason.

    ORCHESTRATION ORDER:
        1. ATR          → volatility baseline for everything downstream
        2. Hurst        → regime check (suppress if trending)
        3. SwingMapper  → build liquidity zone map
        4. ZoneBuilder  → add OBs, FVGs, round numbers, PDH/PDL
        5. LSLDetector  → check for liquidity grab on latest candle
        6. BOS/CHoCH    → market structure analysis
        7. Z-Score      → primary deviation signal
        8. Bollinger    → secondary deviation signal
        9. RSI          → momentum exhaustion
       10. VWAP         → institutional mean reference
       11. Stochastic   → momentum confirmation
       12. ConfluenceScorer → aggregate score + entry decision
       13. PositionSizer   → compute stake, SL, TP if entry valid

    ALL INDICATORS run in < 10ms on a 500-candle series on a t3.medium.
    The engine is designed to be called on every candle close.

USAGE:
    from app.core.engine.signal_engine import SignalEngine, EngineConfig

    engine = SignalEngine(EngineConfig(risk_pct=0.01))
    engine.initialise(account_balance=500.0)

    decision = engine.evaluate(
        candles    = candles,        # list[Candle], newest last
        symbol     = "Volatility 75 Index",
        timeframe  = "M5",
        instrument_type = InstrumentType.VOLATILITY,
    )

    if decision.should_trade:
        place_order(decision)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.engine.confluence import ConfluenceResult, ConfluenceScorer
from app.core.indicators.atr import ATRIndicator, ATRResult
from app.core.indicators.bollinger import BollingerBands, BollingerResult
from app.core.indicators.hurst import HurstIndicator, HurstResult
from app.core.indicators.rsi import RSIIndicator, RSIResult
from app.core.indicators.stochastic import StochasticIndicator, StochasticResult
from app.core.indicators.vwap import VWAPIndicator, VWAPResult
from app.core.indicators.zscore import ZScoreIndicator, ZScoreResult
from app.core.lsl.lsl_detector import (
    Candle,
    InstrumentType,
    LSLDetector,
    LSLSignal,
    compute_atr,
)
from app.core.lsl.swing_mapper import SwingMapper, SwingMapperConfig
from app.core.lsl.zone_builder import ZoneBuilder, ZoneBuilderConfig
from app.core.risk.circuit_breaker import CircuitBreaker
from app.core.risk.position_sizer import PositionSizer, SizeResult
from app.core.smc.bos_choch import BOSCHoCHDetector, BOSCHoCHResult

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────────


@dataclass
class EngineConfig:
    """
    Central configuration for the entire signal engine.
    One config object controls all sub-components.

    Indicator Parameters
    --------------------
    zscore_period     : int    Z-score rolling window. Default 20.
    bb_period         : int    Bollinger Bands period. Default 20.
    bb_std_dev        : float  Bollinger std multiplier. Default 2.0.
    rsi_period        : int    RSI period. Default 14.
    atr_period        : int    ATR fast period. Default 14.
    stoch_k_period    : int    Stochastic %K period. Default 14.
    vwap_session_reset: bool   Reset VWAP at session open. Default True.
    swing_lookback    : int    Swing mapper lookback. Default 5.
    hurst_min_candles : int    Min candles for Hurst computation. Default 50.

    Risk Parameters
    ---------------
    risk_pct          : float  Risk per trade (decimal). Default 0.01 (1%).
    max_risk_pct      : float  Max risk per trade. Default 0.02 (2%).
    sl_atr_mult       : float  SL distance in ATR units. Default 1.5.
    tp_rr             : float  Take profit R:R ratio. Default 2.0.
    min_confluence    : int    Minimum confluence score for entry. Default 6.
    deriv_multiplier  : int    Deriv contract multiplier. Default 100.
    deriv_product     : str    Deriv product type. Default 'multiplier'.

    Circuit Breaker
    ---------------
    cb_max_losses     : int    Consecutive losses before pause. Default 3.
    cb_daily_dd       : float  Daily drawdown limit. Default 0.05.
    cb_weekly_dd      : float  Weekly drawdown limit. Default 0.10.

    Strategy Selection (Indicator Toggles)
    --------------------------------------
    use_zscore        : bool   Enable Z-Score signal. Default True.
    use_bb            : bool   Enable Bollinger Bands signal. Default True.
    use_rsi           : bool   Enable RSI signal. Default True.
    use_vwap          : bool   Enable VWAP signal. Default True.
    use_stoch         : bool   Enable Stochastic signal. Default True.
    use_lsl           : bool   Enable LSL signal. Default True.
    use_smc           : bool   Enable BOS/CHoCH & Order Blocks. Default True.
    use_volume        : bool   Enable Volume signal. Default True.
    use_hurst         : bool   Enable Hurst regime filter. Default True.
    """
    # Indicators
    zscore_period:      int   = 20
    bb_period:          int   = 20
    bb_std_dev:         float = 2.0
    rsi_period:         int   = 14
    atr_period:         int   = 14
    stoch_k_period:     int   = 14
    vwap_session_reset: bool  = True
    swing_lookback:     int   = 5
    hurst_min_candles:  int   = 50

    # Strategy Toggles
    use_zscore:         bool  = True
    use_bb:             bool  = True
    use_rsi:            bool  = True
    use_vwap:           bool  = True
    use_stoch:          bool  = True
    use_lsl:            bool  = True
    use_smc:            bool  = True
    use_volume:         bool  = True
    use_hurst:          bool  = True

    # Risk
    risk_pct:           float = 0.01
    max_risk_pct:       float = 0.02
    sl_atr_mult:        float = 1.5
    tp_rr:              float = 2.0
    min_confluence:     int   = 6
    deriv_multiplier:   int   = 100
    deriv_product:      str   = "multiplier"

    # Circuit Breaker
    cb_max_losses:      int   = 3
    cb_daily_dd:        float = 0.05
    cb_weekly_dd:       float = 0.10


# ─── Trade Decision ───────────────────────────────────────────────────────────


@dataclass
class TradeDecision:
    """
    Final output of the signal engine for one candle evaluation.

    If should_trade is True, all fields needed to place the order are populated.
    If should_trade is False, reason explains why.
    """
    symbol:            str
    timeframe:         str
    direction:         Optional[str]          # "buy", "sell", or None
    should_trade:      bool
    reason:            str

    # Populated only when should_trade = True
    confluence:        Optional[ConfluenceResult] = None
    sizing:            Optional[SizeResult]       = None
    entry_price:       Optional[float]            = None
    lsl_signal:        Optional[LSLSignal]        = None
    structure:         Optional[BOSCHoCHResult]   = None

    # Indicator snapshots for logging/dashboard
    zscore:            Optional[ZScoreResult]     = None
    bollinger:         Optional[BollingerResult]  = None
    rsi:               Optional[RSIResult]        = None
    vwap:              Optional[VWAPResult]       = None
    stoch:             Optional[StochasticResult] = None
    atr:               Optional[ATRResult]        = None
    hurst:             Optional[HurstResult]      = None

    evaluated_at:      datetime = field(default_factory=datetime.utcnow)
    eval_ms:           float = 0.0     # Engine evaluation latency

    @property
    def confluence_score(self) -> int:
        return self.confluence.score if self.confluence else 0

    @property
    def stake(self) -> float:
        return self.sizing.stake if self.sizing else 0.0

    @property
    def stop_loss(self) -> Optional[float]:
        return self.sizing.stop_loss if self.sizing else None

    @property
    def take_profit(self) -> Optional[float]:
        return self.sizing.take_profit if self.sizing else None

    def log_summary(self) -> str:
        """One-line summary for trade logs."""
        if self.should_trade:
            return (
                f"TRADE [{self.direction.upper()}] {self.symbol} {self.timeframe} | "
                f"score={self.confluence_score} | "
                f"entry={self.entry_price:.5f} | "
                f"SL={self.stop_loss:.5f} | "
                f"TP={self.take_profit:.5f} | "
                f"stake=${self.stake:.2f} | "
                f"reason={self.confluence.reason_code if self.confluence else ''}"
            )
        return f"NO TRADE | {self.symbol} {self.timeframe} | {self.reason}"

    def __repr__(self) -> str:
        return (f"TradeDecision(trade={self.should_trade} | "
                f"dir={self.direction} | score={self.confluence_score} | "
                f"reason={self.reason!r} | {self.eval_ms:.1f}ms)")


# ─── Signal Engine ────────────────────────────────────────────────────────────


class SignalEngine:
    """
    Main signal orchestration engine. Wires all indicators, detectors,
    and risk components together into a single evaluate() call.

    Designed to be instantiated once per instrument per timeframe and
    called on every candle close.
    """

    def __init__(
        self,
        config:  Optional[EngineConfig]  = None,
        cb:      Optional[CircuitBreaker] = None,
    ) -> None:
        self.cfg = config or EngineConfig()
        c = self.cfg

        # ── Indicators ────────────────────────────────────────────────────────
        self.zscore    = ZScoreIndicator(period=c.zscore_period)
        self.bollinger = BollingerBands(period=c.bb_period, std_dev=c.bb_std_dev)
        self.rsi       = RSIIndicator(period=c.rsi_period)
        self.atr_ind   = ATRIndicator(period=c.atr_period)
        self.stoch     = StochasticIndicator(k_period=c.stoch_k_period)
        self.vwap_ind  = VWAPIndicator(use_session_reset=c.vwap_session_reset)
        self.hurst_ind = HurstIndicator()

        # ── LSL + SMC ─────────────────────────────────────────────────────────
        self.swing_mapper = SwingMapper(SwingMapperConfig(lookback=c.swing_lookback))
        self.zone_builder = ZoneBuilder()
        self.bos_detector = BOSCHoCHDetector(lookback=c.swing_lookback)

        # ── Scoring + Risk ────────────────────────────────────────────────────
        self.scorer  = ConfluenceScorer(threshold_valid=c.min_confluence)
        self.sizer   = PositionSizer(
            risk_pct=c.risk_pct,
            max_risk_pct=c.max_risk_pct,
            sl_atr_mult=c.sl_atr_mult,
            tp_rr=c.tp_rr,
        )
        self.cb = cb or CircuitBreaker(
            max_consecutive_losses=c.cb_max_losses,
            daily_drawdown_pct=c.cb_daily_dd,
            weekly_drawdown_pct=c.cb_weekly_dd,
        )

        # Per-instrument LSL detectors (created lazily by instrument type)
        self._lsl_detectors: dict[str, LSLDetector] = {}

        logger.info("SignalEngine initialised | confluence_min=%d | risk=%.1f%%",
                    c.min_confluence, c.risk_pct * 100)

    def initialise(self, account_balance: float) -> None:
        """Call once on bot startup with current account balance."""
        self.sizer.update_balance(account_balance)
        self.cb.initialise(account_balance)
        logger.info("SignalEngine ready | balance=$%.2f", account_balance)

    # ── Main Evaluation Entry Point ───────────────────────────────────────────

    def evaluate(
        self,
        candles:         list[Candle],
        symbol:          str = "",
        timeframe:       str = "",
        instrument_type: Optional[InstrumentType] = None,
        htf_bias:        Optional[str] = None,    # "buy", "sell", or None (from HTF analysis)
    ) -> TradeDecision:
        """
        Evaluate the current candle for a trade opportunity.

        Call on every new closed candle. Returns a TradeDecision.
        If should_trade is True, place an order using the sizing parameters.

        Parameters
        ----------
        candles         : list[Candle]   Full candle history, newest LAST. Min 60 recommended.
        symbol          : str            Instrument symbol (e.g. "Volatility 75 Index")
        timeframe       : str            Timeframe string (e.g. "M5", "M15")
        instrument_type : InstrumentType Instrument category for specialised logic
        htf_bias        : str or None    Higher timeframe trend bias for confluence

        Returns
        -------
        TradeDecision — always returned, check .should_trade before acting.
        """
        t0 = time.perf_counter()

        def _no_trade(reason: str, direction=None, **kwargs) -> TradeDecision:
            ms = (time.perf_counter() - t0) * 1000
            return TradeDecision(
                symbol=symbol, timeframe=timeframe,
                direction=direction, should_trade=False,
                reason=reason, eval_ms=round(ms, 2), **kwargs
            )

        # ── 0. Guard: minimum candles ─────────────────────────────────────────
        if len(candles) < 30:
            return _no_trade("insufficient_candles")

        # ── 1. Guard: circuit breaker ─────────────────────────────────────────
        if not self.cb.is_trading_allowed():
            return _no_trade(f"circuit_breaker_{self.cb._state.value}")

        # ── 2. ATR — volatility baseline ─────────────────────────────────────
        atr_result = self.atr_ind.compute(candles)
        if atr_result is None:
            return _no_trade("atr_insufficient_data")
        atr = atr_result.value

        # Suppress trading during extreme volatility spikes
        if atr_result.is_spike:
            return _no_trade("volatility_spike", atr=atr_result)

        # ── 3. Hurst — regime check ───────────────────────────────────────────
        hurst_result: Optional[HurstResult] = None
        if self.cfg.use_hurst and len(candles) >= self.cfg.hurst_min_candles:
            hurst_result = self.hurst_ind.compute(candles)
            if hurst_result and hurst_result.should_suppress_mr:
                return _no_trade("trending_regime_hurst", atr=atr_result, hurst=hurst_result)

        # ── 4. Build liquidity zone map ───────────────────────────────────────
        swing_map = self.swing_mapper.build(candles, symbol=symbol, timeframe=timeframe, atr=atr)
        extra_zones = self.zone_builder.build_all(candles, timeframe=timeframe, atr=atr, symbol=symbol)
        swing_map.highs += extra_zones.highs
        swing_map.lows  += extra_zones.lows

        # ── 5. LSL — liquidity grab detection ────────────────────────────────
        lsl_signal = None
        if self.cfg.use_lsl:
            lsl_detector = self._get_lsl_detector(instrument_type)
            lsl_signal   = lsl_detector.detect(candles, swing_map, atr, symbol=symbol, timeframe=timeframe)

        # ── 6. BOS / CHoCH ────────────────────────────────────────────────────
        structure = None
        if self.cfg.use_smc:
            structure = self.bos_detector.detect(candles)

        # ── 7–11. Compute all indicators ──────────────────────────────────────
        zs_result    = self.zscore.compute(candles)   if self.cfg.use_zscore else None
        bb_result    = self.bollinger.compute(candles) if self.cfg.use_bb     else None
        rsi_result   = self.rsi.compute(candles)       if self.cfg.use_rsi    else None
        vwap_result  = self.vwap_ind.compute(candles, atr=atr) if self.cfg.use_vwap else None
        stoch_result = self.stoch.compute(candles)     if self.cfg.use_stoch  else None

        # ── 12. Determine candidate direction ────────────────────────────────
        direction = self._determine_direction(
            lsl_signal, structure, zs_result, rsi_result, htf_bias
        )

        if direction is None:
            return _no_trade(
                "no_clear_direction",
                zscore=zs_result, bollinger=bb_result, rsi=rsi_result,
                vwap=vwap_result, stoch=stoch_result, atr=atr_result,
                hurst=hurst_result, lsl_signal=lsl_signal,
            )

        # ── 13. Confluence scoring ────────────────────────────────────────────
        htf_aligned = htf_bias == direction if htf_bias else False

        confluence = self.scorer.score(
            direction    = direction,
            z_score      = zs_result.value    if zs_result   else None,
            rsi          = rsi_result.value   if rsi_result  else None,
            bb_position  = bb_result.position if bb_result   else None,
            vwap_dev     = vwap_result.deviation_atr if vwap_result else None,
            stoch_k      = stoch_result.k     if stoch_result else None,
            lsl_signal   = lsl_signal,
            bos_choch    = structure.choch_detected if structure else False,
            order_block  = self._is_at_order_block(candles[-1], extra_zones) if self.cfg.use_smc else False,
            htf_aligned  = htf_aligned,
            volume_ratio = self._volume_ratio(candles) if self.cfg.use_volume else None,
            hurst        = hurst_result.value if hurst_result else None,
            symbol       = symbol,
            timeframe    = timeframe,
        )

        if not confluence.is_valid_entry:
            return _no_trade(
                f"confluence_score_too_low_{confluence.score}",
                direction=direction,
                confluence=confluence,
                zscore=zs_result, bollinger=bb_result, rsi=rsi_result,
                vwap=vwap_result, stoch=stoch_result, atr=atr_result,
                hurst=hurst_result, lsl_signal=lsl_signal, structure=structure,
            )

        # ── 14. Position sizing ───────────────────────────────────────────────
        entry = candles[-1].close
        sizing = self.sizer.calculate(
            entry           = entry,
            atr             = atr,
            direction       = direction,
            confluence_mult = confluence.position_size_multiplier,
            product         = self.cfg.deriv_product,
            multiplier      = self.cfg.deriv_multiplier,
        )

        if not sizing.meets_minimum_rr:
            return _no_trade(
                f"rr_below_minimum_{sizing.rr_ratio}",
                direction=direction, confluence=confluence, sizing=sizing,
            )

        # ── 15. Build and return the trade decision ───────────────────────────
        ms = (time.perf_counter() - t0) * 1000
        decision = TradeDecision(
            symbol        = symbol,
            timeframe     = timeframe,
            direction     = direction,
            should_trade  = True,
            reason        = confluence.reason_code,
            confluence    = confluence,
            sizing        = sizing,
            entry_price   = entry,
            lsl_signal    = lsl_signal,
            structure     = structure,
            zscore        = zs_result,
            bollinger     = bb_result,
            rsi           = rsi_result,
            vwap          = vwap_result,
            stoch         = stoch_result,
            atr           = atr_result,
            hurst         = hurst_result,
            evaluated_at  = datetime.utcnow(),
            eval_ms       = round(ms, 2),
        )

        logger.info("✅ %s | eval=%.1fms", decision.log_summary(), ms)
        return decision

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _determine_direction(
        self,
        lsl_signal:  Optional[LSLSignal],
        structure:   Optional[BOSCHoCHResult],
        zs_result:   Optional[ZScoreResult],
        rsi_result:  Optional[RSIResult],
        htf_bias:    Optional[str],
    ) -> Optional[str]:
        """
        Determine the candidate trade direction from the highest-priority signals.

        Priority order:
        1. LSL signal (strongest — price has already shown the grab)
        2. CHoCH (structure reversal confirmed)
        3. Z-Score + RSI agreement
        4. HTF bias alone (weakest — needs other confirmation)
        """
        # LSL confirmed grab takes priority
        if lsl_signal and lsl_signal.is_confirmed:
            return lsl_signal.direction.value

        # CHoCH structure event
        if structure and structure.choch_detected and structure.direction:
            return structure.direction

        # Z-Score + RSI both agree
        if zs_result and rsi_result:
            if zs_result.direction == rsi_result.direction and zs_result.direction:
                return zs_result.direction

        # Z-Score alone (if extreme)
        if zs_result and zs_result.is_very_extreme and zs_result.direction:
            return zs_result.direction

        return None

    def _get_lsl_detector(self, instrument_type: Optional[InstrumentType]) -> LSLDetector:
        """Get or create an LSL detector for the given instrument type."""
        key = instrument_type.value if instrument_type else "standard"
        if key not in self._lsl_detectors:
            self._lsl_detectors[key] = LSLDetector(instrument_type=instrument_type)
        return self._lsl_detectors[key]

    def _is_at_order_block(self, candle: Candle, extra_zones) -> bool:
        """True if current price is within an order block zone."""
        for zone in extra_zones.highs + extra_zones.lows:
            if "order_block" in zone.zone_type:
                distance = abs(candle.close - zone.price)
                if distance / max(candle.close, 1e-8) < 0.003:   # Within 0.3%
                    return True
        return False

    def _volume_ratio(self, candles: list[Candle], period: int = 20) -> Optional[float]:
        """Current volume / avg volume ratio. None if volume data unavailable."""
        if len(candles) < period + 1:
            return None
        vols = [c.volume for c in candles[-period - 1:]]
        if all(v == 0 for v in vols):
            return None
        avg = sum(vols[:-1]) / len(vols[:-1])
        return vols[-1] / avg if avg > 0 else None
