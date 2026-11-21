"""Read-only MT5 sizing audit; this script never calls order_send or order_check."""
import json
import math
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


SYMBOLS = (
    "EURUSD", "GBPUSD", "XAUUSD", "Germany 40", "US 500",
    "Volatility 75 Index", "Volatility 100 Index", "Crash 1000 Index", "Step Index",
)
TIMEFRAMES = ("M1", "M5", "M15", "H1")


def audit_one(symbol):
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package unavailable")
    info = mt5.symbol_info(symbol)
    if not info:
        return {"symbol": symbol, "status": "unavailable"}
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    result = {
        "symbol": symbol,
        "status": "fully_supported",
        "path": getattr(info, "path", ""),
        "contract_size": getattr(info, "trade_contract_size", None),
        "tick_size": getattr(info, "trade_tick_size", None),
        "tick_value": getattr(info, "trade_tick_value", None),
        "calculation_mode": getattr(info, "trade_calc_mode", None),
        "volume_min": getattr(info, "volume_min", None),
        "volume_max": getattr(info, "volume_max", None),
        "volume_step": getattr(info, "volume_step", None),
        "trade_mode": getattr(info, "trade_mode", None),
        "swap_mode": getattr(info, "swap_mode", None),
        "swap_long": getattr(info, "swap_long", None),
        "swap_short": getattr(info, "swap_short", None),
        "spread": None if tick is None else tick.ask - tick.bid,
        "history": {},
        "profit": {},
        "margin": {},
        "sessions": [],
    }
    for timeframe in TIMEFRAMES:
        period = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        bars = mt5.copy_rates_from_pos(symbol, period, 0, 100) if period is not None else None
        result["history"][timeframe] = None if bars is None else len(bars)
        if bars is None or len(bars) < 100:
            result["status"] = "partially_supported"
    if tick and math.isfinite(tick.bid) and math.isfinite(tick.ask):
        price = tick.ask
        distance = getattr(info, "trade_tick_size", 0) or getattr(info, "point", 0)
        for side_name, side in (
            ("buy", mt5.ORDER_TYPE_BUY),
            ("sell", mt5.ORDER_TYPE_SELL),
        ):
            stop = price - 100 * distance if side_name == "buy" else price + 100 * distance
            for volume in (getattr(info, "volume_min", 0), 1.0):
                if volume is None or volume <= 0:
                    continue
                profit = mt5.order_calc_profit(side, symbol, volume, price, stop)
                margin = mt5.order_calc_margin(side, symbol, volume, price)
                result["profit"].setdefault(side_name, {})[str(volume)] = profit
                result["margin"].setdefault(side_name, {})[str(volume)] = margin
    if hasattr(mt5, "symbol_info_session_trade"):
        sessions = mt5.symbol_info_session_trade(symbol)
        result["sessions"] = [dict(day=s.day, from_hour=s.from_hour, from_min=s.from_min,
                                   to_hour=s.to_hour, to_min=s.to_min) for s in (sessions or [])]
    required = (info.trade_contract_size, info.trade_tick_size, info.trade_tick_value,
                info.volume_min, info.volume_max, info.volume_step)
    if not all(value is not None and math.isfinite(float(value)) and float(value) > 0
               for value in required):
        result["status"] = "unsupported"
    return result


def main():
    if mt5 is None:
        print(json.dumps({"error": "MetaTrader5 package unavailable"}))
        return 2
    if not mt5.initialize():
        print(json.dumps({"error": "MT5 initialize failed", "terminal": mt5.last_error()}))
        return 2
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    output = {
        "account": None if account is None else {"login": account.login, "server": account.server,
                                                 "currency": account.currency, "trade_mode": account.trade_mode},
        "terminal": None if terminal is None else {"connected": terminal.connected,
                                                   "trade_allowed": terminal.trade_allowed,
                                                   "tradeapi_disabled": terminal.tradeapi_disabled},
        "instruments": [audit_one(symbol) for symbol in SYMBOLS],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
