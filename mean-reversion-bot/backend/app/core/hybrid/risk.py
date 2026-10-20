"""Pure linear-instrument risk formulas shared by every campaign operation."""
import math


class CampaignRiskEngine:
    @staticmethod
    def open_risk(entry, stop, sign, quantity, spec, exit_slippage_pct=0, half_spread=0):
        # Profitable stops do not offset other tranche losses.
        distance = max(0, sign * (entry - stop)) + stop * exit_slippage_pct + half_spread
        return (distance * spec.point_value + spec.commission) * quantity

    @staticmethod
    def entry_unit_risk(price, stop, spec, exit_slippage_pct=0, half_spread=0):
        return (abs(price - stop) + stop * exit_slippage_pct + half_spread) * spec.point_value + 2 * spec.commission

    @staticmethod
    def permits(current_open_risk, proposed_risk, realized_pnl, maximum_risk):
        values = (current_open_risk, proposed_risk, realized_pnl, maximum_risk)
        return (all(math.isfinite(v) for v in values)
                and current_open_risk >= 0 and proposed_risk > 0 and maximum_risk > 0
                and current_open_risk + proposed_risk + max(0, -realized_pnl) <= maximum_risk + 1e-9)
