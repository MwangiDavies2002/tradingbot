import math

import numpy as np
import pytest

from app.institutional.risk import AllocationRequest, PortfolioRequest, allocate, portfolio_risk, tail_risk
from app.institutional.derivatives import OptionRequest, price_option
from app.institutional.market_making import MarketMakingRequest, QuoteRequest, quote, simulate_market_making


def test_empirical_tail_fraction_and_zero_loss_floor():
    result = tail_risk(np.array([-10, -5, 0, 10]), .625)
    assert result["var"] == 5
    assert result["expected_shortfall"] == pytest.approx(25 / 3)
    assert tail_risk(np.array([1, 2, 3]), .95)["expected_shortfall"] == 0


def test_hedge_reduces_pnl_risk_but_not_gross_counterparty_exposure():
    data = PortfolioRequest(equity=100, currency="USD",
        positions=[{"symbol": "A", "market_value": 100, "counterparty": "X", "factor_betas": {"market": 1}},
                   {"symbol": "B", "market_value": -100, "counterparty": "X", "factor_betas": {"market": 1}}],
        returns={"A": [.01, -.02] * 20, "B": [.01, -.02] * 20},
        scenarios={"divergence": {"A": -.1, "B": .1}}, factor_limits={"market": .1})
    result = portfolio_risk(data)
    assert result["expected_shortfall"] == 0
    assert result["gross_exposure"] == 200
    assert result["net_exposure"] == 0
    assert result["scenario_pnl"]["divergence"] == -20
    assert not result["limits_passed"]
    assert result["checks"]["factor:market"]
    assert result["correlation"][0][1] == pytest.approx(1)


def test_missing_factor_beta_and_misaligned_returns_are_rejected():
    with pytest.raises(ValueError, match="explicit beta"):
        PortfolioRequest(equity=100, currency="USD", positions=[{"symbol": "A", "market_value": 10, "counterparty": "X"}],
                         returns={"A": [.01] * 20}, factor_limits={"market": 1})
    with pytest.raises(ValueError, match="aligned"):
        allocate(AllocationRequest(returns={"A": [.01] * 20, "B": [.01] * 21}))


def test_allocator_caps_turnover_and_leaves_cash():
    result = allocate(AllocationRequest(returns={"A": [.01, -.01] * 20, "B": [.02, -.02] * 20},
                                        max_weight=.6, max_turnover=.5))
    assert result["weights"] == pytest.approx({"A": .3, "B": .2})
    assert result["cash_weight"] == pytest.approx(.5)
    assert result["turnover_l1"] == pytest.approx(.5)
    flat = allocate(AllocationRequest(returns={"A": [0.] * 20}))
    assert flat["cash_weight"] == 1
    assert flat["zero_variance_assets"] == ["A"]


def test_option_put_call_parity_and_finite_difference_greeks():
    args = dict(spot=100, strike=105, years=.7, volatility=.25, rate=.04, dividend_yield=.01)
    call = price_option(OptionRequest(kind="call", **args))
    put = price_option(OptionRequest(kind="put", **args))
    assert call["price"] - put["price"] == pytest.approx(100 * math.exp(-.01 * .7) - 105 * math.exp(-.04 * .7))
    for kind in ("call", "put"):
        base = price_option(OptionRequest(kind=kind, **args))
        def p(**changes):
            return price_option(OptionRequest(kind=kind, **(args | changes)))["price"]
        h = .001
        assert base["delta"] == pytest.approx((p(spot=100+h)-p(spot=100-h))/(2*h), rel=1e-6)
        assert base["gamma"] == pytest.approx((p(spot=100+h)-2*base["price"]+p(spot=100-h))/h**2, rel=1e-4)
        assert base["vega_per_vol_point"] == pytest.approx((p(volatility=.25001)-p(volatility=.24999))/.00002/100, rel=1e-6)
        assert base["rho_per_rate_point"] == pytest.approx((p(rate=.04001)-p(rate=.03999))/.00002/100, rel=1e-6)
        assert base["theta_per_day"] == pytest.approx(-(p(years=.70001)-p(years=.69999))/.00002/365, rel=1e-6)


def test_inventory_skew_and_one_sided_limit():
    def make(inventory):
        return quote(QuoteRequest(fair_price=100, tick_size=.01, inventory=inventory,
                                   inventory_limit=10, order_size=3))
    flat, long = make(0), make(10)
    assert long["reservation_price"] < flat["reservation_price"]
    assert long["bid"] is None
    assert long["bid_size"] == 0
    assert long["ask_size"] == 3
    assert make(-10)["ask"] is None


def test_market_making_uses_previous_quote_and_respects_latency():
    payload = dict(quote_config=dict(fair_price=100, tick_size=.01, inventory=0, inventory_limit=2, order_size=2),
                   start_ms=0, fill_fraction=1,
                   trades=[dict(event_ms=100, received_ms=110, aggressor="sell", price=99, size=100, fair_price=90),
                           dict(event_ms=200, received_ms=210, aggressor="sell", price=80, size=100, fair_price=80)])
    result = simulate_market_making(MarketMakingRequest(**payload))
    assert result["fill_count"] == 1
    assert result["ending_inventory"] == 2
    assert result["fills"][0]["price"] > 99  # Quote from initial fair, not future fair=90.
    assert result["marked_pnl"] < 0
    assert all(abs(p["inventory"]) <= 2 for p in result["inventory_path"])
    delayed = simulate_market_making(MarketMakingRequest(**payload, quote_latency_ms=500))
    assert delayed["fill_count"] == 0
    assert delayed["inactive_quote_events"] == 2
