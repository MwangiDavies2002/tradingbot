"""Optional terminal exit-cost projection; never mutates the simulated order ledger."""
from decimal import Decimal

from pydantic import Field, model_validator

from app.institutional.data import Record
from app.institutional.instruments import Positive, Nonnegative


class LiquidationScenario(Record):
    bid: Positive
    ask: Positive
    available_quantity: Nonnegative
    event_ms: int = Field(ge=0, strict=True)
    available_ms: int = Field(ge=0, strict=True)
    max_age_ms: int = Field(default=1000, ge=0, le=60000, strict=True)
    slippage_bps: Nonnegative = Field(default=Decimal(0), le=1000)
    taker_fee_bps: Nonnegative = Field(default=Decimal(0), le=1000)

    @model_validator(mode="after")
    def consistent(self):
        if self.bid > self.ask:
            raise ValueError("Liquidation bid must not exceed ask")
        if self.available_ms < self.event_ms:
            raise ValueError("Liquidation quote cannot be available before its event")
        return self


def project_liquidation(request, ledger):
    scenario = request.liquidation
    blockers = []
    if not ledger["client_connected"]:
        blockers.append("client_disconnected")
    if not ledger["venue_online"]:
        blockers.append("venue_halted")
    if any(ledger["client_reservations"].values()):
        blockers.append("unresolved_order_or_fill_reservations")
    if ledger["pending_fill_acknowledgements"] or ledger["pending_terminal_acknowledgements"] or ledger["queued_cancellations"]:
        blockers.append("pending_client_messages_or_cancels")
    if scenario.available_ms > request.end_ms or not 0 <= request.end_ms - scenario.event_ms <= scenario.max_age_ms:
        blockers.append("exit_quote_stale_or_unavailable")
    common = {"mode": "hypothetical_exit_cost_projection", "ledger_unchanged": True,
              "limitations": "Supplied exit-side liquidity and adverse slippage are assumptions, not executable depth. No order submission, margin, financing or contract settlement."}
    if blockers:
        return common | {"status": "blocked", "blockers": blockers}
    inventory = ledger["ending_inventory"]
    sign = Decimal(1) if inventory >= 0 else Decimal(-1)
    quantity = min(abs(inventory), scenario.available_quantity)
    touch = scenario.bid if inventory >= 0 else scenario.ask
    price = touch * (1 - sign * scenario.slippage_bps / 10000)
    fee = quantity * price * scenario.taker_fee_bps / 10000
    cash_delta = sign * quantity * price - fee
    remaining = inventory - sign * quantity
    return common | {"status": "flat" if inventory == 0 else ("complete" if remaining == 0 else "partial"),
        "blockers": [], "side": None if inventory == 0 else ("sell" if inventory > 0 else "buy"),
        "projected_exit_quantity": quantity, "projected_exit_price": price if quantity else None,
        "projected_remaining_inventory": remaining, "projected_cash_change": cash_delta,
        "slippage_cost": quantity * abs(price - touch), "taker_fee": fee,
        "execution_cost_vs_mark": sign * quantity * (request.final_mark - price) + fee,
        "projected_marked_pnl_after_exit": ledger["cash_change"] + cash_delta + remaining * request.final_mark
                                           - request.initial_inventory * request.initial_mark}
