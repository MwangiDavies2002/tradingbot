"""Decimal, single-venue limit-order projections using explicit instrument rules."""
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field, model_validator

from app.institutional.data import Record, fingerprint
from app.institutional.instruments import (Positive, Nonnegative, Currency, InstrumentSpec,
    InstrumentOrderRequest, decimal_text, validate_instrument_order)


class NativeLevel(Record):
    price: Positive
    quantity: Positive


class NativeSnapshot(Record):
    venue: str = Field(min_length=1, max_length=64)
    venue_symbol: str = Field(min_length=1, max_length=64)
    quote_currency: Currency
    event_ms: int = Field(ge=0, strict=True)
    available_ms: int = Field(ge=0, strict=True)
    bids: list[NativeLevel] = Field(min_length=1, max_length=1000)
    asks: list[NativeLevel] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_book(self):
        if self.available_ms < self.event_ms:
            raise ValueError("Snapshot cannot be available before its event")
        if max(level.price for level in self.bids) >= min(level.price for level in self.asks):
            raise ValueError("Snapshot must be uncrossed")
        if any(len({level.price for level in levels}) != len(levels) for levels in (self.bids, self.asks)):
            raise ValueError("Duplicate native price level")
        return self


class PlanInputs(Record):
    book: NativeSnapshot
    side: Literal["buy", "sell"]
    quantity: Positive
    limit_price: Positive
    arrival_price: Positive
    fee_bps: Nonnegative = Decimal("0")
    as_of_ms: int = Field(ge=0, strict=True)
    max_age_ms: int = Field(default=1000, ge=0, le=60000, strict=True)

    @model_validator(mode="after")
    def reasonable_fee(self):
        if self.fee_bps > 1000:
            raise ValueError("Fee scenario exceeds 1000 bps")
        return self


class InstrumentPlanRequest(PlanInputs):
    instrument: InstrumentSpec


def plan_instrument_order(request: InstrumentPlanRequest) -> dict:
    spec, book = request.instrument, request.book
    if (book.venue, book.venue_symbol, book.quote_currency) != (spec.venue, spec.venue_symbol, spec.quote_currency):
        raise ValueError("Snapshot identity does not match the instrument specification")
    if book.available_ms > request.as_of_ms or not 0 <= request.as_of_ms - book.event_ms <= request.max_age_ms:
        raise ValueError("Snapshot is stale or unavailable at decision time")
    if not spec.valid_from_ms <= book.event_ms < spec.valid_until_ms:
        raise ValueError("Snapshot is outside the specification validity interval")
    if not any(s.open_ms <= book.event_ms < s.close_ms for s in spec.sessions):
        raise ValueError("Snapshot is outside the supplied trading sessions")
    validation = validate_instrument_order(InstrumentOrderRequest(instrument=spec, side=request.side,
        quantity=request.quantity, price=request.limit_price, as_of_ms=request.as_of_ms,
        reporting_currency=spec.quote_currency))
    if not validation["order_valid"]:
        failures = ", ".join(key for key, passed in validation["checks"].items() if not passed)
        raise ValueError(f"Order violates instrument constraints: {failures}")
    if not any(s.open_ms <= book.event_ms <= request.as_of_ms < s.close_ms for s in spec.sessions):
        raise ValueError("Snapshot and decision must belong to the same trading session")
    with localcontext() as context:
        context.prec = 80
        for level in book.bids + book.asks:
            if level.price % spec.tick_size or level.quantity % spec.quantity_step:
                raise ValueError("Snapshot price/quantity is off the instrument grid")
        sign = Decimal(1) if request.side == "buy" else Decimal(-1)
        levels = sorted(book.asks if request.side == "buy" else book.bids,
                        key=lambda level: level.price, reverse=request.side == "sell")
        remaining = request.quantity
        projected = []
        notional, fees = Decimal(0), Decimal(0)
        for level in levels:
            if remaining == 0 or sign * (level.price - request.limit_price) > 0:
                break
            quantity = min(remaining, level.quantity)
            units = quantity * spec.contract_size
            value = units * level.price
            fee = value * request.fee_bps / 10000
            projected.append({"price": decimal_text(level.price), "native_quantity": decimal_text(quantity),
                              "underlying_quantity": decimal_text(units), "reference_notional": decimal_text(value),
                              "fee_scenario": decimal_text(fee)})
            remaining -= quantity
            notional += value
            fees += fee
        filled = request.quantity - remaining
        units = filled * spec.contract_size
        shortfall = sign * (notional - units * request.arrival_price) + fees
        return {"mode": "offline_instrument_plan", "live_authorized": False,
                "instrument_hash": fingerprint(spec.model_dump(mode="json")),
                "instrument_id": spec.instrument_id, "revision": spec.revision,
                "order": {"venue": spec.venue, "venue_symbol": spec.venue_symbol, "side": request.side,
                          "type": "limit", "native_quantity": decimal_text(request.quantity),
                          "limit_price": decimal_text(request.limit_price)},
                "checks": validation["checks"], "projected_fills": projected,
                "filled_native_quantity": decimal_text(filled), "unfilled_native_quantity": decimal_text(remaining),
                "filled_underlying_quantity": decimal_text(units), "quote_currency": spec.quote_currency,
                "filled_reference_notional": decimal_text(notional), "fees_scenario": decimal_text(fees),
                "vwap": decimal_text(notional / units) if units else None,
                "arrival_shortfall_scenario": decimal_text(shortfall),
                "limitations": ["Single parent order; projected partial fills are not independently submitted child orders.",
                                "Displayed depth does not guarantee fills; no queues, latency or impact are modeled.",
                                "Linear notional is reference exposure, not margin or contract cash settlement.",
                                "Fees are a supplied bps scenario. Metadata publication times are caller assertions."]}
