"""Causal fair-update controller over the offline order lifecycle ledger."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, localcontext
from typing import Annotated

from pydantic import Field

from app.institutional.instruments import Positive, Nonnegative
from app.institutional.order_lifecycle import LifecycleRequest, FairUpdate, QuoteTimer, Print, VenueState, ConnectionState, Submit, Cancel, _simulate


class AutoQuoteRequest(LifecycleRequest):
    tick_size: Positive
    quantity_step: Positive
    order_size: Positive
    half_spread_bps: Positive = Field(default=Decimal(5), le=1000)
    inventory_skew_bps: Nonnegative = Field(default=Decimal(10), le=1000)
    max_fair_age_ms: int = Field(default=1000, ge=0, le=60000, strict=True)
    quote_ttl_ms: int = Field(default=1000, gt=0, le=60000, strict=True)
    events: list[Annotated[FairUpdate | Print | VenueState | ConnectionState, Field(discriminator="kind")]] = Field(min_length=1, max_length=1000)


def simulate_auto_quotes(request: AutoQuoteRequest) -> dict:
    sequence = 0
    latest_fair = None

    def decide(event, inventory, reserved, orders, online):
        nonlocal sequence, latest_fair
        expired = isinstance(event, QuoteTimer)
        if expired:
            if event.generation != sequence:
                return [], None, None
            fair = latest_fair
        else:
            sequence += 1
            latest_fair = fair = event
        commands = []
        valid = not expired and online and event.at_ms - fair.observed_ms <= request.max_fair_age_ms
        center = fair.price * (1 - inventory / request.inventory_limit * request.inventory_skew_bps / 10000)
        width = fair.price * request.half_spread_bps / 10000
        bid = ((center - width) / request.tick_size).to_integral_value(rounding=ROUND_FLOOR) * request.tick_size
        ask = ((center + width) / request.tick_size).to_integral_value(rounding=ROUND_CEILING) * request.tick_size
        valid = valid and 0 < bid < ask <= Decimal("1e12")
        actions = {}
        for side, price in (("buy", bid), ("sell", ask)):
            current = [o for o in orders if o["side"] == side]
            capacity = request.inventory_limit - inventory if side == "buy" else request.inventory_limit + inventory
            available = max(Decimal(0), capacity - reserved[side])
            size = (min(request.order_size, available) / request.quantity_step).to_integral_value(rounding=ROUND_FLOOR) * request.quantity_step
            keep = valid and current and all(o["price"] == price and not o["cancel_requested"] for o in current)
            if keep:
                actions[side] = "keep"
                continue
            for order in current:
                if not order["cancel_requested"]:
                    commands.append(Cancel(kind="cancel", at_ms=event.at_ms, order_id=order["order_id"]))
            # Wait for all prior same-side reservations, including unknown fills.
            crosses_own_order = any(o["side"] != side and
                (price >= o["price"] if side == "buy" else price <= o["price"]) for o in orders)
            if valid and reserved[side] == 0 and not current and size > 0 and not crosses_own_order:
                commands.append(Submit(kind="submit", at_ms=event.at_ms, order_id=f"quote-{sequence}-{side}",
                                       side=side, price=price, quantity=size))
                actions[side] = "submit"
            else:
                actions[side] = "cancel_or_wait" if current or reserved[side] else "inactive"
        deadline = min(event.at_ms + request.quote_ttl_ms, fair.observed_ms + request.max_fair_age_ms + 1) if valid else None
        timer = QuoteTimer(at_ms=deadline, generation=sequence) if deadline is not None else None
        return commands, {"at_ms": event.at_ms, "observed_ms": fair.observed_ms, "fair_price": fair.price,
                          "trigger": "expiry" if expired else "fair", "expires_at_ms": deadline,
                          "client_inventory": inventory, "reserved": reserved,
                          "bid": bid if valid else None, "ask": ask if valid else None,
                          "eligible": bool(valid), "actions": actions}, timer

    with localcontext() as context:
        context.prec = 80
        result = _simulate(request, decide)
    result["mode"] = "offline_auto_quoting"
    result["limitations"][1] = "Fair receipts trigger quoting; scheduled expiry triggers cancellation only. Expiry runs before same-time source events, which otherwise retain input order. Final mark never drives quotes."
    result["limitations"].extend([
        "Controller sees client inventory/reservations and submitted-order prices, not unacknowledged venue fills or future fair observations.",
        "Changed/stale/expired quotes request cancellation; replacements wait for a subsequent fair event and zero same-side reservations. No refresh on acknowledgements or expiry alone.",
        "Expiry is the earlier of last eligible fair receipt plus quote_ttl_ms and observed_ms plus max_fair_age_ms plus 1. Eligible refresh renews the timer; superseded deadlines are ignored.",
        "Expiry requests cancellation, not immediate venue removal. Submission/cancel latency and matching halts still apply; fills and reservations may persist after expiry. Only timers through end_ms are processed.",
        "Tick and quantity steps are supplied scenario inputs, not verified instrument metadata. No exchange queue, executable strategy or live broker integration."])
    return result
