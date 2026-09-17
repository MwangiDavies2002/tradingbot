"""Offline validation: train-only selection, chronological tests and seeded stress runs."""
from dataclasses import asdict, replace
import numpy as np

from app.backtesting.backtest_engine import BacktestEngine
from app.core.engine.signal_engine import SignalEngine
from app.data.validation import validate_candles


def simulate(candles, config, symbol, timeframe, **costs):
    return BacktestEngine(SignalEngine(config), **costs).run(candles, symbol, timeframe)


def walk_forward(candles, candidates, n_splits=3, symbol="", timeframe="", **costs):
    validate_candles(candles)
    if not 2 <= n_splits <= 10 or not 1 <= len(candidates) <= 20:
        raise ValueError("Use 2–10 folds and 1–20 candidates")
    warmup = costs.get("warmup_bars", 60)
    initial_train = len(candles) // 2
    test_size = (len(candles) - initial_train) // n_splits
    if initial_train <= warmup + 20 or test_size < 20:
        raise ValueError("More data is required for chronological validation")
    reports, folds = [], []
    for fold in range(n_splits):
        split = initial_train + fold * test_size
        end = len(candles) if fold == n_splits - 1 else split + test_size
        training = [simulate(candles[:split], c, symbol, timeframe, **costs) for c in candidates]
        # Empty training samples cannot win by avoiding all risk.
        viable = [i for i, report in enumerate(training) if report.total_trades >= 5]
        if not viable:
            folds.append({"fold": fold + 1, "status": "insufficient_training_trades",
                          "train_end": candles[split - 1].timestamp})
            continue
        best = max(viable, key=lambda i: training[i].total_pnl_pct - training[i].max_drawdown_pct)
        # Past bars only warm indicators; all test fills occur after the split.
        report = simulate(candles[split - warmup:end], candidates[best], symbol, timeframe, **costs)
        reports.append(report)
        folds.append({"fold": fold + 1, "status": "tested", "selected_config": asdict(candidates[best]),
                      "train_end": candles[split - 1].timestamp, "test_start": candles[split].timestamp,
                      "test_end": candles[end - 1].timestamp, "result": report.to_dict()})
    return {"folds": folds, "reports": reports,
            "selection_rule": "training return minus drawdown; at least 5 training trades"}


def monte_carlo(pnls, initial_balance, simulations=1000, seed=42):
    if not 100 <= simulations <= 10000 or initial_balance <= 0:
        raise ValueError("Invalid simulation count or balance")
    if not pnls:
        return {"status": "insufficient_trades", "seed": seed}
    values = np.asarray(pnls, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("Non-finite PnL")
    rng = np.random.default_rng(seed)
    drawdowns, endings = [], []
    for _ in range(simulations):
        # Sampling with replacement measures path and outcome uncertainty.
        path = np.r_[initial_balance, initial_balance + np.cumsum(rng.choice(values, len(values)))]
        peak = np.maximum.accumulate(path)
        drawdowns.append(float(np.max((peak - path) / peak)))
        endings.append(float(path[-1]))
    return {"seed": seed, "simulations": simulations, "method": "IID cash-PnL bootstrap",
            "drawdown_p95": float(np.quantile(drawdowns, .95)),
            "ending_balance_p05": float(np.quantile(endings, .05)),
            "loss_probability": float(np.mean(np.array(endings) < initial_balance)),
            "limitation": "Assumes independent trades and fixed cash sizing; not a forecast"}


def research_report(candles, config, symbol, timeframe, folds=3, **costs):
    candidates = [replace(config, min_confluence=n) for n in
                  sorted({max(1, config.min_confluence - 1), config.min_confluence,
                          config.min_confluence + 1})]
    wf = walk_forward(candles, candidates, folds, symbol, timeframe, **costs)
    reports = wf.pop("reports")
    pnls = [t.pnl for r in reports for t in r.trades]
    trade_count = len(pnls)
    gains = sum(p for p in pnls if p > 0); losses = -sum(p for p in pnls if p < 0)
    pf = gains / losses if losses else None
    positive_folds = sum(r.total_pnl > 0 for r in reports)
    checks = {
        "all_folds_tested": len(reports) == folds,
        "at_least_100_oos_trades": trade_count >= 100,
        "positive_oos_pnl": sum(pnls) > 0,
        "oos_profit_factor_at_least_1_2": pf is not None and pf >= 1.2,
        "at_least_70_percent_positive_folds": positive_folds >= np.ceil(folds * .7),
        "oos_drawdown_below_20_percent": bool(reports) and max(r.max_drawdown_pct for r in reports) < .2,
    }
    # Ablations and cost sensitivity are diagnostics on the TRAINING half only.
    training = candles[:len(candles) // 2]
    ablations = {}
    for name, enabled in asdict(config).items():
        if name.startswith("use_") and enabled and name not in {"use_safety_orders", "use_trailing_stop"}:
            ablations[name] = simulate(training, replace(config, **{name: False}), symbol, timeframe, **costs).to_dict()
    stress_costs = dict(costs)
    stress_costs["slippage_pct"] = max(costs.get("slippage_pct", .0005) * 2, .001)
    stress_costs["spread_pips"] = costs.get("spread_pips", 0) * 2
    stress_costs["commission"] = costs.get("commission", 0) * 2
    stress = simulate(training, config, symbol, timeframe, **stress_costs)
    return {**wf, "oos_trade_count": trade_count, "oos_pnl": sum(pnls),
            "oos_profit_factor": pf, "checks": {k: bool(v) for k, v in checks.items()},
            "research_gate_passed": all(checks.values()),
            "training_ablations": ablations, "training_cost_stress": stress.to_dict(),
            "monte_carlo": monte_carlo(pnls, costs.get("initial_balance", 1000)),
            "live_authorized": False,
            "note": "Research gates do not enable trading. Require separate demo execution validation."}
