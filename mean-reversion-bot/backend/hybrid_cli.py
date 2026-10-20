"""Compare the existing MR signals and hybrid variants offline; no broker connection."""
import argparse
import csv
import json
from pathlib import Path

from app.backtesting.hybrid import CampaignBacktester
from app.core.engine.signal_engine import EngineConfig
from app.core.hybrid.campaign import InstrumentSpec
from app.core.hybrid.regime import RegimeConfig
from app.core.hybrid.strategy import HybridConfig
from app.core.lsl.lsl_detector import Candle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", action="append", required=True, metavar="SYMBOL=CSV")
    parser.add_argument("--specs", type=Path, required=True, help="JSON instrument specifications keyed by symbol")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="Optional JSON with engine and hybrid configuration objects")
    parser.add_argument("--balance", type=float, default=10000)
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--base-seconds", type=int, default=300)
    parser.add_argument("--spread", type=float, default=0)
    parser.add_argument("--slippage", type=float, default=.0005)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new filename")
    try:
        specs_json = json.loads(args.specs.read_text(encoding="utf-8-sig"))
        specs = {s: InstrumentSpec(symbol=s, **values) for s, values in specs_json.items()}
        datasets = {}
        for item in args.data:
            symbol, path = item.split("=", 1)
            if symbol in datasets:
                raise ValueError(f"Duplicate dataset: {symbol}")
            with Path(path).open(encoding="utf-8-sig", newline="") as stream:
                datasets[symbol] = [Candle(int(r["timestamp"]), *(float(r[k]) for k in ("open", "high", "low", "close")),
                                           float(r.get("volume") or 0)) for r in csv.DictReader(stream)]
        settings = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
        if set(settings) - {"engine", "hybrid"}:
            raise ValueError("Config accepts only engine and hybrid objects")
        hybrid = settings.get("hybrid", {}).copy()
        if "regime" in hybrid:
            hybrid["regime"] = RegimeConfig(**hybrid["regime"])
        engine = EngineConfig(**settings.get("engine", {}))
        simulator = CampaignBacktester(engine, HybridConfig(**hybrid), args.balance,
                                       args.slippage, args.spread)
        result = simulator.compare(datasets, specs, args.timeframe, args.base_seconds)
        encoded = json.dumps(result, indent=2, allow_nan=False)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    print(f"Saved A-D campaign comparison: {args.output}")
    for variant, instruments in result["variants"].items():
        for symbol, report in instruments.items():
            m = report["metrics"]
            print(f"{variant} {symbol}: campaigns={m['total_trades']} win={m['win_rate']:.1%} "
                  f"PnL={m['total_pnl']:.2f} risk_max={m['maximum_campaign_risk_percent']:.3f}%")


if __name__ == "__main__":
    main()
