import pytest

from app.institutional.execution import CostRequest, RouteRequest, ScheduleRequest, estimate_cost, route, schedule


def venue(name, ask, size=10, fee=0):
    return {"book": {"venue": name, "symbol": "TEST", "currency": "USD", "event_ms": 100,
                     "received_ms": 110, "sequence": 1, "bids": [{"price": 99, "size": size}],
                     "asks": [{"price": ask, "size": size}]}, "fee_bps": fee}


def test_router_uses_net_price_and_conserves_size():
    result = route(RouteRequest(venues=[venue("expensive_fee", 100, fee=100), venue("B", 100.5)],
                                side="buy", quantity=25, arrival_price=100, as_of_ms=120))
    assert result["fills"][0]["venue"] == "B"
    assert result["filled_quantity"] == 20
    assert result["unfilled_quantity"] == 5
    assert result["implementation_shortfall"] == 15
    assert not result["live_authorized"]


def test_sell_cost_sign_and_limit():
    result = route(RouteRequest(venues=[venue("A", 101)], side="sell", quantity=5,
                                arrival_price=100, as_of_ms=120))
    assert result["arrival_slippage"] == 5
    blocked = route(RouteRequest(venues=[venue("A", 101)], side="sell", quantity=5,
                                 arrival_price=100, as_of_ms=120, limit_price=100))
    assert blocked["filled_quantity"] == 0
    assert blocked["vwap"] is None
    assert blocked["unfilled_quantity"] == 5


def test_stale_and_mixed_currency_venues_rejected():
    with pytest.raises(ValueError, match="Stale"):
        route(RouteRequest(venues=[venue("A", 101)], side="buy", quantity=1,
                           arrival_price=100, as_of_ms=2000))
    other = venue("B", 101)
    other["book"]["currency"] = "EUR"
    with pytest.raises(ValueError, match="currency"):
        route(RouteRequest(venues=[venue("A", 101), other], side="buy", quantity=1,
                           arrival_price=100, as_of_ms=120))


@pytest.mark.parametrize("method,volumes,expected", [
    ("twap", [], [25, 25, 25, 25]), ("vwap", [1, 2, 0, 1], [25, 50, 0, 25]),
    ("participation", [100, 200, 0, 100], [10, 20, 0, 10]),
])
def test_schedules(method, volumes, expected):
    result = schedule(ScheduleRequest(method=method, quantity=100, start_ms=0,
                                      interval_ms=1000, buckets=4, volumes=volumes))
    assert [c["quantity"] for c in result["children"]] == expected
    assert sum(expected) + result["unallocated_quantity"] == 100


def test_cost_components_are_explicit():
    result = estimate_cost(CostRequest(notional=10000, spread_bps=10, fee_bps=2, slippage_bps=3,
                                       daily_volatility=.02, daily_volume_notional=1000000,
                                       impact_coefficient=.5, annual_financing_rate=.0365, holding_days=10))
    assert result["components"] == pytest.approx({"half_spread": 5, "fees": 2, "slippage": 3,
                                                  "impact": 10, "financing": 10})
    assert result["total"] == pytest.approx(30)
