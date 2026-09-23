"""Offline execution plans. Displayed liquidity is a bound, not a fill promise."""
import math
from typing import Literal

from pydantic import Field

from app.institutional.data import BookEvent, OrderBook, Record


class VenueSnapshot(Record):
    book: BookEvent
    fee_bps: float = Field(default=0, ge=0, le=1000)


class RouteRequest(Record):
    venues: list[VenueSnapshot] = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0, le=1e12)
    arrival_price: float = Field(gt=0, le=1e12)
    as_of_ms: int = Field(ge=0, strict=True)
    max_age_ms: int = Field(default=1000, ge=0, le=60000)
    limit_price: float | None = Field(default=None, gt=0, le=1e12)


def route(request: RouteRequest) -> dict:
    """Greedy fee-adjusted taker sweep in a common instrument and currency.

    Limit price constrains raw execution price, not fee-adjusted price. Plans
    never reuse liquidity within a request and return any unfilled residual.
    """
    identity = {(v.book.symbol, v.book.currency) for v in request.venues}
    if len(identity) != 1 or len({v.book.venue for v in request.venues}) != len(request.venues):
        raise ValueError("Require distinct venues for one symbol and quote currency")
    sign = 1 if request.side == "buy" else -1
    levels = []
    for venue in request.venues:
        event = venue.book
        if event.kind != "snapshot":
            raise ValueError("Routing requires complete snapshots")
        book = OrderBook(event.venue, event.symbol, event.currency)
        book.apply(event)
        book.features(request.as_of_ms, request.max_age_ms)
        side = book.asks if sign == 1 else book.bids
        for price, size in side.items():
            if request.limit_price is not None and sign * (price - request.limit_price) > 0:
                continue
            effective = price * (1 + sign * venue.fee_bps / 10000)
            levels.append((sign * effective, event.venue, price, size, venue.fee_bps))
    remaining = request.quantity
    fills = []
    for _, venue, price, available, fee_bps in sorted(levels):
        if remaining <= 0:
            break
        size = min(remaining, available)
        fills.append({"venue": venue, "price": price, "quantity": size,
                      "fee": size * price * fee_bps / 10000})
        remaining = max(0.0, remaining - size)
    filled = sum(f["quantity"] for f in fills)
    notional = sum(f["quantity"] * f["price"] for f in fills)
    fees = sum(f["fee"] for f in fills)
    slippage = sign * (notional - request.arrival_price * filled)
    return {"mode": "offline_plan", "live_authorized": False, "fills": fills,
            "requested_quantity": request.quantity, "filled_quantity": filled,
            "unfilled_quantity": remaining, "fill_fraction": filled / request.quantity,
            "vwap": notional / filled if filled else None, "fees": fees,
            "arrival_slippage": slippage, "implementation_shortfall": slippage + fees,
            "shortfall_bps": (slippage + fees) / (request.arrival_price * filled) * 10000 if filled else None,
            "limitation": "Static displayed-depth sweep; no queue, latency, impact or hidden liquidity model. Shortfall excludes unfilled opportunity cost."}


class ScheduleRequest(Record):
    method: Literal["twap", "vwap", "participation"]
    quantity: float = Field(gt=0, le=1e12)
    start_ms: int = Field(ge=0, strict=True)
    interval_ms: int = Field(gt=0, strict=True)
    buckets: int = Field(default=10, ge=1, le=1000, strict=True)
    volumes: list[float] = Field(default_factory=list, max_length=1000)
    max_participation: float = Field(default=.1, gt=0, le=1)


def schedule(request: ScheduleRequest) -> dict:
    if request.method == "twap":
        weights = [1.0] * request.buckets
    else:
        weights = request.volumes
        if len(weights) != request.buckets or any(v < 0 for v in weights) or sum(weights) <= 0:
            raise ValueError("Supply one nonnegative volume per bucket and positive total volume")
    remaining = request.quantity
    children = []
    total = sum(weights)
    for i, weight in enumerate(weights):
        if request.method == "participation":
            target = weight * request.max_participation
        elif i == len(weights) - 1:
            target = remaining
        else:
            target = request.quantity * weight / total
        quantity = min(remaining, target)
        children.append({"scheduled_ms": request.start_ms + i * request.interval_ms, "quantity": quantity})
        remaining = max(0.0, remaining - quantity)
    return {"mode": "offline_plan", "method": request.method, "children": children,
            "unallocated_quantity": remaining, "live_authorized": False,
            "volume_assumption": "VWAP uses supplied ex-ante forecasts; participation uses supplied scenario volumes. No real-time controller."}


class CostRequest(Record):
    notional: float = Field(gt=0, le=1e15)
    spread_bps: float = Field(ge=0, le=10000)
    fee_bps: float = Field(ge=0, le=10000)
    slippage_bps: float = Field(ge=0, le=10000)
    daily_volatility: float = Field(ge=0, le=10)
    daily_volume_notional: float = Field(gt=0, le=1e18)
    impact_coefficient: float = Field(default=0, ge=0, le=10)
    annual_financing_rate: float = Field(default=0, ge=0, le=10)
    holding_days: float = Field(default=0, ge=0, le=36500)


def estimate_cost(request: CostRequest) -> dict:
    """One-way scenario cost; impact coefficient must be externally calibrated."""
    impact = request.impact_coefficient * request.daily_volatility * math.sqrt(
        request.notional / request.daily_volume_notional)
    parts = {"half_spread": request.notional * request.spread_bps / 20000,
             "fees": request.notional * request.fee_bps / 10000,
             "slippage": request.notional * request.slippage_bps / 10000,
             "impact": request.notional * impact,
             "financing": request.notional * request.annual_financing_rate * request.holding_days / 365}
    return {"components": parts, "total": sum(parts.values()),
            "total_bps": sum(parts.values()) / request.notional * 10000,
            "assumption": "Additive one-way scenario; avoid double-counting calibrated slippage and impact. Financing uses ACT/365."}
