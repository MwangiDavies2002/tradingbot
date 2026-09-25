"""Chronological validation of frozen strategies with a final untouched holdout."""
from dataclasses import asdict, replace
from app.backtesting.research import monte_carlo
from app.core.engine.signal_engine import EngineConfig
from app.execution.mt5_demo import DemoConfig
from app.quant.contracts import ContractBacktest


def validate_strategy(bars, request, profile, symbol, progress):
    values = request.strategy.model_dump(exclude={'symbol', 'timeframe', 'daily_loss_pct'})
    base = EngineConfig(**values, cb_daily_dd=request.strategy.daily_loss_pct)
    thresholds = sorted({max(1, base.min_confluence-1), base.min_confluence, min(20, base.min_confluence+1)})
    candidates = [replace(base, min_confluence=t) for t in thresholds]
    boundary = int(len(bars)*.8)
    development = bars[:boundary]
    if len(development) < 240 or len(bars)-boundary < 60:
        raise ValueError('At least 300 candles are required for walk-forward and final holdout validation')
    folds, oos = [], []
    def simulate(data, config, stress=1):
        return ContractBacktest(config, profile, request.initial_balance, stress).run(data, symbol, request.timeframe)
    # Reuse the existing expanding-window selection rule, now with contract cash accounting.
    initial = len(development)//2
    step = (len(development)-initial)//3
    for fold in range(3):
        progress(f'Walk-forward fold {fold+1}/3')
        split, end = initial+fold*step, (len(development) if fold == 2 else initial+(fold+1)*step)
        training = [simulate(development[:split], c) for c in candidates]
        viable = [i for i, r in enumerate(training) if r.total_trades >= 5]
        if not viable:
            folds.append({'fold': fold+1, 'status': 'insufficient_training_trades'})
            continue
        best = max(viable, key=lambda i: training[i].total_pnl_pct-training[i].max_drawdown_pct)
        # Warmup is past-only; first evaluation is at split, first fill strictly after it.
        report = simulate(development[split-60:end], candidates[best])
        oos.extend(t.pnl for t in report.trades)
        folds.append({'fold': fold+1, 'status': 'tested', 'threshold': candidates[best].min_confluence,
                      'train_end': development[split-1].timestamp, 'test_start': development[split].timestamp,
                      'test_end': development[end-1].timestamp, 'report': report.to_dict()})
    progress('Freeze strategy on development data')
    training = [simulate(development, c) for c in candidates]
    viable = [i for i, r in enumerate(training) if r.total_trades >= 5]
    best = max(viable, key=lambda i: training[i].total_pnl_pct-training[i].max_drawdown_pct) if viable else 0
    chosen = candidates[best]
    progress('Final untouched holdout and doubled-cost stress')
    holdout = simulate(bars[boundary-60:], chosen)
    stress = simulate(bars[boundary-60:], chosen, 2)
    gains, losses = sum(p for p in oos if p > 0), -sum(p for p in oos if p < 0)
    pf = gains/losses if losses else None
    checks = {'training_has_trades': bool(viable), 'all_walk_forward_folds_tested': len([f for f in folds if f['status']=='tested']) == 3,
              'at_least_100_walk_forward_trades': len(oos) >= 100,
              'walk_forward_positive': sum(oos) > 0,
              'walk_forward_profit_factor_1_2': pf is not None and pf >= 1.2,
              'holdout_at_least_20_trades': holdout.total_trades >= 20,
              'holdout_positive': holdout.total_pnl > 0,
              'holdout_profit_factor_1_2': holdout.profit_factor >= 1.2,
              'holdout_drawdown_below_20_percent': holdout.max_drawdown_pct < .2,
              'doubled_cost_holdout_positive': stress.total_pnl > 0}
    config = request.strategy.model_dump()
    config.update(symbol=symbol, timeframe=request.timeframe, min_confluence=chosen.min_confluence)
    return {'folds': folds, 'holdout_start': bars[boundary].timestamp, 'holdout': holdout.to_dict(),
            'holdout_cost_stress': stress.to_dict(), 'checks': checks, 'passed': all(checks.values()),
            'selected_strategy': DemoConfig(**config).model_dump(), 'oos_trades': len(oos), 'oos_pnl': sum(oos),
            'oos_profit_factor': pf, 'monte_carlo': monte_carlo(oos, request.initial_balance),
            'selection_rule': 'Development return minus drawdown, >=5 training trades; thresholds predeclared before fetching data',
            'note': 'Final 20% is not used for selection. Repeatedly tuning against this report invalidates its holdout status. Independent demo observation is still required.'}
