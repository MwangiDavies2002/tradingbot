from copy import deepcopy
from decimal import Decimal

import pytest

from app.institutional.auto_quoting import AutoQuoteRequest, simulate_auto_quotes


def fair(time, price="100", observed=None):
    return dict(kind="fair", at_ms=time, observed_ms=time if observed is None else observed, price=price)


def trade(time, size="1"):
    return dict(kind="trade", at_ms=time, aggressor="sell", price="90", quantity=size)


def run(events, **changes):
    request = AutoQuoteRequest.model_validate(dict(inventory_limit="3", initial_mark="100", final_mark="100",
        tick_size="0.1", quantity_step="0.5", order_size="2", half_spread_bps="10", inventory_skew_bps="10",
        end_ms=100, events=events) | changes)
    result = simulate_auto_quotes(request)
    for row in result["inventory_path"]:
        assert Decimal(row["client_minimum_inventory"]) >= -request.inventory_limit
        assert Decimal(row["client_maximum_inventory"]) <= request.inventory_limit
        assert -request.inventory_limit <= Decimal(row["inventory"]) <= request.inventory_limit
    return result


def test_grid_initial_quote_keep_and_no_decision_from_trades():
    result = run([fair(0), fair(1), trade(2)])
    assert len(result["orders"]) == 2
    assert result["orders"][0]["price"] == "99.9"
    assert result["orders"][1]["price"] == "100.1"
    assert result["quote_decisions"][1]["actions"] == {"buy": "keep", "sell": "keep"}
    assert len(result["quote_decisions"]) == 2


def test_future_fair_and_final_mark_do_not_change_earlier_decisions():
    events = [fair(0), trade(1), fair(2), fair(50)]
    before = run(events, fill_ack_latency_ms=10)
    changed = deepcopy(events)
    changed[-1]["price"] = "200"
    after = run(changed, final_mark="300", fill_ack_latency_ms=10)
    assert before["quote_decisions"][:2] == after["quote_decisions"][:2]
    assert before["fills"] == after["fills"]


def test_unacknowledged_full_fill_is_not_visible_to_controller():
    result = run([fair(0), trade(1, "2"), fair(2), fair(11)], fill_ack_latency_ms=10)
    decisions = result["quote_decisions"]
    assert decisions[1]["client_inventory"] == "0"
    assert decisions[1]["reserved"]["buy"] == "2"
    assert decisions[1]["actions"]["buy"] == "keep"
    assert decisions[2]["client_inventory"] == "2"
    buys = [o for o in result["orders"] if o["side"] == "buy"]
    assert buys[-1]["quantity"] == "1"


def test_changed_quotes_wait_through_delayed_cancellation():
    result = run([fair(0), fair(1, "101"), fair(5, "101"), fair(11, "101")], cancel_latency_ms=10)
    assert len(result["orders"]) == 4
    assert [o["submitted_ms"] for o in result["orders"]] == [0, 0, 11, 11]
    assert result["quote_decisions"][2]["actions"]["buy"] == "cancel_or_wait"


def test_stale_fair_cancels_and_halt_does_not_submit():
    result = run([fair(0), fair(5, observed=0), dict(kind="venue", at_ms=6, online=False),
                  fair(7), dict(kind="venue", at_ms=8, online=True), fair(9)], max_fair_age_ms=2)
    assert result["quote_decisions"][1]["eligible"] is False
    assert result["quote_decisions"][2]["eligible"] is False
    assert [o["submitted_ms"] for o in result["orders"]] == [0, 0, 9, 9]


def test_crossing_own_cancel_pending_quote_blocks_submission():
    # Filled bid frees buy capacity, but an old ask must cancel before a higher bid.
    result = run([fair(0), trade(1, "2"), fair(2, "110"), fair(12, "110")], cancel_latency_ms=10)
    assert not any(o["submitted_ms"] == 2 for o in result["orders"])
    assert any(o["submitted_ms"] == 12 for o in result["orders"])


def test_sizes_round_down_to_step_and_zero_capacity_disables_side():
    result = run([fair(0)], initial_inventory="3", order_size="1.7")
    assert len(result["orders"]) == 1
    assert result["orders"][0]["side"] == "sell"
    assert result["orders"][0]["quantity"] == "1.5"


def test_invalid_future_observation_and_explicit_order_input_rejected():
    with pytest.raises(ValueError, match="future"):
        run([fair(0, observed=1)])
    with pytest.raises(ValueError):
        run([dict(kind="submit", at_ms=0, side="buy", price="99", quantity="1", order_id="manual")])


def test_expiry_runs_without_source_events_and_keeps_cancel_latency():
    result = run([fair(0), trade(10), trade(14), trade(15)], quote_ttl_ms=10, cancel_latency_ms=5)
    assert [f["at_ms"] for f in result["fills"]] == [10, 14]
    assert [a["at_ms"] for a in result["audit"] if a["event"] == "cancel_requested"] == [10, 10]
    assert result["orders"][1]["status"] == "canceled"
    quiet = run([fair(0)], quote_ttl_ms=10, cancel_latency_ms=5)
    assert all(o["status"] == "canceled" for o in quiet["orders"])
    assert quiet["quote_decisions"][-1]["trigger"] == "expiry"


def test_exact_deadline_precedes_trade_and_fresh_receipt():
    result = run([fair(0), trade(10), fair(10)], quote_ttl_ms=10, end_ms=10)
    assert result["fills"] == []
    assert [d["trigger"] for d in result["quote_decisions"]] == ["fair", "expiry", "fair"]
    assert [o["submitted_ms"] for o in result["orders"]] == [0, 0, 10, 10]


def test_refresh_invalidates_old_timer_but_does_not_extend_source_freshness():
    renewed = run([fair(0), fair(9), trade(10)], quote_ttl_ms=10, end_ms=10)
    assert len(renewed["fills"]) == 1
    assert all(d["trigger"] == "fair" for d in renewed["quote_decisions"])
    stale_source = run([fair(0), fair(9, observed=0), trade(10), trade(11)],
                       quote_ttl_ms=50, max_fair_age_ms=10, end_ms=11)
    assert [f["at_ms"] for f in stale_source["fills"]] == [10]
    assert stale_source["quote_decisions"][-1]["at_ms"] == 11


def test_halt_defers_expiry_cancel_ack_until_resume():
    result = run([fair(0), dict(kind="venue", at_ms=5, online=False),
                  dict(kind="venue", at_ms=20, online=True), trade(20)],
                 quote_ttl_ms=10, cancel_latency_ms=2)
    assert result["fills"] == []
    assert all(o["status"] == "canceled" for o in result["orders"])
    assert [a["at_ms"] for a in result["audit"] if a["event"] == "canceled"] == [20, 20]


def test_end_before_timer_and_cancel_ack_retains_reservations():
    before = run([fair(0)], quote_ttl_ms=10, end_ms=9)
    assert len(before["quote_decisions"]) == 1
    pending = run([fair(0)], quote_ttl_ms=10, cancel_latency_ms=5, end_ms=12)
    assert all(o["status"] == "cancel_pending" for o in pending["orders"])
    assert pending["client_reservations"] == {"buy": "2", "sell": "2"}


def test_expiry_preserves_unacknowledged_fill_reservation():
    result = run([fair(0), trade(1)], quote_ttl_ms=5, fill_ack_latency_ms=20, end_ms=10)
    assert result["pending_fill_acknowledgements"] == 1
    assert result["client_reservations"] == {"buy": "1", "sell": "0"}
    assert result["ending_reservations"] == {"buy": "0", "sell": "0"}


def test_expiry_before_activation_prevents_late_order_fill():
    result = run([fair(0), trade(10)], quote_ttl_ms=5, submit_latency_ms=10)
    assert result["fills"] == []
    assert all(o["status"] == "canceled" for o in result["orders"])


def test_expiry_queues_during_disconnect_and_reconnect_needs_new_fair():
    result = run([fair(0), dict(kind="connection", at_ms=1, connected=False),
                  trade(6), dict(kind="connection", at_ms=10, connected=True), fair(15)],
                 quote_ttl_ms=5, cancel_latency_ms=5)
    assert result["fills"][0]["at_ms"] == 6
    assert result["fills"][0]["delivered_at_ms"] == 10
    assert [o["submitted_ms"] for o in result["orders"]] == [0, 0, 15, 15]
    assert [a["at_ms"] for a in result["audit"] if a["event"] == "queued_cancel_sent"] == [10, 10]
