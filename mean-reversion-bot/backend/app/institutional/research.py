"""Expanding-window ridge experiments with label-availability purging."""
import numpy as np
from pydantic import Field, model_validator

from app.institutional.data import Record, fingerprint


class Sample(Record):
    decision_ms: int = Field(ge=0, strict=True)
    features_available_ms: int = Field(ge=0, strict=True)
    target_available_ms: int = Field(ge=0, strict=True)
    features: list[float] = Field(min_length=1, max_length=30)
    target_return: float = Field(ge=-1, le=1000)

    @model_validator(mode="after")
    def temporal_order(self):
        if self.features_available_ms > self.decision_ms or self.target_available_ms <= self.decision_ms:
            raise ValueError("Features must be known at decision time and targets strictly afterward")
        if any(abs(v) > 1e12 for v in self.features):
            raise ValueError("Features exceed supported numerical range")
        return self


class ExperimentRequest(Record):
    name: str = Field(min_length=1, max_length=128)
    samples: list[Sample] = Field(min_length=60, max_length=5000)
    feature_names: list[str] = Field(min_length=1, max_length=30)
    folds: int = Field(default=3, ge=2, le=5, strict=True)
    ridge_penalty: float = Field(default=1, ge=.000001, le=1e6)
    cost_bps: float = Field(default=5, ge=0, le=1000)
    embargo_ms: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def alignment(self):
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("Feature names must be unique")
        if any(len(s.features) != len(self.feature_names) for s in self.samples):
            raise ValueError("Feature dimensions differ")
        if any(b.decision_ms <= a.decision_ms for a, b in zip(self.samples, self.samples[1:])):
            raise ValueError("Samples must be strictly chronological")
        return self


def experiment(request: ExperimentRequest) -> dict:
    samples = request.samples
    x = np.array([s.features for s in samples])
    y = np.array([s.target_return for s in samples])
    initial = len(samples) // 2
    partitions = np.array_split(np.arange(initial, len(samples)), request.folds)
    reports = []
    predictions, actuals, net_returns = [], [], []
    for fold, indices in enumerate(partitions, 1):
        start = int(indices[0])
        cutoff = samples[start].decision_ms - request.embargo_ms
        train = np.array([i for i in range(start) if samples[i].target_available_ms < cutoff])
        if len(train) < max(20, x.shape[1] + 2):
            raise ValueError("Insufficient label-available training samples after purge/embargo")
        mean, scale = x[train].mean(axis=0), x[train].std(axis=0)
        scale[scale < 1e-12] = 1
        design = np.column_stack((np.ones(len(train)), (x[train] - mean) / scale))
        penalty = np.eye(design.shape[1]) * request.ridge_penalty
        penalty[0, 0] = 0  # Intercept is not regularized.
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ y[train])
        test = np.column_stack((np.ones(len(indices)), (x[indices] - mean) / scale))
        predicted = test @ beta
        positions = np.sign(predicted)
        turnover = np.abs(np.diff(np.r_[0, positions]))
        turnover[-1] += abs(positions[-1])  # Close each independent fold.
        net = positions * y[indices] - turnover * request.cost_bps / 10000
        reports.append({"fold": fold, "training_samples": len(train), "purged_samples": start - len(train),
                        "training_last_target_ms": max(samples[i].target_available_ms for i in train),
                        "test_start_ms": samples[start].decision_ms, "test_end_ms": samples[int(indices[-1])].decision_ms,
                        "mse": float(np.mean((predicted - y[indices]) ** 2)),
                        "training_mean_baseline_mse": float(np.mean((y[train].mean() - y[indices]) ** 2)),
                        "net_return_sum": float(net.sum()), "turnover_l1": float(turnover.sum()),
                        "training_feature_mean": mean.tolist(), "training_feature_scale": scale.tolist(),
                        "standardized_coefficients": beta.tolist()})
        predictions.extend(predicted.tolist())
        actuals.extend(y[indices].tolist())
        net_returns.extend(net.tolist())
    payload = request.model_dump()
    return {"name": request.name, "model": "ridge next-return regression", "folds": reports,
            "predictions": predictions, "actuals": actuals, "net_returns": net_returns,
            "net_return_sum": sum(net_returns), "oos_samples": len(predictions),
            "experiment_hash": fingerprint(payload), "live_authorized": False,
            "limitations": ["Targets are supplied by the caller; verify availability timestamps and non-overlapping holding periods.",
                            "Net-return sum is an arithmetic diagnostic, not compounded portfolio equity.",
                            "Costs are a fixed one-way bps scenario; no capacity or fill model.",
                            "Repeatedly choosing models after viewing these folds invalidates their holdout status."]}


class MultipleTestingRequest(Record):
    p_values: dict[str, float] = Field(min_length=1, max_length=10000)
    false_discovery_rate: float = Field(default=.05, gt=0, lt=1)


def adjust_tests(request: MultipleTestingRequest) -> dict:
    if any(not 0 <= p <= 1 for p in request.p_values.values()):
        raise ValueError("P-values must be in [0, 1]")
    ordered = sorted(request.p_values, key=request.p_values.get)
    adjusted = {}
    bound = 1.0
    for i in range(len(ordered) - 1, -1, -1):
        name = ordered[i]
        bound = min(bound, request.p_values[name] * len(ordered) / (i + 1))
        adjusted[name] = bound
    return {"method": "Benjamini-Hochberg", "adjusted_p_values": adjusted,
            "discoveries": [name for name in ordered if adjusted[name] <= request.false_discovery_rate],
            "limitation": "Requires valid pre-specified tests and independence or suitable positive dependence; does not repair backtest leakage or omitted trials."}
