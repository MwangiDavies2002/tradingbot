"""Explicit operator-supplied UTC sessions; no inferred broker schedules."""
from pydantic import Field, model_validator

from app.quant.schemas import Record


class ScanWindow(Record):
    open: int = Field(ge=0, strict=True)
    close: int = Field(gt=0, strict=True)


class ScanCalendar(Record):
    scope: str = Field(min_length=1, max_length=256)
    symbol: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=500)
    revision: str = Field(min_length=1, max_length=128)
    published_at: int = Field(ge=0, strict=True)
    valid_from: int = Field(ge=0, strict=True)
    valid_until: int = Field(gt=0, strict=True)
    windows: list[ScanWindow] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def valid(self):
        if any(not s.strip() for s in (self.scope, self.symbol, self.source, self.revision)):
            raise ValueError('Calendar identity and provenance must not be blank')
        if self.valid_from >= self.valid_until:
            raise ValueError('Calendar validity must be increasing')
        if any(not self.valid_from <= w.open < w.close <= self.valid_until for w in self.windows):
            raise ValueError('Session windows must be nonempty and within calendar validity')
        if any(a.close >= b.open for a, b in zip(self.windows, self.windows[1:])):
            raise ValueError('Session windows must be ordered and separated; merge adjacent windows')
        return self

    def check_identity(self, scope, symbol, now):
        if self.scope != scope or self.symbol != symbol:
            raise ValueError('Session calendar does not match the exact broker account and symbol')
        if self.published_at > now:
            raise ValueError('Session calendar was not yet published at observation time')
        if not self.valid_from <= now < self.valid_until:
            raise ValueError('Session calendar does not cover observation time')

    def check_grid(self, interval):
        if any(w.open % interval or w.close % interval for w in self.windows):
            raise ValueError('Session boundaries must align with the selected UTC candle grid')

    def contains(self, timestamp, interval):
        return timestamp % interval == 0 and any(w.open <= timestamp and timestamp + interval <= w.close for w in self.windows)

    def next_bar(self, earliest, interval):
        """Return a full candle slot within explicit coverage, or fail closed."""
        if earliest < self.valid_from or earliest >= self.valid_until:
            raise ValueError('Session calendar coverage exhausted')
        for window in self.windows:
            candidate = max(window.open, ((earliest + interval - 1) // interval) * interval)
            if candidate + interval <= window.close:
                return candidate
        raise ValueError('No next candle in supplied session calendar')

    def check_history(self, bars, interval):
        if any(not self.contains(b.timestamp, interval) for b in bars):
            raise ValueError('Candle outside supplied sessions or calendar coverage')
        if any(self.next_bar(a.timestamp + interval, interval) != b.timestamp for a, b in zip(bars, bars[1:])):
            raise ValueError('Missing candle inside a supplied open session')
