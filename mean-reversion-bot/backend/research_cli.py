"""Run bounded research offline without connecting to a broker or database."""
import argparse
import csv
import json
from pathlib import Path
from app.backtesting.research import research_report
from app.core.engine.signal_engine import EngineConfig
from app.core.lsl.lsl_detector import Candle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--balance", type=float, default=1000)
    parser.add_argument("--spread", type=float, default=0)
    parser.add_argument("--slippage", type=float, default=.0005)
    parser.add_argument("--commission", type=float, default=0)
    parser.add_argument("--threshold", type=int, default=6)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new filename")
    with args.csv.open(encoding="utf-8-sig", newline="") as stream:
        candles = [Candle(int(r["timestamp"]), *(float(r[k]) for k in
                    ("open", "high", "low", "close")), float(r.get("volume") or 0))
                   for r in csv.DictReader(stream)]
    report = research_report(candles, EngineConfig(min_confluence=args.threshold),
                             args.symbol, args.timeframe, initial_balance=args.balance,
                             spread_pips=args.spread, slippage_pct=args.slippage, commission=args.commission)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Saved {args.output}; research gate passed: {report['research_gate_passed']}")


if __name__ == "__main__":
    main()
