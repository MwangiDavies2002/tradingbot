"""Inventory-skewed research quotes, without order submission or simulated fills."""
import math
from typing import Literal

from pydantic import Field

from app.institutional.data import Record


class QuoteRequest(Record):
    fair_price: float = Field(gt=0, le=1e12)
    tick_size: float = Field(gt=0, le=1e9)
    inventory: float = Field(ge=-1e12, le=1e12)
    inventory_limit: float = Field(gt=0, le=1e12)
    order_size: float = Field(gt=0, le=1e12)
    half_spread_bps: float = Field(default=5, gt=0, le=1000)
    inventory_skew_bps: float = Field(default=10, ge=0, le=1000)
    volatility_buffer_bps: float = Field(default=0, ge=0, le=1000)
    hedge_cost_bps: float = Field(default=0, ge=0, le=1000)


def quote(request: QuoteRequest) -> dict:
    if abs(request.inventory) > request.inventory_limit:
        raise ValueError("Inventory exceeds limit; explicit risk reduction is required")
    center = request.fair_price * (1 - request.inventory / request.inventory_limit * request.inventory_skew_bps / 10000)
    width = request.fair_price * (request.half_spread_bps + request.volatility_buffer_bps + request.hedge_cost_bps) / 10000
    bid = math.floor((center - width) / request.tick_size) * request.tick_size
    ask = math.ceil((center + width) / request.tick_size) * request.tick_size
    if bid <= 0 or bid >= ask:
        raise ValueError("Tick/price combination cannot produce valid two-sided quotes")
    bid_size = min(request.order_size, request.inventory_limit - request.inventory)
    ask_size = min(request.order_size, request.inventory_limit + request.inventory)
    return {"reservation_price": center, "bid": bid if bid_size > 0 else None,
            "ask": ask if ask_size > 0 else None, "bid_size": bid_size, "ask_size": ask_size,
            "live_authorized": False, "mode": "offline_quote",
            "limitation": "No queue/fill/adverse-selection model. Outstanding orders must be included in inventory limits before any live integration."}


class TradePrint(Record):
    event_ms: int = Field(ge=0, strict=True)
    received_ms: int = Field(ge=0, strict=True)
    aggressor: Literal["buy", "sell"]
    price: float = Field(gt=0, le=1e12)
    size: float = Field(gt=0, le=1e12)
    fair_price: float = Field(gt=0, le=1e12)


class MarketMakingRequest(Record):
    quote_config: QuoteRequest
    start_ms: int = Field(ge=0, strict=True)
    trades: list[TradePrint] = Field(min_length=1, max_length=10000)
    fee_bps: float = Field(default=0, ge=0, le=1000)
    quote_latency_ms: int = Field(default=0, ge=0, le=60000, strict=True)
    max_quote_age_ms: int = Field(default=1000, gt=0, le=60000, strict=True)
    fill_fraction: float = Field(default=.1, gt=0, le=1)


def simulate_market_making(request: MarketMakingRequest) -> dict:
    """Replay prints against previously formed quotes, then reprice.

    Fill fraction is a supplied scenario assumption, never an estimated queue
    probability. Each print reprices quotes; unfilled resting sizes are canceled
    instantaneously in this simplified simulator.
    """
    config = request.quote_config
    inventory, cash, fees = config.inventory, 0.0, 0.0
    initial_value = inventory * config.fair_price
    current_quote = quote(config)
    quote_time = request.start_ms
    previous_event = request.start_ms - 1
    previous_receive = request.start_ms - 1
    fills, path = [], []
    inactive = 0
    for trade in request.trades:
        if (trade.event_ms <= previous_event or trade.received_ms < trade.event_ms
                or trade.received_ms < previous_receive):
            raise ValueError("Trade prints must have increasing event times and nondecreasing receive times")
        previous_event, previous_receive = trade.event_ms, trade.received_ms
        active = quote_time + request.quote_latency_ms <= trade.event_ms <= quote_time + request.max_quote_age_ms
        if not active:
            inactive += 1
        side = "ask" if trade.aggressor == "buy" else "bid"
        price = current_quote[side]
        sign = -1 if side == "ask" else 1
        crosses = price is not None and (trade.price >= price if side == "ask" else trade.price <= price)
        if active and crosses:
            size = min(current_quote[f"{side}_size"], trade.size * request.fill_fraction)
            fee = size * price * request.fee_bps / 10000
            inventory += sign * size
            cash -= sign * size * price + fee
            fees += fee
            fills.append({"event_ms": trade.event_ms, "side": "buy" if sign == 1 else "sell",
                          "quantity": size, "price": price, "fee": fee,
                          "markout_to_current_fair": sign * size * (trade.fair_price - price)})
        path.append({"event_ms": trade.event_ms, "inventory": inventory,
                     "marked_pnl": cash + inventory * trade.fair_price - initial_value})
        # This print's fair estimate becomes usable only on receipt, after fill evaluation.
        config = QuoteRequest.model_validate(config.model_dump() | {"inventory": inventory, "fair_price": trade.fair_price})
        current_quote = quote(config)
        quote_time = trade.received_ms
    return {"mode": "offline_simulation", "fills": fills, "inventory_path": path,
            "fill_count": len(fills), "ending_inventory": inventory, "cash_change": cash,
            "fees": fees, "marked_pnl": path[-1]["marked_pnl"], "inactive_quote_events": inactive,
            "live_authorized": False,
            "limitations": ["Trade-through plus fixed fill fraction is a hypothetical fill rule, not queue replay.",
                            "Cancel/replace is instantaneous; no outstanding-order, hidden-liquidity or hedge model.",
                            "Ending inventory is marked, not liquidated. No financing or final exit costs."]}
