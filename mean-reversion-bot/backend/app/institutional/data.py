"""Normalized price-level books and point-in-time observations.

Prices are quote-currency units per asset unit; sizes are asset units. Timestamps
are UTC epoch milliseconds, and sequence numbers are per venue/instrument.
This is an internal schema, not an exchange protocol implementation.
"""
from bisect import bisect_right
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Level(Record):
    price: float = Field(gt=0, le=1e12)
    size: float = Field(ge=0, le=1e12)


class BookEvent(Record):
    venue: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    event_ms: int = Field(ge=0, strict=True)
    received_ms: int = Field(ge=0, strict=True)
    sequence: int = Field(ge=0, strict=True)
    kind: Literal["snapshot", "delta"] = "snapshot"
    bids: list[Level] = Field(default_factory=list, max_length=1000)
    asks: list[Level] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_event(self):
        if self.received_ms < self.event_ms:
            raise ValueError("received_ms must not precede event_ms")
        for side in (self.bids, self.asks):
            if len({level.price for level in side}) != len(side):
                raise ValueError("Duplicate price levels in one side")
            if self.kind == "snapshot" and any(level.size == 0 for level in side):
                raise ValueError("Snapshots require positive sizes; zero deletes a delta level")
        return self


class OrderBook:
    def __init__(self, venue: str, symbol: str, currency: str):
        self.venue, self.symbol, self.currency = venue, symbol, currency
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.sequence = -1
        self.event_ms = -1
        self.received_ms = -1
        self.ready = False

    def apply(self, event: BookEvent) -> None:
        try:
            if (event.venue, event.symbol, event.currency) != (self.venue, self.symbol, self.currency):
                raise ValueError("Book identity mismatch")
            if event.sequence <= self.sequence or event.event_ms < self.event_ms or event.received_ms < self.received_ms:
                raise ValueError("Duplicate or out-of-order book event")
            if event.kind == "delta" and (not self.ready or event.sequence != self.sequence + 1):
                raise ValueError("Sequence gap: a new snapshot is required")
            bids = {} if event.kind == "snapshot" else dict(self.bids)
            asks = {} if event.kind == "snapshot" else dict(self.asks)
            for levels, target in ((event.bids, bids), (event.asks, asks)):
                for level in levels:
                    if level.size == 0:
                        target.pop(level.price, None)
                    else:
                        target[level.price] = level.size
            if not bids or not asks or max(bids) >= min(asks):
                raise ValueError("Book must be two-sided and uncrossed")
            if len(bids) > 1000 or len(asks) > 1000:
                raise ValueError("Book exceeds supported depth")
        except ValueError:
            self.ready = False
            raise
        self.bids, self.asks = bids, asks
        self.sequence, self.event_ms, self.received_ms = event.sequence, event.event_ms, event.received_ms
        self.ready = True

    def features(self, as_of_ms: int, max_age_ms: int = 1000) -> dict:
        if max_age_ms < 0 or not self.ready:
            raise ValueError("Book is not ready or age limit is invalid")
        if as_of_ms < self.received_ms or not 0 <= as_of_ms - self.event_ms <= max_age_ms:
            raise ValueError("Stale or future book")
        bid, ask = max(self.bids), min(self.asks)
        bid_size, ask_size = self.bids[bid], self.asks[ask]
        mid = (bid + ask) / 2
        return {"mid": mid, "spread": ask - bid, "spread_bps": (ask - bid) / mid * 10000,
                "top_imbalance": (bid_size - ask_size) / (bid_size + ask_size),
                "microprice": (ask * bid_size + bid * ask_size) / (bid_size + ask_size),
                "bid_depth": sum(self.bids.values()), "ask_depth": sum(self.asks.values()),
                "feed_latency_ms": self.received_ms - self.event_ms,
                "age_ms": as_of_ms - self.event_ms}


class Observation(Record):
    name: str = Field(min_length=1, max_length=128)
    event_ms: int = Field(ge=0, strict=True)
    available_ms: int = Field(ge=0, strict=True)
    value: float = Field(ge=-1e15, le=1e15)
    source: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def publication_follows_event(self):
        if self.available_ms < self.event_ms:
            raise ValueError("Observation cannot be available before its event")
        return self


def point_in_time(observations: list[Observation], decision_times: list[int], max_age_ms: int) -> list[dict]:
    """As-of join by publication time, including revisions only when available.

    Age is measured from the observation's event time, not its publication time.
    A late publication therefore cannot make an old observation look fresh.
    """
    if max_age_ms < 0 or any(t < 0 for t in decision_times):
        raise ValueError("Invalid time or age")
    grouped: dict[str, list[Observation]] = {}
    for obs in observations:
        grouped.setdefault(obs.name, []).append(obs)
    if len(grouped) > 100:
        raise ValueError("At most 100 distinct features are supported per join")
    for values in grouped.values():
        values.sort(key=lambda o: o.available_ms)
        if len({o.available_ms for o in values}) != len(values):
            raise ValueError("Ambiguous feature publications; use distinct feature names")
    times = {name: [o.available_ms for o in values] for name, values in grouped.items()}
    rows = []
    for decision in decision_times:
        row = {}
        for name, values in grouped.items():
            index = bisect_right(times[name], decision) - 1
            obs = values[index] if index >= 0 else None
            row[name] = obs.value if obs and decision - obs.event_ms <= max_age_ms else None
        rows.append(row)
    return rows


def fingerprint(value) -> str:
    """Canonical SHA-256 for JSON-compatible inputs, rejecting non-finite data."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def replay(events: list[BookEvent], max_age_ms: int = 1000) -> dict:
    books: dict[tuple, OrderBook] = {}
    output = []
    previous_receive = -1
    for event in events:
        if event.received_ms < previous_receive:
            raise ValueError("Replay must be ordered by received_ms")
        previous_receive = event.received_ms
        key = (event.venue, event.symbol, event.currency)
        book = books.setdefault(key, OrderBook(*key))
        book.apply(event)
        output.append({"venue": event.venue, "symbol": event.symbol, "sequence": event.sequence,
                       "received_ms": event.received_ms, **book.features(event.received_ms, max_age_ms)})
    return {"schema_version": 1, "event_count": len(events), "features": output,
            "data_hash": fingerprint([e.model_dump() for e in events])}
