from decimal import Decimal

import pytest

from app.institutional.order_lifecycle import LifecycleRequest, simulate_lifecycle


def run(inventory="2", **changes):
    data = dict(initial_inventory=inventory, inventory_limit="10", initial_mark="100", final_mark="100",
        end_ms=100, events=[dict(kind="venue", at_ms=0, online=True)],
        liquidation=dict(bid="99", ask="101", available_quantity="10", event_ms=95, available_ms=96,
                         slippage_bps="10", taker_fee_bps="20")) | changes
    return simulate_lifecycle(LifecycleRequest.model_validate(data))


@pytest.mark.parametrize("inventory,price,cash,side", [
    ("2", "98.901", "197.406396", "sell"), ("-2", "101.101", "-202.606404", "buy")])
def test_exit_costs_long_short_and_marked_pnl_reconcile(inventory, price, cash, side):
    result = run(inventory)
    projection = result["liquidation_projection"]
    assert projection["status"] == "complete"
    assert projection["side"] == side
    assert projection["projected_exit_price"] == price
    assert projection["projected_cash_change"] == cash
    assert projection["projected_remaining_inventory"] == "0"
    assert Decimal(projection["projected_marked_pnl_after_exit"]) == -Decimal(projection["execution_cost_vs_mark"])
    assert result["ending_inventory"] == inventory
    assert result["cash_change"] == "0"


@pytest.mark.parametrize("quantity,status,remaining", [("0", "partial", "2"), ("0.5", "partial", "1.5"), ("2", "complete", "0")])
def test_exit_liquidity_caps_quantity_and_retains_residual(quantity, status, remaining):
    result = run(liquidation=dict(bid="99", ask="101", available_quantity=quantity, event_ms=100, available_ms=100))
    projection = result["liquidation_projection"]
    assert projection["status"] == status
    assert projection["projected_exit_quantity"] == quantity
    assert projection["projected_remaining_inventory"] == remaining
    assert Decimal(result["marked_pnl"]) - Decimal(projection["projected_marked_pnl_after_exit"]) == Decimal(projection["execution_cost_vs_mark"])


def test_flat_has_no_fee_or_exit_order():
    projection = run("0")["liquidation_projection"]
    assert projection["status"] == "flat"
    assert projection["side"] is None
    assert projection["projected_exit_price"] is None
    assert projection["taker_fee"] == "0"


@pytest.mark.parametrize("events,blocker", [
    ([dict(kind="connection", at_ms=0, connected=False)], "client_disconnected"),
    ([dict(kind="venue", at_ms=0, online=False)], "venue_halted"),
    ([dict(kind="submit", at_ms=0, order_id="a", side="buy", price="99", quantity="1")], "unresolved_order_or_fill_reservations")])
def test_unresolved_execution_blocks_exit_projection(events, blocker):
    projection = run(events=events)["liquidation_projection"]
    assert projection["status"] == "blocked"
    assert blocker in projection["blockers"]
    assert "projected_marked_pnl_after_exit" not in projection


@pytest.mark.parametrize("quote", [dict(event_ms=101, available_ms=101), dict(event_ms=0, available_ms=0, max_age_ms=99)])
def test_unavailable_or_stale_exit_quote_blocked(quote):
    projection = run(liquidation=dict(bid="99", ask="101", available_quantity="2") | quote)["liquidation_projection"]
    assert projection["blockers"] == ["exit_quote_stale_or_unavailable"]


def test_signed_rebate_credits_cash_and_waits_for_client_ack():
    events = [dict(kind="submit", at_ms=0, order_id="a", side="buy", price="100", quantity="1"),
              dict(kind="trade", at_ms=1, aggressor="sell", price="99", quantity="1")]
    result = run("0", events=events, fee_bps="-2", fill_ack_latency_ms=100)
    assert result["fees"] == "-0.02"
    assert result["fees_charged"] == "0"
    assert result["rebates_earned"] == "0.02"
    assert result["cash_change"] == "-99.98"
    assert result["client_cash_change"] == "0"
    assert "pending_client_messages_or_cancels" in result["liquidation_projection"]["blockers"]
    delivered = run("0", events=events, fee_bps="-2", fill_ack_latency_ms=99)
    assert delivered["client_cash_change"] == delivered["cash_change"]
    assert delivered["client_fees"] == "-0.02"


def test_crossed_exit_quotes_and_invalid_fee_values_rejected():
    with pytest.raises(ValueError, match="bid"):
        run(liquidation=dict(bid="102", ask="101", available_quantity="1", event_ms=0, available_ms=0))
    with pytest.raises(ValueError):
        run(fee_bps="-1001")
