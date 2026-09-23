"""Scenario risk for linear positions in one reporting currency.

Historical returns are aligned simple returns for one common observation period.
No square-root time scaling, FX conversion or regulatory capital claim is made.
"""
import math

import numpy as np
from pydantic import Field, model_validator

from app.institutional.data import Record


class Position(Record):
    symbol: str = Field(min_length=1, max_length=64)
    market_value: float = Field(ge=-1e15, le=1e15)
    counterparty: str = Field(min_length=1, max_length=64)
    factor_betas: dict[str, float] = Field(default_factory=dict, max_length=30)


class PortfolioRequest(Record):
    currency: str = Field(min_length=3, max_length=3)
    equity: float = Field(gt=0, le=1e15)
    positions: list[Position] = Field(min_length=1, max_length=30)
    returns: dict[str, list[float]] = Field(min_length=1, max_length=30)
    confidence: float = Field(default=.975, gt=.5, lt=1)
    scenarios: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=30)
    gross_limit: float = Field(default=1, gt=0, le=100)
    net_limit: float = Field(default=1, gt=0, le=100)
    symbol_limit: float = Field(default=.25, gt=0, le=100)
    counterparty_limit: float = Field(default=.5, gt=0, le=100)
    factor_limits: dict[str, float] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def validate_alignment(self):
        symbols = {p.symbol for p in self.positions}
        if set(self.returns) != symbols:
            raise ValueError("Return histories must exactly cover the position symbols")
        lengths = {len(r) for r in self.returns.values()}
        if len(lengths) != 1 or not 20 <= next(iter(lengths)) <= 10000:
            raise ValueError("Require 20-10000 aligned return observations per symbol")
        if any(not -1 <= r <= 1000 for values in self.returns.values() for r in values):
            raise ValueError("Simple asset returns must be between -1 and 1000")
        if any(abs(beta) > 1e6 for p in self.positions for beta in p.factor_betas.values()):
            raise ValueError("Factor beta exceeds supported numerical range")
        for shocks in self.scenarios.values():
            if set(shocks) != symbols or any(not -1 <= s <= 1000 for s in shocks.values()):
                raise ValueError("Each scenario must cover all symbols with valid simple returns")
        if any(limit <= 0 for limit in self.factor_limits.values()):
            raise ValueError("Factor limits must be positive fractions of equity")
        for factor in self.factor_limits:
            if any(factor not in p.factor_betas for p in self.positions):
                raise ValueError("Every position requires an explicit beta for each limited factor")
        return self


def tail_risk(pnl: np.ndarray, confidence: float) -> dict:
    losses = np.sort(-np.asarray(pnl, dtype=float))[::-1]
    if losses.ndim != 1 or not len(losses) or not np.isfinite(losses).all() or not .5 < confidence < 1:
        raise ValueError("Invalid PnL sample or confidence")
    # Fractional empirical tail mass prevents ties/quantile interpolation from
    # silently changing the requested tail probability.
    mass = len(losses) * (1 - confidence)
    whole = int(math.floor(mass))
    fractional = mass - whole
    tail_sum = float(losses[:whole].sum())
    if fractional:
        tail_sum += fractional * float(losses[whole])
    var = float(np.quantile(losses, confidence, method="inverted_cdf"))
    return {"var": max(0.0, var), "expected_shortfall": max(0.0, tail_sum / mass),
            "confidence": confidence, "observations": len(losses), "tail_observation_mass": mass,
            "tail_sample_warning": mass < 10}


def portfolio_risk(request: PortfolioRequest) -> dict:
    values: dict[str, float] = {}
    counterparties: dict[str, float] = {}
    factors: dict[str, float] = {}
    for position in request.positions:
        values[position.symbol] = values.get(position.symbol, 0) + position.market_value
        counterparties[position.counterparty] = counterparties.get(position.counterparty, 0) + abs(position.market_value)
        for name, beta in position.factor_betas.items():
            factors[name] = factors.get(name, 0) + position.market_value * beta
    symbols = sorted(values)
    matrix = np.array([request.returns[s] for s in symbols], dtype=float).T
    exposures = np.array([values[s] for s in symbols])
    pnl = matrix @ exposures
    gross = sum(abs(p.market_value) for p in request.positions)
    net = sum(values.values())
    # Gross per symbol avoids hiding offsetting positions held across brokers.
    symbol_gross = {s: sum(abs(p.market_value) for p in request.positions if p.symbol == s) for s in symbols}
    checks = {"gross": gross <= request.equity * request.gross_limit,
              "net": abs(net) <= request.equity * request.net_limit}
    checks.update({f"symbol:{s}": v <= request.equity * request.symbol_limit for s, v in symbol_gross.items()})
    checks.update({f"counterparty:{c}": v <= request.equity * request.counterparty_limit for c, v in counterparties.items()})
    checks.update({f"factor:{f}": abs(factors[f]) <= request.equity * limit for f, limit in request.factor_limits.items()})
    scenarios = {name: sum(values[s] * shocks[s] for s in symbols) for name, shocks in request.scenarios.items()}
    covariance = np.atleast_2d(np.cov(matrix, rowvar=False, ddof=1))
    sd = np.sqrt(np.diag(covariance))
    denom = np.outer(sd, sd)
    correlation = np.divide(covariance, denom, out=np.zeros_like(covariance), where=denom > 0)
    corr_json = [[float(correlation[i, j]) if denom[i, j] > 0 else None
                  for j in range(len(symbols))] for i in range(len(symbols))]
    return {"currency": request.currency, "horizon": "one supplied return observation",
            **tail_risk(pnl, request.confidence), "gross_exposure": gross, "net_exposure": net,
            "gross_leverage": gross / request.equity, "symbol_gross": symbol_gross,
            "counterparty_gross": counterparties, "factor_exposure": factors,
            "scenario_pnl": scenarios, "symbols": symbols, "correlation": corr_json,
            "period_pnl_std": float(np.std(pnl, ddof=1)), "checks": checks,
            "limits_passed": all(checks.values()), "live_authorized": False,
            "limitations": ["Fixed linear exposures; options need full repricing or Greeks.",
                            "Counterparty gross is a concentration proxy, not credit exposure or regulatory capital.",
                            "Returns must already be aligned in time and currency; sample risk is not a forecast."]}


class AllocationRequest(Record):
    returns: dict[str, list[float]] = Field(min_length=1, max_length=30)
    max_weight: float = Field(default=.25, gt=0, le=1)
    gross_budget: float = Field(default=1, gt=0, le=1)
    previous_weights: dict[str, float] = Field(default_factory=dict, max_length=30)
    max_turnover: float = Field(default=1, ge=0, le=2)


def allocate(request: AllocationRequest) -> dict:
    symbols = sorted(request.returns)
    lengths = {len(v) for v in request.returns.values()}
    if len(lengths) != 1 or not 20 <= next(iter(lengths)) <= 10000:
        raise ValueError("Require 20-10000 aligned observations per asset")
    if any(not -1 <= r <= 1000 for values in request.returns.values() for r in values):
        raise ValueError("Invalid simple returns")
    if set(request.previous_weights) - set(symbols):
        raise ValueError("Previous weights contain an unknown asset")
    old = np.array([request.previous_weights.get(s, 0) for s in symbols])
    if (old < 0).any() or (old > request.max_weight).any() or old.sum() > request.gross_budget + 1e-12:
        raise ValueError("Previous portfolio violates caps; explicit liquidation planning is required")
    matrix = np.array([request.returns[s] for s in symbols]).T
    sd = np.std(matrix, axis=0, ddof=1)
    inverse = np.divide(1.0, sd, out=np.zeros_like(sd), where=sd > 1e-12)
    weights = np.zeros(len(symbols))
    active = inverse > 0
    budget = request.gross_budget
    while active.any() and budget > 1e-12:
        proposal = budget * inverse[active] / inverse[active].sum()
        indices = np.flatnonzero(active)
        capped = proposal >= request.max_weight
        if not capped.any():
            weights[indices] = proposal
            break
        chosen = indices[capped]
        weights[chosen] = request.max_weight
        budget -= len(chosen) * request.max_weight
        active[chosen] = False
    turnover = float(np.abs(weights - old).sum())
    if turnover > request.max_turnover:
        weights = old + (weights - old) * request.max_turnover / turnover
    covariance = np.atleast_2d(np.cov(matrix, rowvar=False, ddof=1))
    return {"method": "long-only capped inverse volatility", "weights": dict(zip(symbols, weights.tolist())),
            "cash_weight": max(0.0, 1 - float(weights.sum())),
            "turnover_l1": float(np.abs(weights - old).sum()),
            "estimated_period_volatility": math.sqrt(max(0, float(weights @ covariance @ weights))),
            "zero_variance_assets": [s for s, v in zip(symbols, sd) if v <= 1e-12],
            "live_authorized": False,
            "limitation": "No expected-return optimization; covariance is estimated on supplied training data only. Cash earns zero."}
