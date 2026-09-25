"""Session audits and cross-asset statistics with no price filling."""
from datetime import datetime, timezone
from itertools import combinations
import math
import warnings
from zoneinfo import ZoneInfo

import numpy as np
from statsmodels.tsa.stattools import adfuller, coint
from app.data.validation import validate_candles


def is_session(ts, session):
    local = datetime.fromtimestamp(ts, ZoneInfo(session.timezone))
    minute = local.hour * 60 + local.minute
    return (local.weekday() in session.weekdays and local.date() not in session.holidays
            and session.open_minute <= minute < session.early_closes.get(local.date(), session.close_minute))


def audit(bars, interval, session, start, end):
    validate_candles(bars)
    actual = {b.timestamp for b in bars}
    expected = {t for t in range(start, end, interval) if is_session(t, session)}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    return {'bars': len(bars), 'expected_bars': len(expected), 'missing_bars': len(missing),
            'missing_examples': missing[:30], 'outside_session_or_grid': len(unexpected),
            'coverage': len(actual & expected) / len(expected) if expected else 0,
            'session_confirmed': session.confirmed, 'start': start, 'end_exclusive': end,
            'passed': bool(expected) and not missing and not unexpected and session.confirmed,
            'note': 'No candles are filled or invented. Missing counts use the supplied session, holidays and early closes.'}


def returns(bars, interval):
    # A gap is excluded, not bridged into a multi-period return.
    return {b.timestamp: b.close / a.close - 1 for a, b in zip(bars, bars[1:])
            if b.timestamp - a.timestamp == interval}


def coefficient(x, y):
    if len(x) < 3 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return None
    value = float(np.corrcoef(x, y)[0, 1])
    return max(-1., min(1., value)) if math.isfinite(value) else None


def relationships(series, interval, minimum=100, window=60, exposures=None):
    names = sorted(series)
    ret = {s: returns(series[s], interval) for s in names}
    prices = {s: {b.timestamp: b.close for b in series[s]} for s in names}
    pairs, matrix = [], {s: {} for s in names}
    for s in names:
        vals = list(ret[s].values())
        matrix[s][s] = 1. if len(vals) >= minimum and np.std(vals) >= 1e-12 else None
    for a, b in combinations(names, 2):
        times = sorted(ret[a].keys() & ret[b].keys())
        x, y = [ret[a][t] for t in times], [ret[b][t] for t in times]
        rho = coefficient(x, y) if len(times) >= minimum else None
        rolling = []
        for i in range(window - 1, len(times)):
            # Do not silently roll over unmatched/missing observations.
            segment = times[i-window+1:i+1]
            contiguous = all(v-u == interval for u, v in zip(segment, segment[1:]))
            r = coefficient(x[i-window+1:i+1], y[i-window+1:i+1]) if contiguous else None
            rolling.append({'timestamp': times[i], 'correlation': r})
        # Bound serialized points while retaining a real window calculation at each point.
        stride = max(1, math.ceil(len(rolling) / 400))
        row = {'a': a, 'b': b, 'correlation': rho, 'overlap': len(times),
               'unmatched_returns': len(ret[a]) + len(ret[b]) - 2 * len(times),
               'rolling': rolling[::stride], 'rolling_window': window,
               'status': 'ok' if rho is not None else 'insufficient_overlap_or_constant_returns'}
        common = sorted(prices[a].keys() & prices[b].keys())
        # Test only the longest uninterrupted price block; test assumptions are explicit.
        blocks = [[]]
        for t in common:
            if blocks[-1] and t - blocks[-1][-1] != interval:
                blocks.append([])
            blocks[-1].append(t)
        block = max(blocks, key=len)
        coin = {'status': 'insufficient_contiguous_history', 'observations': len(block), 'p_value': None}
        if len(block) >= max(minimum, 100):
            lx, ly = np.log([prices[a][t] for t in block]), np.log([prices[b][t] for t in block])
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error')
                    level_p = [float(adfuller(z, maxlag=5, autolag='AIC')[1]) for z in (lx, ly)]
                    diff_p = [float(adfuller(np.diff(z), maxlag=5, autolag='AIC')[1]) for z in (lx, ly)]
                    if min(level_p) <= .05 or max(diff_p) >= .05:
                        coin.update(status='integration_assumptions_not_supported', level_adf_p=level_p, difference_adf_p=diff_p)
                    else:
                        stat, pvalue, _ = coint(lx, ly, trend='c', maxlag=5, autolag='aic')
                        beta, intercept = np.polyfit(ly, lx, 1)
                        if not all(math.isfinite(v) for v in (stat, pvalue, beta, intercept)):
                            raise ValueError('Degenerate series')
                        coin.update(status='tested', p_value=float(pvalue), statistic=float(stat),
                                    hedge_ratio=float(beta), intercept=float(intercept),
                                    start=block[0], end=block[-1])
            except (ValueError, Warning, np.linalg.LinAlgError):
                coin.update(status='degenerate_or_unstable_series')
        row['cointegration'] = coin
        matrix[a][b] = matrix[b][a] = rho
        pairs.append(row)
    # Holm controls familywise false positives without independence assumptions.
    tested = sorted([p for p in pairs if p['cointegration']['p_value'] is not None],
                    key=lambda p: p['cointegration']['p_value'])
    bound = 0.
    for i, row in enumerate(tested):
        coin = row['cointegration']
        bound = max(bound, min(1., coin['p_value'] * (len(pairs) - i)))
        coin.update(adjusted_p_value=bound, evidence_of_cointegration=bound < .05)
    exposures = exposures or {}
    alerts = []
    for row in pairs:
        a, b, rho = row['a'], row['b'], row['correlation']
        if rho is not None and abs(rho) >= .7:
            same_risk = rho * exposures.get(a, 0) * exposures.get(b, 0) > 0
            alerts.append({'a': a, 'b': b, 'correlation': rho,
                           'kind': 'overlapping_directional_exposure' if same_risk else 'strong_relationship',
                           'message': 'Positions reinforce the same market movement' if same_risk else 'Check directions and sizes before combining these assets'})
    ranked = [p for p in pairs if p['correlation'] is not None]
    return {'symbols': names, 'matrix': matrix, 'pairs': pairs,
            'positive': sorted([p for p in ranked if p['correlation'] > 0], key=lambda p: -p['correlation'])[:10],
            'negative': sorted([p for p in ranked if p['correlation'] < 0], key=lambda p: p['correlation'])[:10],
            'exposure_warnings': alerts, 'exposures': exposures,
            'method': 'Pearson correlation of exact timestamp-aligned, one-bar percentage returns; no forward fill',
            'cointegration_method': 'Engle–Granger on log prices, constant, AIC lags <=5; ADF integration screening; Holm adjustment across all selected pairs',
            'note': 'Exploratory relationships, not a pairs-trading strategy. Correlation and cointegration can change. Exposure warnings are directional, not portfolio VaR.'}
