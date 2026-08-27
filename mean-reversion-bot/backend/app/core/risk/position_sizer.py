"""
position_sizer.py
────────────────────────────────────────────────────────────────────────────────
Position Sizer — ATR-Based Risk Management
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Calculates the correct position size for every trade so that the maximum
    loss if the stop loss is hit equals a fixed percentage of account equity.

    The formula:
        risk_amount = account_balance × risk_pct
        pip_risk    = |entry_price - stop_loss|
        position    = risk_amount / pip_risk

    For Deriv specifically:
        Multipliers product:  stake = risk_amount / multiplier  (defined risk)
        Rise/Fall contracts:  stake = risk_amount directly
        Vanilla options:      calculated from delta

    ATR-based stop loss:
        sl = entry ± (atr × sl_multiplier)
        Default sl_multiplier = 1.5 (SL placed 1.5 ATR from entry)

    The position sizer also applies the confluence score multiplier:
        A+ setup (score ≥ 9):  1.5× base size (but never exceeds max_risk_pct)
        Standard setup:        1.0× base size

    Hard limits (NEVER overridden):
        - Max risk per trade:  max_risk_pct of equity (default 2%)
        - Min position:        min_stake (Deriv minimum)
        - Max position:        max_stake (hard cap)

USAGE:
    from app.core.risk.position_sizer import PositionSizer, TradeSpec

    sizer  = PositionSizer(account_balance=500.0, risk_pct=0.01)
    result = sizer.calculate(
        entry=1948.50, stop_loss=1946.00, atr=1.5,
        confluence_mult=1.5, product="multiplier", multiplier=100
    )
    print(result.stake, result.risk_amount, result.rr_ratio)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SizeResult:
    stake:            float    # Amount to stake in Deriv (USD)
    risk_amount:      float    # Max loss if SL hit (USD)
    risk_pct:         float    # Risk as % of equity
    pip_risk:         float    # |entry - stop_loss|
    stop_loss:        float    # Computed or provided SL price
    take_profit:      float    # Computed TP price
    rr_ratio:         float    # Risk:Reward ratio
    atr_used:         float
    confluence_mult:  float

    @property
    def is_valid(self) -> bool:
        """True if all values are positive and within safe ranges."""
        return (
            self.stake > 0 and
            self.risk_amount > 0 and
            self.rr_ratio >= 1.0 and
            self.pip_risk > 0
        )

    @property
    def meets_minimum_rr(self) -> bool:
        """Minimum 1:1.5 RR required. Below this → no trade."""
        return self.rr_ratio >= 1.5

    def __repr__(self) -> str:
        return (
            f"SizeResult(stake=${self.stake:.2f} | "
            f"risk=${self.risk_amount:.2f} ({self.risk_pct*100:.1f}%) | "
            f"SL={self.stop_loss:.5f} | TP={self.take_profit:.5f} | "
            f"RR=1:{self.rr_ratio:.2f} | valid={self.is_valid})"
        )


class PositionSizer:
    """
    ATR-based position sizer with hard risk limits.

    Parameters
    ----------
    account_balance : float  Current account equity in USD.
    risk_pct        : float  Risk per trade as decimal. Default 0.01 (1%).
    max_risk_pct    : float  Hard maximum. Default 0.02 (2%).
    sl_atr_mult     : float  Stop loss distance = ATR × this. Default 1.5.
    tp_rr           : float  Take profit RR ratio (primary). Default 2.0.
    min_stake       : float  Deriv minimum stake. Default 1.0.
    max_stake       : float  Hard stake cap. Default 100.0.
    """

    def __init__(
        self,
        account_balance: float = 100.0,
        risk_pct:        float = 0.01,
        max_risk_pct:    float = 0.02,
        sl_atr_mult:     float = 1.5,
        tp_rr:           float = 2.0,
        min_stake:       float = 1.0,
        max_stake:       float = 100.0,
    ) -> None:
        self.account_balance = account_balance
        self.risk_pct        = risk_pct
        self.max_risk_pct    = max_risk_pct
        self.sl_atr_mult     = sl_atr_mult
        self.tp_rr           = tp_rr
        self.min_stake       = min_stake
        self.max_stake       = max_stake

    def update_balance(self, new_balance: float) -> None:
        """Call after each trade close to keep sizing current."""
        self.account_balance = new_balance
        logger.debug("PositionSizer balance updated: $%.2f", new_balance)

    def calculate(
        self,
        entry:            float,
        atr:              float,
        direction:        str,              # "buy" or "sell"
        stop_loss:        Optional[float] = None,   # If None, computed from ATR
        take_profit:      Optional[float] = None,   # If None, computed from RR
        confluence_mult:  float = 1.0,      # 1.0 standard, 1.5 for A+ setups
        product:          str   = "multiplier",     # "multiplier", "rise_fall", "vanilla"
        multiplier:       int   = 100,      # Deriv multiplier (if product=multiplier)
    ) -> SizeResult:
        """
        Calculate position size and SL/TP for a trade.

        Parameters
        ----------
        entry           : float  Entry price
        atr             : float  Current ATR (for SL distance)
        direction       : str    'buy' or 'sell'
        stop_loss       : float  Explicit SL price. Auto-computed if None.
        take_profit     : float  Explicit TP price. Auto-computed if None.
        confluence_mult : float  Multiplier from ConfluenceResult (1.0 or 1.5)
        product         : str    Deriv product type
        multiplier      : int    Deriv contract multiplier (Multipliers product)

        Returns
        -------
        SizeResult with all trade parameters computed.
        """
        # ── Compute SL ───────────────────────────────────────────────────────
        sl_distance = atr * self.sl_atr_mult
        if stop_loss is None:
            if direction == "buy":
                stop_loss = entry - sl_distance
            else:
                stop_loss = entry + sl_distance

        pip_risk = abs(entry - stop_loss)
        if pip_risk <= 0:
            pip_risk = sl_distance   # Safety fallback

        # ── Compute TP ───────────────────────────────────────────────────────
        if take_profit is None:
            tp_distance = pip_risk * self.tp_rr
            if direction == "buy":
                take_profit = entry + tp_distance
            else:
                take_profit = entry - tp_distance

        tp_distance_actual = abs(entry - take_profit)
        rr_ratio           = round(tp_distance_actual / pip_risk, 2) if pip_risk > 0 else 0.0

        # ── Risk amount ───────────────────────────────────────────────────────
        base_risk   = self.account_balance * self.risk_pct
        # Apply confluence multiplier but never exceed hard max
        adjusted_risk = base_risk * min(confluence_mult, 1.5)
        max_risk      = self.account_balance * self.max_risk_pct
        risk_amount   = min(adjusted_risk, max_risk)

        # ── Stake calculation ─────────────────────────────────────────────────
        stake = self._compute_stake(
            risk_amount=risk_amount,
            pip_risk=pip_risk,
            entry=entry,
            product=product,
            multiplier=multiplier,
        )

        # ── Apply hard limits ─────────────────────────────────────────────────
        stake = max(self.min_stake, min(stake, self.max_stake))
        # Recompute actual risk after clamping
        actual_risk_pct = risk_amount / self.account_balance

        result = SizeResult(
            stake           = round(stake, 2),
            risk_amount     = round(risk_amount, 4),
            risk_pct        = round(actual_risk_pct, 6),
            pip_risk        = round(pip_risk, 6),
            stop_loss       = round(stop_loss, 6),
            take_profit     = round(take_profit, 6),
            rr_ratio        = rr_ratio,
            atr_used        = atr,
            confluence_mult = confluence_mult,
        )

        if not result.meets_minimum_rr:
            logger.warning(
                "PositionSizer: RR=%.2f below minimum 1.5 | entry=%.5f SL=%.5f TP=%.5f",
                rr_ratio, entry, stop_loss, take_profit,
            )
        else:
            logger.debug("PositionSizer: %s", result)

        return result

    def _compute_stake(
        self,
        risk_amount: float,
        pip_risk:    float,
        entry:       float,
        product:     str,
        multiplier:  int,
    ) -> float:
        """
        Compute the Deriv stake based on product type.

        Multipliers:  The stake × multiplier gives the notional exposure.
                      P&L per pip = stake × multiplier / entry
                      So: stake = risk_amount × entry / (multiplier × pip_risk)

        Rise/Fall:    The stake IS the max loss (binary-like).
                      stake = risk_amount directly.

        Vanilla:      Approximation: treat like rise/fall for sizing.
        """
        if product == "multiplier":
            # Notional = stake × multiplier
            # P&L per unit price move = (stake × multiplier) / entry
            # Max loss = pip_risk × (stake × multiplier) / entry
            # Solve for stake:
            denominator = (multiplier * pip_risk) / entry
            if denominator > 0:
                return risk_amount / denominator
            return self.min_stake

        if product in ("rise_fall", "vanilla", "digit"):
            # These have defined max loss = stake
            return risk_amount

        # Default: treat as multiplier with multiplier=1
        return risk_amount / max(pip_risk, 1e-8)
