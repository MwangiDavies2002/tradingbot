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
        assert Decimal(row["client_maximum_inventory"]) <= limit
        assert Decimal(row["client_minimum_inventory"]) >= -limit
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


def test_matching_halt_retains_capacity_and_defers_cancel_acknowledgement():
    result = run([submit("a"), dict(kind="venue", at_ms=1, online=False), cancel("a", 2),
                  trade(10), submit("b", 11), dict(kind="venue", at_ms=20, online=True),
                  submit("c", 20)], cancel_latency_ms=5)
    assert result["fills"] == []
    assert result["inventory_path"][3]["reserved_buy"] == "2"
    assert result["orders"][1]["status"] == "rejected"
    assert result["orders"][2]["status"] == "open"
    assert next(a["at_ms"] for a in result["audit"] if a["event"] == "canceled") == 20


def test_venue_rejection_preserves_prior_fills_and_releases_remainder():
    result = run([submit("a"), trade(1), dict(kind="reject", at_ms=2, order_id="a", reason="synthetic venue rule"),
                  trade(3), submit("b", 4)])
    assert result["ending_inventory"] == "1"
    assert result["orders"][0]["status"] == "venue_rejected"
    assert result["orders"][0]["filled"] == "1"
    assert result["orders"][1]["status"] == "open"


def test_halt_at_end_keeps_due_cancels_reserved():
    result = run([submit("a"), dict(kind="venue", at_ms=1, online=False), cancel("a", 2)])
    assert result["venue_online"] is False
    assert result["ending_reservations"]["buy"] == "2"


def test_rejection_after_fill_is_noop_and_unknown_reference_invalid():
    result = run([submit("a"), trade(1, "2"), dict(kind="reject", at_ms=2, order_id="a", reason="late")])
    assert result["orders"][0]["status"] == "filled"
    assert result["audit"][-1]["event"] == "reject_noop"
    with pytest.raises(ValueError, match="earlier submitted"):
        run([dict(kind="reject", at_ms=0, order_id="missing", reason="invalid")])


def test_delayed_sell_fill_does_not_let_client_spend_unconfirmed_buy_capacity():
    result = run([submit("sell", quantity="3", side="sell", price="101"),
                  trade(1, "3", "buy", "102"), submit("too-soon", 2, quantity="4"),
                  submit("after-ack", 11, quantity="4")], fill_ack_latency_ms=10)
    assert result["orders"][1]["status"] == "rejected"
    assert result["orders"][2]["status"] == "open"
    assert result["inventory_path"][1]["inventory"] == "-3"
    assert result["inventory_path"][1]["client_inventory"] == "0"
    assert result["inventory_path"][1]["client_reserved_sell"] == "3"
    assert result["client_inventory"] == "-3"


@pytest.mark.parametrize("terminal", ["cancel", "reject"])
def test_terminal_ack_never_releases_unacknowledged_fills(terminal):
    event = cancel("a", 2) if terminal == "cancel" else dict(kind="reject", at_ms=2, order_id="a", reason="test")
    result = run([submit("a"), trade(1), event, submit("replacement", 3, quantity="3")],
                 fill_ack_latency_ms=20, end_ms=10)
    assert result["ending_reservations"]["buy"] == "0"
    assert result["client_reservations"]["buy"] == "1"
    assert result["orders"][1]["status"] == "rejected"
    assert result["pending_fill_acknowledgements"] == 1
    assert result["fills"][0]["acknowledged"] is False
    assert result["client_inventory"] == "0"


def test_acknowledgements_settle_during_halt_and_reconcile_cash_fees():
    result = run([submit("a"), trade(1), trade(2), dict(kind="venue", at_ms=3, online=False)],
                 fill_ack_latency_ms=10, fee_bps="10", end_ms=12)
    assert result["client_inventory"] == result["ending_inventory"] == "2"
    assert result["client_cash_change"] == result["cash_change"] == "-198.198"
    assert result["client_fees"] == result["fees"] == "0.198"
    assert result["orders"][0]["acknowledged_filled"] == "2"
    assert result["pending_fill_acknowledgements"] == 0
    assert [a["at_ms"] for a in result["audit"] if a["event"] == "fill_acknowledged"] == [11, 12]


def test_unknown_opposite_fills_do_not_net_and_partial_ack_at_end():
    result = run([submit("buy"), submit("sell", side="sell", price="101"),
                  trade(1), trade(2, aggressor="buy", price="102")], fill_ack_latency_ms=10, end_ms=11)
    assert result["ending_inventory"] == "0"
    assert result["client_inventory"] == "1"
    assert result["unacknowledged_quantity"] == {"buy": "0", "sell": "1"}
    assert result["client_reservations"] == {"buy": "1", "sell": "2"}
    assert result["pending_fill_acknowledgements"] == 1


def test_zero_delay_preserves_immediate_client_ledger():
    result = run([submit("a"), trade(1)], fee_bps="1")
    assert result["client_inventory"] == result["ending_inventory"]
    assert result["client_reservations"] == result["ending_reservations"]
    assert result["client_cash_change"] == result["cash_change"]
    assert result["fills"][0]["ack_at_ms"] == 1


def connection(time, connected):
    return dict(kind="connection", at_ms=time, connected=connected)


def test_disconnect_does_not_stop_matching_and_buffers_fill_cash():
    result = run([submit("a"), connection(1, False), trade(2)], fee_bps="10")
    assert result["ending_inventory"] == "1"
    assert result["client_inventory"] == "0"
    assert result["client_cash_change"] == "0"
    assert result["client_reservations"]["buy"] == "2"
    assert result["fills"][0]["delivered_at_ms"] is None
    assert result["client_connected"] is False


def test_reconnect_delivers_due_fills_once_and_retains_future_ack():
    result = run([submit("a"), connection(1, False), trade(2), trade(9),
                  connection(12, True), connection(13, True)], fill_ack_latency_ms=10, end_ms=13)
    assert result["client_inventory"] == "1"
    assert result["fills"][0]["delivered_at_ms"] == 12
    assert result["fills"][1]["delivered_at_ms"] is None
    assert len([a for a in result["audit"] if a["event"] == "fill_acknowledged"]) == 1


def test_queued_cancel_latency_starts_on_reconnect_and_submit_is_rejected():
    result = run([submit("a"), connection(1, False), cancel("a", 2), cancel("a", 3),
                  submit("blocked", 4), connection(10, True), trade(14), trade(15)], cancel_latency_ms=5)
    assert result["orders"][0]["cancel_effective_ms"] == 15
    assert [f["at_ms"] for f in result["fills"]] == [14]
    assert result["orders"][1]["status"] == "rejected"
    assert len([a for a in result["audit"] if a["event"] == "queued_cancel_sent"]) == 1


@pytest.mark.parametrize("terminal", ["cancel", "reject"])
def test_unreceived_terminal_confirmation_keeps_remaining_reserved(terminal):
    events = [submit("a"), cancel("a", 0), connection(1, False), trade(2)] if terminal == "cancel" else [
        submit("a"), connection(1, False), trade(2), dict(kind="reject", at_ms=3, order_id="a", reason="test")]
    before = run(events, cancel_latency_ms=5, end_ms=6)
    assert before["ending_reservations"]["buy"] == "0"
    assert before["client_reservations"]["buy"] == "2"
    assert before["pending_terminal_acknowledgements"] == 1
    after = run(events + [connection(7, True)], cancel_latency_ms=5)
    assert after["client_inventory"] == "1"
    assert after["client_reservations"]["buy"] == "0"
    assert after["pending_terminal_acknowledgements"] == 0
    assert after["client_cash_change"] == after["cash_change"]


def test_full_fill_makes_queued_cancel_obsolete_on_recovery():
    result = run([submit("a"), connection(1, False), cancel("a", 2), trade(3, "2"), connection(4, True)])
    assert result["orders"][0]["status"] == "filled"
    assert result["queued_cancellations"] == 0
    assert result["client_inventory"] == "2"
    assert any(a["event"] == "queued_cancel_obsolete" for a in result["audit"])
