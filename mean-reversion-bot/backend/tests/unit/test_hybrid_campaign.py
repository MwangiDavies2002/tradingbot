import pytest

from app.core.hybrid.campaign import InstrumentSpec, TradeCampaign, Confirmation
from app.core.hybrid.regime import Regime, RegimeConfig, MarketRegime, completed_bars
from app.core.lsl.lsl_detector import Candle


def campaign(direction="buy", point_value=1, commission=0):
    c = TradeCampaign("test", "TEST", direction, Regime.BULLISH, {},
                      InstrumentSpec("TEST", point_value, 0.01, 0.01, commission=commission), 10000)
    c.setup(0, 100)
    return c


@pytest.mark.parametrize("direction,stop", [("buy", 95), ("sell", 105)])
def test_probe_is_small_and_instrument_aware(direction, stop):
    c = campaign(direction, 10)
    assert c.open_probe("probe", 1, 100, stop)
    assert c.total_quantity == pytest.approx(0.5)
    assert c.current_open_risk == pytest.approx(25)
    assert c.risk_limit == 100


def test_duplicate_probe_and_wrong_stop_are_rejected():
    c = campaign()
    assert not c.open_probe("wrong", 1, 100, 101)
    assert c.open_probe("probe", 1, 100, 95)
    assert not c.open_probe("probe", 1, 100, 95)
    assert len(c.entries) == 1


def test_insufficient_htf_history_is_unknown():
    assert MarketRegime().classify({}).regime == Regime.UNKNOWN


def test_htf_excludes_unfinished_and_gapped_buckets():
    bars = [Candle(i * 300, 100, 101, 99, 100, 1) for i in range(15)]
    assert len(completed_bars(bars, 3600, 300, 4500)) == 1
    assert completed_bars(bars, 3600, 300, 3599) == []
    assert completed_bars(bars[:5] + bars[6:], 3600, 300, 4500) == []


def test_minimum_quantity_never_rounds_risk_up():
    c = campaign(point_value=1e6)
    assert not c.open_probe("probe", 1, 100, 95)
    assert c.total_quantity == 0


def test_commission_consumes_budget_and_net_pnl():
    c = campaign(commission=1)
    assert c.open_probe("probe", 1, 100, 95)
    assert c.current_open_risk + max(0, -c.realized_pnl) <= 25
    assert c.realized_pnl < 0


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_spec_rejected(value):
    with pytest.raises(ValueError):
        InstrumentSpec("TEST", value, .01, .01)


@pytest.mark.parametrize("slope,expected", [(0.2, Regime.BULLISH), (-0.2, Regime.BEARISH), (0, Regime.RANGE)])
def test_regime_on_synthetic_swing_structure(slope, expected):
    import math
    bars = []
    for i in range(100):
        p = 100 + slope * i + 2 * math.sin(i * math.pi / 6)
        bars.append(Candle(i * 3600, p, p + .3, p - .3, p, 1))
    detector = MarketRegime(RegimeConfig(timeframes=(3600,), ema_period=20, swing_lookback=2, range_band_pct=.03))
    assert detector.classify({3600: bars}).regime == expected


def confirm(timestamp=2, direction="buy", event_id="bos", reasons=("BOS_CONFIRMED",)):
    return Confirmation(event_id, timestamp, direction, 8, reasons)


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_risk_budget_bounds_every_add_and_duplicate_confirmation(direction, sign):
    c = campaign(direction)
    assert c.open_probe("probe", 1, 100, 100 - sign * 5)
    for i in range(2, 5):
        assert c.add(confirm(i, direction, str(i)), i, 100 + sign * i, 100 - sign * 5)
        assert c.current_open_risk <= c.risk_limit
    quantity = c.total_quantity
    assert not c.add(confirm(4, direction, "4"), 4, 100 + sign * 4, 100 - sign * 5)
    assert c.total_quantity == quantity
    assert len(c.entries) == 4


def test_add_rejected_when_requested_risk_exceeds_remaining_budget():
    c = campaign()
    c.open_probe("probe", 1, 100, 95, .9)
    assert not c.add(confirm(), 2, 102, 95, .25)
    assert len(c.entries) == 1
    assert c.events[-1]["reason_codes"] == ["CAMPAIGN_RISK_LIMIT"]


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_losing_position_and_pnl_without_confirmation_cannot_add(direction, sign):
    c = campaign(direction)
    c.open_probe("probe", 1, 100, 100 - sign * 5)
    assert not c.add(confirm(2, direction), 2, 100 - sign, 100 - sign * 5)
    assert not c.add(confirm(2, direction, reasons=("POSITIVE_PNL",)), 2, 100 + sign, 100 - sign * 5)
    assert len(c.entries) == 1


def test_released_risk_and_weighted_average_after_add():
    c = campaign()
    c.open_probe("probe", 1, 100, 95, .75)
    assert c.move_stop(2, 103, 99)
    assert c.current_open_risk == 15
    assert c.available_risk == 85
    assert c.add(confirm(3), 3, 104, 99, .5)
    assert c.average_entry == pytest.approx((15 * 100 + 10 * 104) / 25)
    assert c.current_open_risk == 65


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_stop_never_loosens_or_crosses_market(direction, sign):
    c = campaign(direction)
    c.open_probe("probe", 1, 100, 100 - sign * 5)
    before = c.current_open_risk
    assert not c.move_stop(2, 100 + sign * 3, 100 - sign * 6)
    assert c.current_open_risk == before
    assert not c.move_stop(2, 100 + sign * 3, 100 + sign * 4)
    assert c.move_stop(2, 100 + sign * 3, 100 - sign)
    assert c.current_open_risk < before


def test_stale_future_and_wrong_direction_confirmations_are_rejected():
    c = campaign()
    c.open_probe("probe", 1, 100, 95)
    for event in (confirm(1), confirm(4), confirm(2, "sell")):
        assert not c.add(event, 3, 102, 95)
    assert len(c.entries) == 1


def test_context_scoring_is_optional_capped_and_does_not_accumulate():
    from app.core.engine.confluence import ConfluenceScorer
    scorer = ConfluenceScorer()
    base = scorer.score("buy", z_score=-2.2)
    assert base.score == 2
    enriched = scorer.with_hybrid_context(base, ("EMA_PULLBACK", "DEMAND_ZONE"), ("BOS_CONFIRMED",))
    assert enriched.score == 6
    assert base.score == 2
    assert scorer.with_hybrid_context(enriched, ("EMA_PULLBACK", "DEMAND_ZONE"), ("BOS_CONFIRMED",)).score == 6
    with pytest.raises(ValueError):
        scorer.with_hybrid_context(base, ("UNKNOWN_LEVEL",))


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_partial_exit_quantity_fifo_pnl_and_duplicate_target(direction, sign):
    c = campaign(direction, point_value=2)
    assert c.open_probe("probe", 1, 100, 100 - sign * 5)
    assert c.add(confirm(2, direction), 2, 100 + sign * 2, 100 - sign * 5)
    quantity, before = c.total_quantity, c.current_open_risk
    assert c.partial_exit("TP1", 3, 100 + sign * 4, 1, "TP1")
    assert c.total_quantity == pytest.approx(quantity - 1)
    assert c.realized_pnl == pytest.approx(8)
    assert c.current_open_risk < before
    assert c.average_entry == pytest.approx(sum(e.price * e.remaining for e in c.entries) / (quantity - 1))
    assert not c.partial_exit("TP1", 3, 100 + sign * 4, 1, "TP1")
    assert c.realized_pnl == 8
    c.close("end", 4, 100 + sign * 4)
    expected = sum(sign * (100 + sign * 4 - e.price) * e.quantity * 2 for e in c.entries)
    assert c.realized_pnl == pytest.approx(expected)
    assert c.total_quantity == c.current_open_risk == c.unrealized_pnl == 0


def test_exit_commission_reconciles_net_pnl():
    c = campaign(commission=.1)
    c.open_probe("probe", 1, 100, 95)
    quantity = c.total_quantity
    c.partial_exit("TP1", 2, 103, 1)
    c.close("end", 3, 104)
    assert c.realized_pnl == pytest.approx(3 + (quantity - 1) * 4 - 2 * quantity * .1)


def test_invalidation_cancels_orders_closes_and_prevents_further_actions():
    c = campaign()
    c.open_probe("probe", 1, 100, 95)
    c.pending_orders["queued-add"] = {"quantity": 1}
    assert c.invalidate(2, 98)
    assert c.status.value == "INVALIDATED"
    assert c.pending_orders == {}
    assert c.total_quantity == 0
    assert c.realized_pnl == -10
    assert any(e["action"] == "CANCEL" for e in c.events)
    assert not c.invalidate(3, 99)
    assert not c.add(confirm(3), 3, 102, 95)
    assert not c.open_probe("again", 3, 100, 95)


def test_runner_and_partial_minimums():
    c = campaign()
    c.open_probe("probe", 1, 100, 95)
    assert not c.partial_exit("bad", 2, 102, .001)
    assert not c.partial_exit("too-much", 2, 102, 10)
    assert c.partial_exit("TP1", 2, 102, 1)
    assert c.start_runner(3, 103)
    assert c.status.value == c.state.value == "RUNNER"
    assert not c.start_runner(3, 103)


def test_exit_slippage_and_spread_are_reserved_in_risk_sizing():
    c = campaign(point_value=10)
    c.exit_slippage_pct = .001
    c.half_spread = .2
    c.open_probe("probe", 1, 100, 95)
    assert c.total_quantity < .5
    assert c.current_open_risk <= 25
    assert c.current_open_risk == pytest.approx(c.total_quantity * (5 + .095 + .2) * 10)


def test_locked_profit_does_not_offset_new_tranche_risk():
    c = campaign()
    c.open_probe("probe", 1, 100, 95, .5)
    c.move_stop(2, 103, 101)
    assert c.current_open_risk == 0
    assert c.add(confirm(3), 3, 104, 101, .75)
    assert c.current_open_risk == 75
    # The first tranche's $10 locked profit is deliberately not credited.
    assert c.available_risk == 25
    assert not c.add(confirm(4, event_id="second-bos"), 4, 105, 101, .3)


@pytest.mark.parametrize("point_value", [1, 10, 100])
@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_deterministic_risk_sequence_with_friction(point_value, direction, sign):
    c = campaign(direction, point_value, commission=.2)
    c.exit_slippage_pct, c.half_spread = .001, .1
    assert c.open_probe("probe", 1, 100, 100 - sign * 5)
    for i in range(2, 7):
        price = 100 + sign * i
        c.move_stop(i, price, 100 + sign * (i - 2))
        c.add(confirm(i, direction, str(i)), i, price, 100 + sign * (i - 2))
        assert c.current_open_risk + max(0, -c.realized_pnl) <= c.risk_limit + 1e-9
        assert c.maximum_risk_used <= c.risk_limit + 1e-9


def test_identical_evidence_is_not_scored_twice():
    from app.core.engine.confluence import ConfluenceScorer
    scorer = ConfluenceScorer()
    base = scorer.score("buy", order_block=True, bos_choch=True)
    assert scorer.with_hybrid_context(base, ("DEMAND_ZONE",), ("BOS_CONFIRMED",)).score == base.score
