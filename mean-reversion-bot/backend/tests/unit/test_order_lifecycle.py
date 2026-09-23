from decimal import Decimal

import pytest

from app.institutional.order_lifecycle import LifecycleRequest, simulate_lifecycle


def submit(key, time=0, quantity="2", side="buy", price="99"):
    return dict(kind="submit", at_ms=time, order_id=key, side=side, price=price, quantity=quantity)


def cancel(key, time):
    return dict(kind="cancel", at_ms=time, order_id=key)


def trade(time, quantity="1", aggressor="sell", price="98"):
    return dict(kind="trade", at_ms=time, aggressor=aggressor, price=price, quantity=quantity)


def run(events, **changes):
    result = simulate_lifecycle(LifecycleRequest.model_validate(dict(inventory_limit="3", initial_mark="100",
        final_mark="100", end_ms=100, events=events) | changes))
    limit = Decimal(changes.get("inventory_limit", "3"))
    for row in result["inventory_path"]:
        assert Decimal(row["maximum_inventory"]) <= limit
        assert Decimal(row["minimum_inventory"]) >= -limit
    for order in result["orders"]:
        assert Decimal(order["filled"]) + Decimal(order["remaining"]) == Decimal(order["quantity"])
    return result


def test_pending_submission_reserves_capacity_and_cannot_fill_early():
    result = run([submit("a"), submit("b", 1), trade(9), trade(10)], submit_latency_ms=10)
    assert result["orders"][1]["status"] == "rejected"
    assert [f["at_ms"] for f in result["fills"]] == [10]
    assert result["ending_reservations"]["buy"] == "1"


def test_pending_cancel_can_fill_then_releases_only_unfilled_quantity():
    result = run([submit("a"), cancel("a", 10), submit("b", 11), trade(19),
                  trade(20), submit("c", 21)], cancel_latency_ms=10)
    assert result["orders"][0]["status"] == "canceled"
    assert result["orders"][0]["filled"] == "1"
    assert result["orders"][1]["status"] == "rejected"
    assert result["orders"][2]["status"] == "open"
    assert len(result["fills"]) == 1


def test_shared_print_budget_price_time_priority_and_fees():
    result = run([submit("low", price="98"), submit("first", price="99"),
                  submit("second", price="99"), trade(1, "6")],
                 inventory_limit="10", fill_fraction="0.5", fee_bps="10")
    assert [f["order_id"] for f in result["fills"]] == ["first", "second"]
    assert [f["quantity"] for f in result["fills"]] == ["2", "1"]
    assert result["ending_inventory"] == "3"
    assert result["fees"] == "0.297"
    assert result["cash_change"] == "-297.297"
    assert result["marked_pnl"] == "2.703"


def test_opposite_orders_do_not_net_reservations():
    result = run([submit("buy", quantity="3"), submit("sell", quantity="3", side="sell", price="101"),
                  submit("extra", quantity="1"), trade(1, "3", "buy", "102")])
    assert result["orders"][2]["status"] == "rejected"
    assert result["ending_inventory"] == "-3"
    assert result["ending_reservations"] == {"buy": "3", "sell": "0"}
    assert result["cash_change"] == "303"


def test_cancel_before_activation_and_duplicate_cancel():
    result = run([submit("a"), cancel("a", 1), cancel("a", 2), trade(10)],
                 submit_latency_ms=10, cancel_latency_ms=1)
    assert result["fills"] == []
    assert result["orders"][0]["cancel_effective_ms"] == 10
    assert result["orders"][0]["status"] == "canceled"


def test_terminal_pending_cancels_keep_reservations_until_effective():
    events = [submit("a"), cancel("a", 95)]
    pending = run(events, cancel_latency_ms=10)
    assert pending["ending_reservations"]["buy"] == "2"
    complete = run(events, cancel_latency_ms=10, end_ms=105)
    assert complete["ending_reservations"]["buy"] == "0"


def test_full_fill_wins_cancel_race_and_no_later_release():
    result = run([submit("a"), cancel("a", 1), trade(2, "2"), cancel("a", 3)], cancel_latency_ms=10)
    assert result["orders"][0]["status"] == "filled"
    assert not any(row["event"] == "canceled" for row in result["audit"])


@pytest.mark.parametrize("events,changes", [
    ([submit("a"), submit("a")], {}), ([cancel("missing", 0)], {}),
    ([submit("a", 2), trade(1)], {}), ([submit("a", 101)], {}),
    ([submit("a")], {"initial_inventory": "4"}),
    ([submit("a")], {"fill_fraction": "1.1"}),
])
def test_invalid_event_scenarios_rejected(events, changes):
    with pytest.raises(ValueError):
        run(events, **changes)
