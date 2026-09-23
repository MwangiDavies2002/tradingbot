from decimal import Decimal

import pytest

from app.institutional.instruments import ConversionRequest, InstrumentOrderRequest, InstrumentSpec, convert_currency, validate_instrument_order
from app.institutional.service import analyze


def spec(**changes):
    return dict(instrument_id="synthetic-gold", venue="TEST", venue_symbol="TEST_GOLD",
                revision="1", source="synthetic-test-fixture", product="linear_contract",
                underlying_unit="troy_ounce", quote_currency="USD", contract_size="100",
                tick_size="0.05", quantity_step="0.01", min_quantity="0.01", max_quantity="10",
                min_notional="1", published_ms=50, valid_from_ms=100, valid_until_ms=1000,
                sessions=[dict(open_ms=100, close_ms=500), dict(open_ms=600, close_ms=1000)]) | changes


def order(**changes):
    return dict(instrument=spec(), side="buy", quantity="0.03", price="2000.05",
                as_of_ms=200, reporting_currency="USD") | changes


def fx(**changes):
    return dict(base_currency="USD", quote_currency="KES", bid="129", ask="130",
                event_ms=100, available_ms=110, source="synthetic-test-fixture") | changes


def test_decimal_contract_units_and_notional():
    result = analyze("instrument-order", order())
    assert result["result"]["order_valid"]
    assert result["result"]["underlying_quantity"] == "3"
    assert result["result"]["quote_notional"] == "6000.15"
    assert result["result"]["spot_cash_before_fees"] is None
    assert result["request"]["instrument"]["tick_size"] == "0.05"
    assert len(result["result"]["instrument_hash"]) == 64


@pytest.mark.parametrize("changes,failed", [
    ({"price": "2000.051"}, "price_on_tick"),
    ({"quantity": "0.031"}, "quantity_on_step"),
    ({"quantity": "10.01"}, "quantity_within_bounds"),
    ({"as_of_ms": 500}, "session_open"),
    ({"as_of_ms": 1000}, "metadata_effective"),
    ({"instrument": spec(published_ms=300)}, "metadata_published"),
    ({"instrument": spec(min_notional="10000")}, "minimum_notional"),
])
def test_invalid_orders_report_failed_checks_without_rounding(changes, failed):
    result = validate_instrument_order(InstrumentOrderRequest(**order(**changes)))
    assert not result["order_valid"]
    assert not result["checks"][failed]


@pytest.mark.parametrize("changes", [
    {"tick_size": "NaN"}, {"quantity_step": "0"}, {"max_quantity": "0.001"},
    {"product": "spot"}, {"min_quantity": "0.015"},
    {"sessions": [dict(open_ms=100, close_ms=700), dict(open_ms=600, close_ms=1000)]},
    {"sessions": [dict(open_ms=0, close_ms=500)]}, {"quote_currency": "usd"},
])
def test_inconsistent_metadata_rejected(changes):
    with pytest.raises(ValueError):
        InstrumentSpec(**spec(**changes))


@pytest.mark.parametrize("amount,source,target,expected,side", [
    ("2", "USD", "KES", "258", "bid"),
    ("-2", "USD", "KES", "-260", "ask"),
    ("260", "KES", "USD", "2", "inverse_ask"),
    ("-258", "KES", "USD", "-2", "inverse_bid"),
])
def test_conversion_sign_and_pair_orientation(amount, source, target, expected, side):
    result = convert_currency(ConversionRequest(amount=amount, from_currency=source,
        to_currency=target, as_of_ms=120, fx=fx()))
    assert result["amount"] == expected
    assert result["rate_side"] == side


@pytest.mark.parametrize("quote,now", [(fx(), 109), (fx(), 2000), (fx(base_currency="EUR"), 120)])
def test_unavailable_stale_or_wrong_pair_rejected(quote, now):
    with pytest.raises(ValueError):
        convert_currency(ConversionRequest(amount="1", from_currency="USD", to_currency="KES", as_of_ms=now, fx=quote))


def test_spot_cash_and_reporting_short_exposure():
    result = validate_instrument_order(InstrumentOrderRequest(**order(
        instrument=spec(product="spot", contract_size="1"), side="sell",
        reporting_currency="KES", fx=fx())))
    assert result["spot_cash_before_fees"] == "60.0015"
    assert result["reporting_exposure"]["rate_side"] == "ask"
    assert Decimal(result["reporting_exposure"]["amount"]) == Decimal("-7800.195")


def test_report_replay_and_high_precision_products():
    payload = order(instrument=spec(contract_size="0.000000000001"),
                    price="0.000000000001", quantity="0.000000000001")
    first = analyze("instrument-order", payload)
    assert first == analyze("instrument-order", first["request"])
    assert Decimal(first["result"]["quote_notional"]) == Decimal("1e-36")
