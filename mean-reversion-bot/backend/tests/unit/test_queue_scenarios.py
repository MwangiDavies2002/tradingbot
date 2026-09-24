from decimal import Decimal

import pytest

from app.institutional.order_lifecycle import LifecycleRequest, simulate_lifecycle
from app.institutional.auto_quoting import AutoQuoteRequest, simulate_auto_quotes


def submit(key="a", queue="2", price="100"):
    return dict(kind="submit", at_ms=0, order_id=key, side="buy", price=price, quantity="2", queue_ahead_quantity=queue)


def trade(time, quantity="1", price="99"):
    return dict(kind="trade", at_ms=time, aggressor="sell", price=price, quantity=quantity)


def run(events, **changes):
    result = simulate_lifecycle(LifecycleRequest.model_validate(dict(inventory_limit="10", initial_mark="100",
        final_mark="100", end_ms=100, events=events) | changes))
    for allocation in result["trade_allocations"]:
        assert Decimal(allocation["scenario_budget"]) == sum(Decimal(allocation[key]) for key in
            ("queue_consumed", "filled_quantity", "unused_budget"))
    for order in result["orders"]:
        assert Decimal(order["queue_ahead_initial"]) == Decimal(order["queue_ahead_remaining"]) + Decimal(order["queue_consumed"])
    return result


def test_queue_depletes_before_fill_and_does_not_change_cash_or_inventory():
    result = run([submit(), trade(1), trade(2), trade(3)], fee_bps="10")
    assert [fill["at_ms"] for fill in result["fills"]] == [3]
    assert result["queue_quantity_consumed"] == "2"
    assert result["cash_change"] == "-100.1"
    assert result["inventory_path"][2]["inventory"] == "0"
    assert result["client_reservations"]["buy"] == "1"


def test_one_print_budget_shared_across_queue_hurdles_and_own_orders():
    result = run([submit("a", "1"), submit("b", "2"), trade(1, "10")], fill_fraction="0.5")
    assert result["queue_quantity_consumed"] == "3"
    assert sum(Decimal(f["quantity"]) for f in result["fills"]) == 2
    assert result["orders"][1]["filled"] == "0"
    assert result["orders"][1]["queue_ahead_remaining"] == "0"


def test_price_priority_before_time_and_incremental_hurdles():
    result = run([submit("low", "1", "99"), submit("high", "1", "100"), trade(1, "2")])
    assert [q["order_id"] for q in result["queue_depletions"]] == ["high"]
    assert result["fills"][0]["order_id"] == "high"
    assert result["orders"][0]["queue_ahead_remaining"] == "1"


def test_inactive_non_crossing_and_halted_orders_do_not_deplete():
    result = run([submit(), trade(1), trade(10, price="101"),
                  dict(kind="venue", at_ms=11, online=False), trade(12)], submit_latency_ms=10)
    assert result["queue_quantity_consumed"] == "0"
    assert result["fills"] == []


def test_cancel_pending_consumes_until_effective_and_then_retires_hurdle():
    result = run([submit(queue="5"), dict(kind="cancel", at_ms=1, order_id="a"), trade(2), trade(6)], cancel_latency_ms=5)
    assert result["queue_quantity_consumed"] == "1"
    assert result["orders"][0]["queue_ahead_remaining"] == "4"
    assert result["ending_reservations"]["buy"] == "0"


def test_disconnect_keeps_queue_progress_at_venue_without_client_fill_ack():
    result = run([submit(queue="1"), dict(kind="connection", at_ms=1, connected=False), trade(2, "2")])
    assert result["queue_quantity_consumed"] == "1"
    assert result["ending_inventory"] == "1"
    assert result["client_inventory"] == "0"
    assert result["client_reservations"]["buy"] == "2"


def test_auto_quotes_get_fresh_hurdle_on_replacement_and_keep_progress():
    request = AutoQuoteRequest.model_validate(dict(inventory_limit="10", initial_mark="100", final_mark="100",
        end_ms=100, tick_size="0.1", quantity_step="1", order_size="2", queue_ahead_quantity="2",
        events=[dict(kind="fair", at_ms=0, observed_ms=0, price="100"), trade(1),
                dict(kind="fair", at_ms=2, observed_ms=2, price="100"),
                dict(kind="fair", at_ms=3, observed_ms=3, price="101"),
                dict(kind="fair", at_ms=4, observed_ms=4, price="101")]))
    result = simulate_auto_quotes(request)
    assert len(result["orders"]) == 4
    assert result["orders"][0]["queue_ahead_remaining"] == "1"
    assert result["orders"][2]["queue_ahead_remaining"] == "2"
    assert result["quote_decisions"][1]["actions"]["buy"] == "keep"


def test_negative_queue_rejected_and_default_zero_keeps_immediate_fill():
    with pytest.raises(ValueError):
        run([submit(queue="-1")])
    event = submit()
    del event["queue_ahead_quantity"]
    result = run([event, trade(1)])
    assert result["queue_quantity_consumed"] == "0"
    assert result["fills"][0]["quantity"] == "1"
