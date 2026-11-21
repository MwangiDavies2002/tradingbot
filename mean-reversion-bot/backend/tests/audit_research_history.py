"""Read-only MT5 history and tick-depth audit. Never calls order_send."""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from collections import Counter

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


SYMBOLS = (
    "EURUSD", "GBPUSD", "XAUUSD", "Germany 40",
    "Volatility 75 Index", "Crash 1000 Index", "Step Index",
)
TIMEFRAMES = ("M1", "M5", "M15", "H1")


def audit_candles(symbol, timeframe, bars):
    if bars is None:
        return {"available": False, "count": 0}
    times = [int(row["time"]) for row in bars]
    ordered = sorted(times)
    duplicates = len(times) - len(set(times))
    gaps = sorted(Counter(ordered[i] - ordered[i - 1] for i in range(1, len(ordered))).items())
    spreads = [float(row["spread"]) for row in bars if row["spread"] is not None]
    return {
        "available": True,
        "count": len(bars),
        "first": datetime.fromtimestamp(ordered[0], timezone.utc).isoformat() if ordered else None,
        "last": datetime.fromtimestamp(ordered[-1], timezone.utc).isoformat() if ordered else None,
        "duplicates": duplicates,
        "timestamp_monotonic": times == ordered,
        "timestamp_gap_seconds": [{"gap": gap, "count": count} for gap, count in gaps[:20]],
        "spread_observations": len(spreads),
        "calendar_closed_periods": "unknown",
        "timezone": "UTC broker timestamps",
    }


def main():
    if mt5 is None:
        print(json.dumps({"error": "MetaTrader5 package unavailable"}))
        return 2
    if not mt5.initialize():
        print(json.dumps({"error": "MT5 initialize failed", "terminal": mt5.last_error()}))
        return 2
    now = datetime.now(timezone.utc)
    output = {"captured_at": now.isoformat(), "symbols": {}}
    for symbol in SYMBOLS:
        info = mt5.symbol_info(symbol)
        if info is None:
            output["symbols"][symbol] = {"status": "unavailable"}
            continue
        mt5.symbol_select(symbol, True)
        item = {
            "status": "discovered",
            "path": getattr(info, "path", ""),
            "timeframes": {},
            "ticks": {"status": "unknown"},
        }
        for timeframe in TIMEFRAMES:
            period = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
            bars = mt5.copy_rates_from_pos(symbol, period, 0, 10000) if period is not None else None
            audit = audit_candles(symbol, timeframe, bars)
            audit["maximum_window_count"] = 0 if bars is None else len(bars)
            audit["exact_full_history_depth"] = "not established; bounded 10,000-bar probe"
            item["timeframes"][timeframe] = audit
        tick_end = now
        tick_start = now - timedelta(days=7)
        flags = getattr(mt5, "COPY_TICKS_ALL", 3)
        ticks = mt5.copy_ticks_range(symbol, tick_start, tick_end, flags)
        item["ticks"] = {
            "status": "available" if ticks is not None else "unavailable",
            "count": 0 if ticks is None else len(ticks),
            "first": (datetime.fromtimestamp(int(ticks[0]["time"]), timezone.utc).isoformat()
                      if ticks is not None and len(ticks) else None),
            "last": (datetime.fromtimestamp(int(ticks[-1]["time"]), timezone.utc).isoformat()
                     if ticks is not None and len(ticks) else None),
        }
        output["symbols"][symbol] = item
    print(json.dumps(output, indent=2, sort_keys=True))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
