"""Controlled exploratory research audit. Costs and calendars remain explicitly unverified."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from app.quant.schemas import Bar, Profile, AnalysisRequest, Asset
from app.quant.validation import validate_strategy
from app.quant.instruments import specification_fingerprint, classify_instrument


SYMBOLS = (
    "EURUSD", "GBPUSD", "XAUUSD", "Germany 40",
    "Volatility 75 Index", "Crash 1000 Index", "Step Index",
)
TIMEFRAMES = ("M5", "M15", "H1")


def profile_for(info):
    return Profile(
        contract_size=info.trade_contract_size,
        tick_size=info.trade_tick_size,
        tick_value=getattr(info, "trade_tick_value", None),
        point=info.point,
        digits=info.digits,
        volume_min=info.volume_min,
        volume_max=info.volume_max,
        volume_step=info.volume_step,
        profit_currency=getattr(info, "currency_profit", None),
        account_currency="USD",
        calculation_mode=info.trade_calc_mode,
        order_mode=info.order_mode,
        trade_mode=info.trade_mode,
        minimum_stop=getattr(info, "trade_stops_level", 0) * info.point,
        commission_per_lot=0,
        financing_long=0,
        financing_short=0,
        slippage_ticks=0,
        market_impact_ticks_per_lot=0,
        spread_price=None,
        price_basis="bid",
        costs_confirmed=False,
        slippage_confirmed=False,
        specification_confirmed=True,
        specification_source=f"MT5 symbol_info; {getattr(info, 'path', '')}",
        specification_fingerprint=specification_fingerprint(info),
        asset_class=classify_instrument(info, mt5),
        broker_group=getattr(info, "path", "") or "",
    )


def main():
    if mt5 is None:
        print(json.dumps({"error": "MetaTrader5 package unavailable"}))
        return 2
    if not mt5.initialize():
        print(json.dumps({"error": "MT5 initialize failed", "terminal": mt5.last_error()}))
        return 2
    now = datetime.now(timezone.utc)
    output = {}
    for symbol in SYMBOLS:
        info = mt5.symbol_info(symbol)
        if info is None:
            output[symbol] = {"status": "unavailable"}
            continue
        mt5.symbol_select(symbol, True)
        profile = profile_for(info)
        output[symbol] = {"status": "exploratory", "timeframes": {}}
        for timeframe in TIMEFRAMES:
            period = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
            if period is None:
                output[symbol]["timeframes"][timeframe] = {"status": "unsupported"}
                continue
            bars_raw = mt5.copy_rates_from_pos(symbol, period, 0, 3000)
            if bars_raw is None or len(bars_raw) < 300:
                output[symbol]["timeframes"][timeframe] = {
                    "status": "insufficient_history",
                    "count": 0 if bars_raw is None else len(bars_raw),
                }
                continue
            bars = [Bar(
                timestamp=int(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["tick_volume"]),
                spread=float(row["spread"]) * info.point,
            ) for row in bars_raw]
            lookback_days = {"M1": 6, "M5": 30, "M15": 90, "H1": 365}[timeframe]
            request = AnalysisRequest(
                assets=[Asset(symbol=symbol, timeframe=timeframe)],
                timeframe=timeframe,
                days=lookback_days,
                initial_balance=10000,
            )
            try:
                stages = []
                validation = validate_strategy(
                    bars, request, profile, symbol,
                    lambda stage: stages.append(stage),
                )
                output[symbol]["timeframes"][timeframe] = {
                    "status": "exploratory_result",
                    "observations": len(bars),
                    "stages": stages,
                    "cost_model": {
                        "commission_per_lot": 0,
                        "financing": 0,
                        "slippage_ticks": 0,
                        "spread_source": "measured MT5 historical spread",
                        "confirmed": False,
                        "qualified": False,
                    },
                    "session_calendar": "unknown",
                    "validation": validation,
                }
            except Exception as exc:
                output[symbol]["timeframes"][timeframe] = {
                    "status": "validation_error",
                    "observations": len(bars),
                    "error": str(exc),
                    "cost_model_confirmed": False,
                    "session_calendar": "unknown",
                }
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
