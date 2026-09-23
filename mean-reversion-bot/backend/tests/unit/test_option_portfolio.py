import copy

import pytest

from app.institutional.derivatives import OptionRequest, price_option
from app.institutional.option_portfolio import GREEKS, OptionPortfolioRequest, option_portfolio
from app.institutional.service import analyze


def payload():
    return {"currency": "USD", "positions": [
        {"position_id": "long", "underlying": "SYNTHETIC", "currency": "USD", "contracts": 2,
         "multiplier": 100, "option": {"kind": "call", "spot": 100, "strike": 105,
         "years": .5, "volatility": .25, "rate": .04, "dividend_yield": .01}}],
        "scenarios": [{"name": "unchanged", "shocks": {"SYNTHETIC": {}}}]}


def run(data):
    return option_portfolio(OptionPortfolioRequest.model_validate(data))


def test_signed_scaling_zero_shock_and_offsetting_positions():
    data = payload()
    unit = price_option(OptionRequest(**data["positions"][0]["option"]))
    result = run(data)
    assert result["base_value"] == pytest.approx(200 * unit["price"])
    for key in GREEKS:
        assert result["by_underlying"]["SYNTHETIC"][key] == pytest.approx(200 * unit[key])
    assert result["scenarios"][0]["pnl"] == 0
    data["positions"].append(copy.deepcopy(data["positions"][0]) | {"position_id": "short", "contracts": -2})
    result = run(data)
    assert result["base_value"] == 0
    assert result["gross_option_value"] == pytest.approx(400 * unit["price"])
    assert all(value == 0 for value in result["by_underlying"]["SYNTHETIC"].values())


def test_combined_scenario_fully_reprices_short_position():
    data = payload()
    data["positions"][0]["contracts"] = -3
    data["scenarios"] = [{"name": "stress", "elapsed_days": 10, "shocks": {
        "SYNTHETIC": {"spot_return": -.2, "volatility_change": .1, "rate_change": -.01,
                      "dividend_yield_change": .02}}}]
    result = run(data)
    expected = price_option(OptionRequest(kind="call", spot=80, strike=105,
        years=.5 - 10/365, volatility=.35, rate=.03, dividend_yield=.03))
    stress = result["scenarios"][0]
    assert stress["value"] == pytest.approx(-300 * expected["price"])
    assert stress["pnl"] == pytest.approx(stress["value"] - result["base_value"])
    assert stress["positions"][0]["delta"] == pytest.approx(-300 * expected["delta"])


def test_distinct_underlying_greeks_remain_separate():
    data = payload()
    data["positions"].append(copy.deepcopy(data["positions"][0]) | {"position_id": "other", "underlying": "OTHER"})
    data["scenarios"][0]["shocks"]["OTHER"] = {}
    result = run(data)
    assert set(result["by_underlying"]) == {"SYNTHETIC", "OTHER"}
    assert "delta" not in result
    assert result["base_value"] == pytest.approx(sum(r["value"] for r in result["positions"]))


@pytest.mark.parametrize("change", [
    {"spot_return": -1}, {"volatility_change": -.25}, {"rate_change": 1},
    {"dividend_yield_change": 1}, {"spot_return": float("nan")},
])
def test_invalid_transformed_market_inputs_rejected(change):
    data = payload()
    data["scenarios"][0]["shocks"]["SYNTHETIC"] = change
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("days", [182.5, 183])
def test_expiry_boundary_and_beyond_rejected(days):
    data = payload()
    data["scenarios"][0]["elapsed_days"] = days
    with pytest.raises(ValueError, match="strictly before"):
        run(data)


@pytest.mark.parametrize("case,match", [("currency", "currency"), ("spot", "same spot"),
    ("id", "IDs"), ("scenario", "names"), ("missing", "exactly all"), ("extra", "exactly all")])
def test_inconsistent_portfolio_rejected(case, match):
    data = payload()
    if case == "currency":
        data["positions"][0]["currency"] = "EUR"
    elif case in ("spot", "id"):
        other = copy.deepcopy(data["positions"][0])
        if case == "spot":
            other["position_id"] = "second"
            other["option"]["spot"] = 101
        data["positions"].append(other)
    elif case == "scenario":
        data["scenarios"].append(copy.deepcopy(data["scenarios"][0]))
    else:
        data["scenarios"][0]["shocks"]["OTHER"] = {}
        if case == "missing":
            del data["scenarios"][0]["shocks"]["SYNTHETIC"]
    with pytest.raises(ValueError, match=match):
        run(data)


def test_report_reproducibility_and_input_provenance():
    report = analyze("option-portfolio", payload())
    assert report == analyze("option-portfolio", payload())
    assert report["live_authorized"] is False
    changed = payload()
    changed["positions"][0]["contracts"] = -2
    assert analyze("option-portfolio", changed)["report_id"] != report["report_id"]
