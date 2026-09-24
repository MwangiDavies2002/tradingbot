"""Offline single-instrument order ledger with explicit event and latency scenarios."""
from decimal import Decimal, localcontext
from collections import deque
import heapq
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.institutional.data import Record
from app.institutional.instruments import Positive, decimal_text
from app.institutional.liquidation import LiquidationScenario, project_liquidation


class Submit(Record):
    kind: Literal["submit"]
    at_ms: int = Field(ge=0, strict=True)
    order_id: str = Field(min_length=1, max_length=64)
    side: Literal["buy", "sell"]
    price: Positive
    quantity: Positive


class Cancel(Record):
    kind: Literal["cancel"]
    at_ms: int = Field(ge=0, strict=True)
    order_id: str = Field(min_length=1, max_length=64)


class Print(Record):
    kind: Literal["trade"]
    at_ms: int = Field(ge=0, strict=True)
    aggressor: Literal["buy", "sell"]
    price: Positive
    quantity: Positive


class VenueState(Record):
    kind: Literal["venue"]
    at_ms: int = Field(ge=0, strict=True)
    online: bool = Field(strict=True)


class Reject(Record):
    kind: Literal["reject"]
    at_ms: int = Field(ge=0, strict=True)
    order_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=256)


class ConnectionState(Record):
    kind: Literal["connection"]
    at_ms: int = Field(ge=0, strict=True)
    connected: bool = Field(strict=True)


class FairUpdate(Record):
    kind: Literal["fair"]
    at_ms: int = Field(ge=0, strict=True)
    observed_ms: int = Field(ge=0, strict=True)
    price: Positive

    @model_validator(mode="after")
    def available(self):
        if self.observed_ms > self.at_ms:
            raise ValueError("Fair observation cannot be from the future")
        return self


class QuoteTimer(Record):
    """Internal controller deadline, never accepted as a manual lifecycle input."""
    at_ms: int
    generation: int


class LifecycleRequest(Record):
    initial_inventory: Decimal = Field(default=Decimal(0), ge=-Decimal("1e12"), le=Decimal("1e12"), max_digits=30, decimal_places=12)
    inventory_limit: Positive
    initial_mark: Positive
    final_mark: Positive
    end_ms: int = Field(ge=0, strict=True)
    submit_latency_ms: int = Field(default=0, ge=0, le=60000, strict=True)
    cancel_latency_ms: int = Field(default=0, ge=0, le=60000, strict=True)
    fill_ack_latency_ms: int = Field(default=0, ge=0, le=60000, strict=True)
    fee_bps: Decimal = Field(default=Decimal(0), ge=-1000, le=1000, max_digits=30, decimal_places=12)
    liquidation: LiquidationScenario | None = None
    fill_fraction: Positive = Field(default=Decimal(1), le=1)
    events: list[Annotated[Submit | Cancel | Print | VenueState | Reject | ConnectionState, Field(discriminator="kind")]] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def ordered(self):
        if abs(self.initial_inventory) > self.inventory_limit:
            raise ValueError("Initial inventory exceeds limit")
        if any(b.at_ms < a.at_ms for a, b in zip(self.events, self.events[1:])):
            raise ValueError("Events must be in nondecreasing timestamp order")
        if self.events[-1].at_ms > self.end_ms:
            raise ValueError("end_ms must cover all events")
        ids = set()
        for event in self.events:
            if isinstance(event, Submit):
                if event.order_id in ids:
                    raise ValueError("Order IDs must be unique, including rejected orders")
                ids.add(event.order_id)
            elif isinstance(event, (Cancel, Reject)) and event.order_id not in ids:
                raise ValueError("Cancel/reject must reference an earlier submitted order")
        if len(ids) > 500:
            raise ValueError("At most 500 submitted orders are supported")
        return self


def simulate_lifecycle(request: LifecycleRequest) -> dict:
    with localcontext() as context:
        context.prec = 80
        return _simulate(request)


def _simulate(request, controller=None):
    orders, fills, audit, path = {}, [], [], []
    inventory, cash, fees = request.initial_inventory, Decimal(0), Decimal(0)
    client_inventory, client_cash, client_fees = inventory, Decimal(0), Decimal(0)
    pending_fills = deque()
    unacknowledged = {"buy": Decimal(0), "sell": Decimal(0)}
    venue_online = True
    client_connected = True
    reconnected_ms = 0
    resumed_ms = 0
    decisions = []

    def outstanding():
        return [order for order in orders.values() if order["status"] in ("open", "cancel_pending")]

    def reservations():
        return {side: sum((o["remaining"] for o in outstanding() if o["side"] == side), Decimal(0))
                for side in ("buy", "sell")}

    def client_reservations():
        resting = reservations()
        for order in orders.values():
            if not order["terminal_acknowledged"]:
                resting[order["side"]] += order["remaining"]
        return {side: resting[side] + unacknowledged[side] for side in ("buy", "sell")}

    def acknowledge(at_ms):
        nonlocal client_inventory, client_cash, client_fees
        if not client_connected:
            return
        while pending_fills and pending_fills[0]["ack_at_ms"] <= at_ms:
            fill = pending_fills.popleft()
            sign = Decimal(1) if fill["side"] == "buy" else Decimal(-1)
            client_inventory += sign * fill["quantity"]
            client_cash -= sign * fill["quantity"] * fill["price"] + fill["fee"]
            client_fees += fill["fee"]
            unacknowledged[fill["side"]] -= fill["quantity"]
            orders[fill["order_id"]]["acknowledged_filled"] += fill["quantity"]
            fill["acknowledged"] = True
            fill["delivered_at_ms"] = max(fill["ack_at_ms"], reconnected_ms)
            audit.append({"at_ms": fill["delivered_at_ms"], "order_id": fill["order_id"], "event": "fill_acknowledged"})
        for order in orders.values():
            if not order["terminal_acknowledged"]:
                order["terminal_acknowledged"] = True
                audit.append({"at_ms": at_ms, "order_id": order["order_id"], "event": "terminal_acknowledged"})

    def settle(at_ms):
        if not venue_online:
            return
        for order in outstanding():
            if order["cancel_effective_ms"] is not None and order["cancel_effective_ms"] <= at_ms:
                order["status"] = "canceled"
                order["terminal_acknowledged"] = client_connected
                audit.append({"at_ms": max(order["cancel_effective_ms"], resumed_ms), "order_id": order["order_id"], "event": "canceled"})

    inputs = deque(request.events)
    timers = []
    index = -1
    while inputs or (timers and timers[0][0] <= request.end_ms):
        if timers and timers[0][0] <= request.end_ms and (not inputs or timers[0][0] <= inputs[0].at_ms):
            event = heapq.heappop(timers)[2]
        else:
            event = inputs.popleft()
        index += 1
        acknowledge(event.at_ms)
        settle(event.at_ms)
        if isinstance(event, (FairUpdate, QuoteTimer)):
            if controller is None:
                raise ValueError("Fair updates require a quoting controller")
            # Do not expose venue fill totals/status to the decision function.
            client_orders = []
            for order in orders.values():
                terminal = order["terminal_acknowledged"] and order["status"] in ("rejected", "venue_rejected", "canceled")
                known_remaining = (order["remaining"] if not terminal else Decimal(0)) + order["filled"] - order["acknowledged_filled"]
                if known_remaining > 0 and not terminal:
                    client_orders.append({"order_id": order["order_id"], "side": order["side"],
                        "price": order["price"], "cancel_requested": order["client_cancel_requested"]})
            commands, decision, timer = controller(event, client_inventory, client_reservations(), client_orders, venue_online and client_connected)
            if decision is None:
                continue
            decisions.append(decision)
            if timer is not None:
                heapq.heappush(timers, (timer.at_ms, timer.generation, timer))
            inputs.extendleft(reversed(commands))
        elif isinstance(event, ConnectionState):
            if event.connected and not client_connected:
                reconnected_ms = event.at_ms
            client_connected = event.connected
            audit.append({"at_ms": event.at_ms, "order_id": None,
                          "event": "client_connected" if client_connected else "client_disconnected"})
            if client_connected:
                acknowledge(event.at_ms)
                for order in orders.values():
                    if order["cancel_queued"]:
                        order["cancel_queued"] = False
                        if order["status"] == "open":
                            order["status"] = "cancel_pending"
                            order["cancel_effective_ms"] = max(event.at_ms + request.cancel_latency_ms, order["active_ms"])
                            audit.append({"at_ms": event.at_ms, "order_id": order["order_id"], "event": "queued_cancel_sent"})
                        else:
                            audit.append({"at_ms": event.at_ms, "order_id": order["order_id"], "event": "queued_cancel_obsolete"})
                settle(event.at_ms)
        elif isinstance(event, VenueState):
            if event.online and not venue_online:
                resumed_ms = event.at_ms
            venue_online = event.online
            audit.append({"at_ms": event.at_ms, "order_id": None, "event": "venue_online" if venue_online else "venue_offline"})
            settle(event.at_ms)
        elif isinstance(event, Reject):
            order = orders[event.order_id]
            effective = order["status"] in ("open", "cancel_pending")
            if effective:
                order["status"] = "venue_rejected"
                order["terminal_acknowledged"] = client_connected
            audit.append({"at_ms": event.at_ms, "order_id": event.order_id,
                          "event": "venue_rejected" if effective else "reject_noop", "reason": event.reason})
        elif isinstance(event, Submit):
            if len(orders) >= 500:
                raise ValueError("Generated scenario exceeds 500 orders; reduce fair updates")
            reserved = client_reservations()
            capacity = (request.inventory_limit - client_inventory - reserved["buy"] if event.side == "buy"
                        else request.inventory_limit + client_inventory - reserved["sell"])
            accepted = client_connected and venue_online and event.quantity <= capacity
            orders[event.order_id] = {"order_id": event.order_id, "side": event.side,
                "price": event.price, "quantity": event.quantity, "remaining": event.quantity,
                "filled": Decimal(0), "acknowledged_filled": Decimal(0), "submitted_ms": event.at_ms,
                "active_ms": event.at_ms + request.submit_latency_ms, "sequence": index,
                "cancel_effective_ms": None, "client_cancel_requested": False,
                "cancel_queued": False, "terminal_acknowledged": True,
                "status": "open" if accepted else "rejected"}
            audit.append({"at_ms": event.at_ms, "order_id": event.order_id,
                          "event": "accepted" if accepted else ("rejected_client_disconnected" if not client_connected else
                              ("rejected_inventory_capacity" if venue_online else "rejected_venue_offline"))})
        elif isinstance(event, Cancel):
            order = orders[event.order_id]
            order["client_cancel_requested"] = True
            if order["status"] == "open" and not order["cancel_queued"] and not client_connected:
                order["cancel_queued"] = True
                audit.append({"at_ms": event.at_ms, "order_id": event.order_id, "event": "cancel_queued"})
            elif order["status"] == "open" and not order["cancel_queued"]:
                order["status"] = "cancel_pending"
                # A pre-activation cancel cannot overtake the original submission.
                order["cancel_effective_ms"] = max(event.at_ms + request.cancel_latency_ms, order["active_ms"])
                audit.append({"at_ms": event.at_ms, "order_id": event.order_id, "event": "cancel_requested"})
                settle(event.at_ms)
            else:
                audit.append({"at_ms": event.at_ms, "order_id": event.order_id, "event": "cancel_noop"})
        elif venue_online:
            side = "sell" if event.aggressor == "buy" else "buy"
            candidates = [o for o in outstanding() if o["side"] == side and o["active_ms"] <= event.at_ms
                          and (event.price >= o["price"] if side == "sell" else event.price <= o["price"])]
            candidates.sort(key=lambda o: (o["price"] if side == "sell" else -o["price"], o["active_ms"], o["sequence"]))
            available = event.quantity * request.fill_fraction
            for order in candidates:
                size = min(order["remaining"], available)
                if size <= 0:
                    break
                sign = Decimal(1) if side == "buy" else Decimal(-1)
                fee = size * order["price"] * request.fee_bps / 10000
                inventory += sign * size
                cash -= sign * size * order["price"] + fee
                fees += fee
                available -= size
                order["remaining"] -= size
                order["filled"] += size
                if order["remaining"] == 0:
                    order["status"] = "filled"
                fill = {"at_ms": event.at_ms, "order_id": order["order_id"], "side": side,
                        "quantity": size, "price": order["price"], "fee": fee,
                        "ack_at_ms": event.at_ms + request.fill_ack_latency_ms, "acknowledged": False,
                        "delivered_at_ms": None}
                fills.append(fill)
                pending_fills.append(fill)
                unacknowledged[side] += size
        acknowledge(event.at_ms)
        reserved = reservations()
        client_reserved = client_reservations()
        path.append({"at_ms": event.at_ms, "event_index": index, "inventory": inventory,
                     "reserved_buy": reserved["buy"], "reserved_sell": reserved["sell"],
                     "maximum_inventory": inventory + reserved["buy"],
                     "minimum_inventory": inventory - reserved["sell"], "venue_online": venue_online,
                     "client_connected": client_connected,
                     "client_inventory": client_inventory, "client_reserved_buy": client_reserved["buy"],
                     "client_reserved_sell": client_reserved["sell"],
                     "client_maximum_inventory": client_inventory + client_reserved["buy"],
                     "client_minimum_inventory": client_inventory - client_reserved["sell"]})
    acknowledge(request.end_ms)
    settle(request.end_ms)
    result = {"mode": "offline_order_lifecycle", "live_authorized": False,
        "orders": list(orders.values()), "fills": fills, "audit": sorted(audit, key=lambda row: row["at_ms"]),
        "inventory_path": path, "ending_inventory": inventory, "ending_reservations": reservations(),
        "cash_change": cash, "fees": fees,
        "fees_charged": sum((max(f["fee"], Decimal(0)) for f in fills), Decimal(0)),
        "rebates_earned": sum((max(-f["fee"], Decimal(0)) for f in fills), Decimal(0)),
        "client_inventory": client_inventory, "client_cash_change": client_cash, "client_fees": client_fees,
        "client_reservations": client_reservations(), "unacknowledged_quantity": unacknowledged,
        "pending_fill_acknowledgements": len(pending_fills),
        "venue_online": venue_online,
        "client_connected": client_connected,
        "pending_terminal_acknowledgements": sum(not o["terminal_acknowledged"] for o in orders.values()),
        "queued_cancellations": sum(o["cancel_queued"] for o in orders.values()),
        "marked_pnl": cash + inventory * request.final_mark - request.initial_inventory * request.initial_mark,
        "limitations": ["One instrument in underlying units and one quote currency; no margin or instrument-grid validation.",
            "Explicit scenario events, not an automatic strategy. Same-time inputs execute in list order; effective cancels precede each input.",
            "Pending submissions and cancellations reserve full remaining size; pre-activation cancels wait for activation.",
            "Trade-through and a shared fill fraction are hypothetical; price/time priority applies only among simulated orders, not an exchange queue.",
            "Venue offline means a simulated matching halt: no fills/new submissions, outstanding reservations retained, cancel acknowledgements wait for resume. It is not a client network disconnect.",
            "Explicit reject events reject remaining venue quantity; client confirmation waits through disconnects. Prior fills remain booked.",
            "Admission uses acknowledged client inventory plus resting and unacknowledged fill quantities on each side, without netting unknown fills.",
            "Reliable fill/terminal messages buffer during client disconnects while venue matching continues. Reconnect delivers due messages before sending queued cancels; cancel latency starts at transmission.",
            "Unsent cancels queue while disconnected; new submissions are locally rejected. Previously transmitted orders/cancels continue at the venue. No automatic cancel-on-disconnect.",
            "Orders/status, cash_change and marked_pnl describe venue truth; client fields include only acknowledged fills. No message loss/reordering, market-data delay, hidden liquidity, self-trade prevention or hedging model.",
            "No automatic terminal cancellation or liquidation; open orders retain reservations at end_ms. Final mark is supplied, without exit costs."]}
    if controller is not None:
        result["quote_decisions"] = decisions
    if request.liquidation is not None:
        result["liquidation_projection"] = project_liquidation(request, result)
    result["limitations"].append("fee_bps is a signed hypothetical resting-fill rate: positive charge, negative rebate. It does not verify maker eligibility. Optional exit projections do not mutate this ledger.")

    def serialize(value):
        if isinstance(value, Decimal):
            return decimal_text(value)
        if isinstance(value, dict):
            return {key: serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [serialize(item) for item in value]
        return value
    return serialize(result)
