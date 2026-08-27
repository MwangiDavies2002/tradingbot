"""
confluence.py
────────────────────────────────────────────────────────────────────────────────
Multi-Signal Confluence Scorer — The Trade Gate
────────────────────────────────────────────────────────────────────────────────

WHAT THIS MODULE DOES:
    Aggregates signals from every indicator and detector into a single
    confluence score. A trade only fires when that score meets the threshold.

    This is the most important risk control in the entire system.
    It prevents low-quality, single-signal trades and enforces the rule:
    "Only trade when multiple independent signals agree."

SCORING SYSTEM (max ~17 points):
    ┌──────────────────────────────────────────┬────────┐
    │ Signal                                   │ Points │
    ├──────────────────────────────────────────┼────────┤
    │ Z-Score |z| > 2.0                        │ +2     │
    │ Z-Score |z| > 2.5 (bonus)                │ +1     │
    │ RSI extreme (< 25 or > 75)               │ +2     │
    │ Bollinger Band breach                    │ +1     │
    │ VWAP deviation > 1.5 ATR                 │ +1     │
    │ Stochastic extreme (< 15 or > 85)        │ +1     │
    │ LSL grab confirmed (wick > 0.6)          │ +2     │
    │ LSL very strong grab (score > 0.75)      │ +1     │
    │ SMC: BOS / CHoCH detected                │ +1     │
    │ SMC: Order Block present                 │ +2     │
    │ HTF trend aligned                        │ +1     │
    │ Volume spike > 1.5× avg                  │ +1     │
    │ Hurst exponent < 0.45 (MR regime)        │ +1     │
    └──────────────────────────────────────────┴────────┘

ENTRY THRESHOLDS:
    Score ≥ 6  → Valid setup — standard position size
    Score ≥ 9  → High-conviction A+ setup — 1.5× position size
    Score < 6  → NO TRADE

USAGE:
    from app.core.engine.confluence import ConfluenceScorer, ConfluenceResult

    scorer = ConfluenceScorer()
    result = scorer.score(
        direction   = "buy",
        z_score     = -2.3,
        rsi         = 22.0,
        bb_position = "below_lower",
        vwap_dev    = -1.8,
        stoch_k     = 12.0,
        lsl_signal  = lsl_signal,       # LSLSignal or None
        bos_choch   = True,
        order_block = True,
        htf_aligned = True,
        volume_ratio= 1.7,
        hurst       = 0.38,
    )

    if result.is_valid_entry:
        order = build_order(direction, result.position_size_mult)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.lsl.lsl_detector import GrabDirection, LSLSignal

logger = logging.getLogger(__name__)


# ─── Score Breakdown ──────────────────────────────────────────────────────────


@dataclass
class ScoreBreakdown:
    """
    Itemised breakdown of every point in the confluence score.
    Used for audit trails, dashboard display, and debugging.
    """
    # Quantitative signals
    z_score_points:     int = 0   # 0, 2, or 3
    rsi_points:         int = 0   # 0 or 2
    bb_points:          int = 0   # 0 or 1
    vwap_points:        int = 0   # 0 or 1
    stoch_points:       int = 0   # 0 or 1

    # LSL signals
    lsl_points:         int = 0   # 0, 2, or 3

    # SMC signals
    bos_choch_points:   int = 0   # 0 or 1
    order_block_points: int = 0   # 0 or 2

    # Context signals
    htf_points:         int = 0   # 0 or 1
    volume_points:      int = 0   # 0 or 1
    hurst_points:       int = 0   # 0 or 1

    @property
    def total(self) -> int:
        return (
            self.z_score_points +
            self.rsi_points +
            self.bb_points +
            self.vwap_points +
            self.stoch_points +
            self.lsl_points +
            self.bos_choch_points +
            self.order_block_points +
            self.htf_points +
            self.volume_points +
            self.hurst_points
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "z_score":     self.z_score_points,
            "rsi":         self.rsi_points,
            "bollinger":   self.bb_points,
            "vwap":        self.vwap_points,
            "stochastic":  self.stoch_points,
            "lsl":         self.lsl_points,
            "bos_choch":   self.bos_choch_points,
            "order_block": self.order_block_points,
            "htf_trend":   self.htf_points,
            "volume":      self.volume_points,
            "hurst":       self.hurst_points,
            "total":       self.total,
        }

    def summary_line(self) -> str:
        """One-line score summary for logging."""
        parts = []
        if self.z_score_points:     parts.append(f"Z:{self.z_score_points}")
        if self.rsi_points:         parts.append(f"RSI:{self.rsi_points}")
        if self.bb_points:          parts.append(f"BB:{self.bb_points}")
        if self.vwap_points:        parts.append(f"VWAP:{self.vwap_points}")
        if self.stoch_points:       parts.append(f"Stoch:{self.stoch_points}")
        if self.lsl_points:         parts.append(f"LSL:{self.lsl_points}")
        if self.bos_choch_points:   parts.append(f"CHoCH:{self.bos_choch_points}")
        if self.order_block_points: parts.append(f"OB:{self.order_block_points}")
        if self.htf_points:         parts.append(f"HTF:{self.htf_points}")
        if self.volume_points:      parts.append(f"Vol:{self.volume_points}")
        if self.hurst_points:       parts.append(f"Hurst:{self.hurst_points}")
        return " | ".join(parts) + f" → TOTAL: {self.total}"


# ─── Result ───────────────────────────────────────────────────────────────────


@dataclass
class ConfluenceResult:
    """
    Full result from the confluence scorer for one evaluation.

    Contains the score breakdown, entry decision, position size multiplier,
    and a reason code for logging and auditing.
    """
    direction:           str                 # "buy" or "sell"
    breakdown:           ScoreBreakdown
    symbol:              str = ""
    timeframe:           str = ""
    evaluated_at:        datetime = field(default_factory=datetime.utcnow)

    # Threshold configuration (copied from scorer for audit)
    threshold_valid:     int = 6
    threshold_aplus:     int = 9

    @property
    def score(self) -> int:
        return self.breakdown.total

    @property
    def is_valid_entry(self) -> bool:
        """True if score meets minimum threshold for a trade."""
        return self.score >= self.threshold_valid

    @property
    def is_aplus_setup(self) -> bool:
        """True if score meets A+ threshold — allows larger position size."""
        return self.score >= self.threshold_aplus

    @property
    def position_size_multiplier(self) -> float:
        """
        Returns position size multiplier based on score quality.
        Applied ON TOP of the base position size from risk management.

        - A+ setup (score ≥ 9):  1.5× base size
        - Valid setup (score ≥ 6): 1.0× base size
        - Below threshold:         0.0 (no trade)
        """
        if self.is_aplus_setup:
            return 1.5
        if self.is_valid_entry:
            return 1.0
        return 0.0

    @property
    def quality_label(self) -> str:
        """Human-readable quality label for dashboards and logs."""
        if self.is_aplus_setup:
            return "A+"
        if self.is_valid_entry:
            return "B"
        if self.score >= 4:
            return "C (below threshold)"
        return "D (weak)"

    @property
    def reason_code(self) -> str:
        """
        Short reason code for database storage and filtering.
        Format: SCORE_DIRECTION_SIGNALS  e.g. "8_BUY_ZRS_LSL_OB"
        """
        parts = [str(self.score), self.direction.upper()]
        bd = self.breakdown
        if bd.z_score_points:     parts.append("ZRS")
        if bd.rsi_points:         parts.append("RSI")
        if bd.bb_points:          parts.append("BB")
        if bd.vwap_points:        parts.append("VWP")
        if bd.stoch_points:       parts.append("STO")
        if bd.lsl_points:         parts.append("LSL")
        if bd.bos_choch_points:   parts.append("CHC")
        if bd.order_block_points: parts.append("OB")
        if bd.htf_points:         parts.append("HTF")
        if bd.volume_points:      parts.append("VOL")
        if bd.hurst_points:       parts.append("HUR")
        return "_".join(parts)

    def __repr__(self) -> str:
        return (
            f"ConfluenceResult({self.direction.upper()} | "
            f"score={self.score} | "
            f"quality={self.quality_label} | "
            f"valid={self.is_valid_entry} | "
            f"size_mult={self.position_size_multiplier}x)"
        )


# ─── Confluence Scorer ────────────────────────────────────────────────────────


class ConfluenceScorer:
    """
    Multi-signal confluence scorer — the trade gate.

    Every potential trade passes through this scorer. Only setups that
    accumulate enough agreement across independent signal categories
    are allowed to proceed to order execution.

    Parameters
    ----------
    threshold_valid : int
        Minimum score for a valid entry. Default 6.
        Increase to 7–8 for more conservative filtering.

    threshold_aplus : int
        Score threshold for A+ / high-conviction setup. Default 9.
        These setups allow 1.5× position size.

    z_score_threshold : float
        |Z-score| must exceed this to earn Z-score points. Default 2.0.

    z_score_strong : float
        |Z-score| above this earns the extra +1 bonus point. Default 2.5.

    rsi_oversold : float
        RSI below this = oversold for BUY signals. Default 25.

    rsi_overbought : float
        RSI above this = overbought for SELL signals. Default 75.

    stoch_oversold : float
        Stochastic %K below this = oversold. Default 15.

    stoch_overbought : float
        Stochastic %K above this = overbought. Default 85.

    vwap_dev_threshold : float
        VWAP deviation (in ATR units) above this earns VWAP points. Default 1.5.

    volume_ratio_threshold : float
        Volume / avg_volume ratio above this earns volume points. Default 1.5.

    hurst_mr_threshold : float
        Hurst exponent below this confirms mean-reverting regime. Default 0.45.
    """

    def __init__(
        self,
        threshold_valid:          int   = 6,
        threshold_aplus:          int   = 9,
        z_score_threshold:        float = 2.0,
        z_score_strong:           float = 2.5,
        rsi_oversold:             float = 25.0,
        rsi_overbought:           float = 75.0,
        stoch_oversold:           float = 15.0,
        stoch_overbought:         float = 85.0,
        vwap_dev_threshold:       float = 1.5,
        volume_ratio_threshold:   float = 1.5,
        hurst_mr_threshold:       float = 0.45,
    ) -> None:
        self.threshold_valid        = threshold_valid
        self.threshold_aplus        = threshold_aplus
        self.z_score_threshold      = z_score_threshold
        self.z_score_strong         = z_score_strong
        self.rsi_oversold           = rsi_oversold
        self.rsi_overbought         = rsi_overbought
        self.stoch_oversold         = stoch_oversold
        self.stoch_overbought       = stoch_overbought
        self.vwap_dev_threshold     = vwap_dev_threshold
        self.volume_ratio_threshold = volume_ratio_threshold
        self.hurst_mr_threshold     = hurst_mr_threshold

        logger.info(
            "ConfluenceScorer init | threshold=%d (A+=%d) | z=%.1f | rsi=%.0f/%.0f",
            threshold_valid, threshold_aplus,
            z_score_threshold, rsi_oversold, rsi_overbought,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def score(
        self,
        direction:    str,                       # "buy" or "sell"
        # ── Quantitative signals ──────────────────
        z_score:      Optional[float] = None,
        rsi:          Optional[float] = None,
        bb_position:  Optional[str]   = None,    # "above_upper", "below_lower", or None
        vwap_dev:     Optional[float] = None,    # deviation in ATR units (positive/negative)
        stoch_k:      Optional[float] = None,
        # ── LSL signal ────────────────────────────
        lsl_signal:   Optional[LSLSignal] = None,
        # ── SMC signals ───────────────────────────
        bos_choch:    bool = False,
        order_block:  bool = False,
        # ── Context signals ───────────────────────
        htf_aligned:  bool = False,              # True if HTF trend matches direction
        volume_ratio: Optional[float] = None,    # current_vol / avg_vol
        hurst:        Optional[float] = None,    # Hurst exponent
        symbol:       str = "",
        timeframe:    str = "",
    ) -> ConfluenceResult:
        """
        Evaluate all signals and return a ConfluenceResult.

        Pass whatever signals are available — None values are simply skipped.
        Direction is used to validate that signals agree with the proposed trade.

        Parameters
        ----------
        direction   : "buy" or "sell" — the proposed trade direction
        z_score     : Current Z-score of price vs rolling mean
        rsi         : RSI value (0–100)
        bb_position : "above_upper" (overbought) / "below_lower" (oversold) / None
        vwap_dev    : VWAP deviation in ATR units. Negative = below VWAP.
        stoch_k     : Stochastic %K value (0–100)
        lsl_signal  : Confirmed LSLSignal or None
        bos_choch   : True if a Break of Structure or Change of Character detected
        order_block : True if price is at a mapped Order Block in signal direction
        htf_aligned : True if higher timeframe trend matches the proposed direction
        volume_ratio: current_volume / average_volume (>1 = above average)
        hurst       : Hurst exponent estimate (< 0.5 = mean-reverting)
        symbol      : Instrument name (for logging)
        timeframe   : Timeframe (for logging)

        Returns
        -------
        ConfluenceResult with full score breakdown and entry decision.
        """
        direction = direction.lower().strip()
        if direction not in ("buy", "sell"):
            raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

        bd = ScoreBreakdown()

        # ── Z-Score ───────────────────────────────────────────────────────────
        if z_score is not None:
            z_abs = abs(z_score)
            z_direction_ok = (direction == "buy" and z_score < 0) or \
                             (direction == "sell" and z_score > 0)
            if z_abs >= self.z_score_threshold and z_direction_ok:
                bd.z_score_points = 2
                if z_abs >= self.z_score_strong:
                    bd.z_score_points += 1   # Bonus +1 for very extreme deviation

        # ── RSI ───────────────────────────────────────────────────────────────
        if rsi is not None:
            rsi_ok = (direction == "buy"  and rsi < self.rsi_oversold) or \
                     (direction == "sell" and rsi > self.rsi_overbought)
            if rsi_ok:
                bd.rsi_points = 2

        # ── Bollinger Bands ───────────────────────────────────────────────────
        if bb_position is not None:
            bb_ok = (direction == "buy"  and bb_position == "below_lower") or \
                    (direction == "sell" and bb_position == "above_upper")
            if bb_ok:
                bd.bb_points = 1

        # ── VWAP Deviation ────────────────────────────────────────────────────
        if vwap_dev is not None:
            vwap_abs = abs(vwap_dev)
            vwap_dir_ok = (direction == "buy"  and vwap_dev < 0) or \
                          (direction == "sell" and vwap_dev > 0)
            if vwap_abs >= self.vwap_dev_threshold and vwap_dir_ok:
                bd.vwap_points = 1

        # ── Stochastic ────────────────────────────────────────────────────────
        if stoch_k is not None:
            stoch_ok = (direction == "buy"  and stoch_k < self.stoch_oversold) or \
                       (direction == "sell" and stoch_k > self.stoch_overbought)
            if stoch_ok:
                bd.stoch_points = 1

        # ── LSL Signal ────────────────────────────────────────────────────────
        if lsl_signal is not None and lsl_signal.is_confirmed:
            # Validate LSL direction matches trade direction
            lsl_dir_ok = (
                (direction == "buy"  and lsl_signal.direction == GrabDirection.BUY)  or
                (direction == "sell" and lsl_signal.direction == GrabDirection.SELL)
            )
            if lsl_dir_ok:
                bd.lsl_points = lsl_signal.confluence_points   # 2 or 3 from LSLSignal

        # ── BOS / CHoCH ───────────────────────────────────────────────────────
        if bos_choch:
            bd.bos_choch_points = 1

        # ── Order Block ───────────────────────────────────────────────────────
        if order_block:
            bd.order_block_points = 2

        # ── HTF Trend Alignment ───────────────────────────────────────────────
        if htf_aligned:
            bd.htf_points = 1

        # ── Volume Spike ──────────────────────────────────────────────────────
        if volume_ratio is not None and volume_ratio >= self.volume_ratio_threshold:
            bd.volume_points = 1

        # ── Hurst Exponent (Mean-Reverting Regime) ────────────────────────────
        if hurst is not None and hurst < self.hurst_mr_threshold:
            bd.hurst_points = 1

        # ── Build Result ──────────────────────────────────────────────────────
        result = ConfluenceResult(
            direction        = direction,
            breakdown        = bd,
            symbol           = symbol,
            timeframe        = timeframe,
            threshold_valid  = self.threshold_valid,
            threshold_aplus  = self.threshold_aplus,
        )

        log_fn = logger.info if result.is_valid_entry else logger.debug
        log_fn(
            "Confluence [%s %s] | score=%d (%s) | %s | entry=%s",
            symbol, direction.upper(),
            result.score, result.quality_label,
            bd.summary_line(),
            "✅ VALID" if result.is_valid_entry else "❌ SKIP",
        )

        return result

    def minimum_required(self) -> dict[str, int]:
        """Return the minimum signal requirements as a dict (for docs/UI display)."""
        return {
            "threshold_valid":  self.threshold_valid,
            "threshold_aplus":  self.threshold_aplus,
            "z_score_min":      self.z_score_threshold,
            "rsi_oversold":     self.rsi_oversold,
            "rsi_overbought":   self.rsi_overbought,
            "stoch_oversold":   self.stoch_oversold,
            "stoch_overbought": self.stoch_overbought,
            "vwap_dev_min":     self.vwap_dev_threshold,
            "volume_ratio_min": self.volume_ratio_threshold,
            "hurst_max":        self.hurst_mr_threshold,
        }
