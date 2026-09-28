# Supplied session calendars for the forward scanner

The scanner accepts an optional `calendar` on each asset in the authenticated
local `POST /api/scanner/start` request. This is an API configuration feature;
the dashboard does not yet have a calendar editor. Loading saved scanner settings
preserves calendars already stored on selected assets.

Use an operator/admin key and the existing connected MT5 demo account. Starting
the scanner records hypothetical observations only. Calendar input does not
authorize broker orders or change demo execution settings.

## Calendar contract

All times are integer Unix seconds in UTC. Supply the complete set of open
windows for the declared validity period. Times outside these windows within
that period are treated as scheduled closures. Convert broker-local schedules,
DST changes, holidays and early closes explicitly before submitting them.
The application does not download or independently verify the source schedule.

| Field | Meaning |
| --- | --- |
| `scope` | Exact `server:account` scope shown in scanner observations |
| `symbol` | Exact selected broker symbol, including suffixes |
| `source` | Broker schedule or other source reference; cannot be blank |
| `revision` | Supplied calendar revision; cannot be blank |
| `published_at` | Source publication time, no later than observation time |
| `valid_from`, `valid_until` | Coverage start inclusive, end exclusive |
| `windows` | 1–1000 ordered `{ "open": ..., "close": ... }` intervals |

Windows must be nonempty, inside coverage, and separated. Merge adjacent windows;
overlapping or unordered windows are rejected. Both endpoints must align with the
selected timeframe's UTC grid. Partial candles and broker grids that do not align
with this UTC grid are unsupported and rejected.

For example, the following **synthetic test fixture** illustrates the asset shape.
Its epoch-era dates are expired and it must not be used as a current broker schedule:

```json
{
  "assets": [{
    "symbol": "EURUSD.a",
    "calendar": {
      "scope": "demo:1",
      "symbol": "EURUSD.a",
      "source": "synthetic test fixture; not a broker calendar",
      "revision": "test-r1",
      "published_at": 0,
      "valid_from": 0,
      "valid_until": 7200,
      "windows": [{"open": 0, "close": 1800}, {"open": 3600, "close": 7200}]
    }
  }],
  "timeframe": "M5",
  "threshold": 6
}
```

Omit `calendar` or set it to `null` to retain strict recent-candle gap handling.
No default market hours, provider aliases or weekend exceptions are guessed.

## Observations and paper outcomes

- Supplied calendars must cover the entire returned candle history (up to 500
  closed bars) and observation time. Every history candle must be inside an open
  window; any missing scheduled candle blocks the observation. Scheduled closures
  may separate adjacent returned candles. Current time must be in an open window,
  and the existing fresh-candle and quote checks still apply.
- New hypothetical entry waits for the first full scheduled candle starting after
  observation. If the supplied calendar has no remaining slot, the observation is
  retained as rejected. Supplying a calendar does not relax other signal gates.
- The exact calendar and `explicit_utc_v1` continuity model are pinned in the
  observation/trade policy and included in its fingerprint. Changing source,
  revision or windows creates a different evidence policy. Exports and saved
  evidence retain this provenance; rejected calendar checks retain the input too.
- Existing paper trades use their pinned calendar. Scheduled closures do not
  count toward held bars. A reopening price gap still uses the existing adverse
  stop-fill rules. Missing scheduled outcome bars or expired coverage leave an
  unfinished trade unresolved. No new calendar retroactively repairs a trade.
- Valid closed history can resolve existing paper outcomes even when fresh-entry
  checks reject a stale quote or closed session. Invalid, forming/future candles
  and account changes cannot advance the ledger.
- Stopping or restarting still leaves unfinished exposure unresolved; it does not
  resume scanning. Historical trades without calendars keep their prior gap rules.

This remains a fixed-spread, ATR-slippage, tick-rounded hypothetical model.
It does not model session-dependent spreads, financing, holiday costs or broker
fills. Six-hour UTC analytics buckets remain time buckets, not named sessions.
Automatic broker-calendar ingestion and calendar editing in the UI remain pending.
