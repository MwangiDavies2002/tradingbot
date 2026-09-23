"""User-supplied instrument contracts and point-in-time cash conversion.

Decimal quantities/prices are serialized as strings. No provider specification,
calendar, margin requirement or FX price is inferred by these research tools.
"""
from decimal import Decimal, localcontext
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.institutional.data import Record, fingerprint

Positive = Annotated[Decimal, Field(gt=0, le=Decimal("1e12"), max_digits=30, decimal_places=12)]
Nonnegative = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), max_digits=30, decimal_places=12)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


class SessionWindow(Record):
    open_ms: int = Field(ge=0, strict=True)
    close_ms: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.close_ms <= self.open_ms:
            raise ValueError("Session close must follow open")
        return self


class InstrumentSpec(Record):
    instrument_id: str = Field(min_length=1, max_length=128)
    venue: str = Field(min_length=1, max_length=64)
    venue_symbol: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=256)
    product: Literal["spot", "linear_contract"]
    underlying_unit: str = Field(min_length=1, max_length=64)
    quote_currency: Currency
    contract_size: Positive = Decimal("1")
    tick_size: Positive
    quantity_step: Positive
    min_quantity: Positive
    max_quantity: Positive
    min_notional: Nonnegative = Decimal("0")
    published_ms: int = Field(ge=0, strict=True)
    valid_from_ms: int = Field(ge=0, strict=True)
    valid_until_ms: int = Field(gt=0, strict=True)
    sessions: list[SessionWindow] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        if self.valid_until_ms <= self.valid_from_ms:
            raise ValueError("Instrument validity end must follow start")
        if self.product == "spot" and self.contract_size != 1:
            raise ValueError("Spot quantity must already be in underlying units (contract_size=1)")
        if self.min_quantity > self.max_quantity:
            raise ValueError("min_quantity exceeds max_quantity")
        if self.min_quantity % self.quantity_step or self.max_quantity % self.quantity_step:
            raise ValueError("Quantity bounds must be multiples of quantity_step")
        ordered = sorted(self.sessions, key=lambda s: s.open_ms)
        if any(b.open_ms < a.close_ms for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Session windows overlap")
        if any(s.open_ms < self.valid_from_ms or s.close_ms > self.valid_until_ms for s in ordered):
            raise ValueError("Session windows must lie within instrument validity")
        return self


class FxQuote(Record):
    base_currency: Currency
    quote_currency: Currency
    bid: Positive
    ask: Positive
    event_ms: int = Field(ge=0, strict=True)
    available_ms: int = Field(ge=0, strict=True)
    source: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def consistent(self):
        if self.base_currency == self.quote_currency or self.bid > self.ask:
            raise ValueError("FX quote must have distinct currencies and bid <= ask")
        if self.available_ms < self.event_ms:
            raise ValueError("FX quote cannot be available before its event")
        return self


class ConversionRequest(Record):
    amount: Decimal = Field(ge=Decimal("-1e36"), le=Decimal("1e36"), max_digits=100, decimal_places=36)
    from_currency: Currency
    to_currency: Currency
    as_of_ms: int = Field(ge=0, strict=True)
    max_age_ms: int = Field(default=1000, ge=0, le=60000, strict=True)
    fx: FxQuote | None = None


def convert_currency(request: ConversionRequest) -> dict:
    if request.from_currency == request.to_currency:
        if request.fx is not None:
            raise ValueError("Same-currency conversion must not supply an FX quote")
        converted, rate, side = request.amount, Decimal(1), "identity"
    else:
        fx = request.fx
        if fx is None:
            raise ValueError("Cross-currency conversion requires an explicit FX quote")
        if fx.available_ms > request.as_of_ms or not 0 <= request.as_of_ms - fx.event_ms <= request.max_age_ms:
            raise ValueError("FX quote is stale or unavailable at the decision time")
        with localcontext() as context:
            context.prec = 80
            if (request.from_currency, request.to_currency) == (fx.base_currency, fx.quote_currency):
                rate = fx.bid if request.amount >= 0 else fx.ask
                side = "bid" if request.amount >= 0 else "ask"
                converted = request.amount * rate
            elif (request.from_currency, request.to_currency) == (fx.quote_currency, fx.base_currency):
                denominator = fx.ask if request.amount >= 0 else fx.bid
                side = "inverse_ask" if request.amount >= 0 else "inverse_bid"
                rate = 1 / denominator
                converted = request.amount / denominator
            else:
                raise ValueError("FX pair does not cover the requested currencies; triangulation is not supported")
    return {"amount": decimal_text(converted), "currency": request.to_currency,
            "rate": decimal_text(rate), "rate_side": side,
            "source": request.fx.source if request.fx else None, "live_authorized": False,
            "assumption": "Liquidation value for positive cash; replacement cost for negative cash. No fees or currency rounding."}


class InstrumentOrderRequest(Record):
    instrument: InstrumentSpec
    side: Literal["buy", "sell"]
    quantity: Positive
    price: Positive
    as_of_ms: int = Field(ge=0, strict=True)
    reporting_currency: Currency
    fx: FxQuote | None = None
    fx_max_age_ms: int = Field(default=1000, ge=0, le=60000, strict=True)


def validate_instrument_order(request: InstrumentOrderRequest) -> dict:
    spec = request.instrument
    with localcontext() as context:
        context.prec = 80
        units = request.quantity * spec.contract_size
        notional = units * request.price
        exposure = notional * (1 if request.side == "buy" else -1)
        checks = {
            "metadata_published": spec.published_ms <= request.as_of_ms,
            "metadata_effective": spec.valid_from_ms <= request.as_of_ms < spec.valid_until_ms,
            "session_open": any(s.open_ms <= request.as_of_ms < s.close_ms for s in spec.sessions),
            "price_on_tick": request.price % spec.tick_size == 0,
            "quantity_on_step": request.quantity % spec.quantity_step == 0,
            "quantity_within_bounds": spec.min_quantity <= request.quantity <= spec.max_quantity,
            "minimum_notional": notional >= spec.min_notional,
        }
    conversion = convert_currency(ConversionRequest(amount=exposure, from_currency=spec.quote_currency,
        to_currency=request.reporting_currency, as_of_ms=request.as_of_ms,
        max_age_ms=request.fx_max_age_ms, fx=request.fx))
    return {"instrument_id": spec.instrument_id, "venue_symbol": spec.venue_symbol,
            "revision": spec.revision, "instrument_hash": fingerprint(spec.model_dump(mode="json")),
            "checks": checks, "order_valid": all(checks.values()),
            "underlying_quantity": decimal_text(units), "quote_notional": decimal_text(notional),
            "quote_currency": spec.quote_currency, "signed_reference_exposure": decimal_text(exposure),
            "spot_cash_before_fees": decimal_text(exposure.copy_negate()) if spec.product == "spot" else None,
            "reporting_exposure": conversion, "live_authorized": False,
            "limitations": ["Supplied metadata and session windows require independent provider verification.",
                            "No automatic rounding, margin, fees, settlement or trading authorization.",
                            "Linear-contract notional is a reference exposure, not the cash paid for a leveraged contract."]}
