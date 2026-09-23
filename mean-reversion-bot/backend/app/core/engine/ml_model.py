"""Small dependency-free online classifier for research and demo trading.

Features and next-close labels use only the supplied closed-candle history.
The latest closed candle may complete a training label; inference predicts
the following candle. Callers must never supply forming or future candles.
"""
from __future__ import annotations

import math
from typing import Optional

from app.core.lsl.lsl_detector import Candle


def _features(closes: list[float], i: int) -> list[float]:
    window = closes[max(0, i - 20): i + 1]
    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / max(1, len(window) - 1)
    sd = math.sqrt(variance) or 1e-9
    ret = closes[i] / closes[i - 1] - 1.0 if i else 0.0
    return [1.0, (closes[i] - mean) / sd, ret, sd / max(abs(mean), 1e-9)]


def predict(candles: list[Candle], min_samples: int = 80,
            threshold: float = 0.56) -> tuple[Optional[str], float]:
    """Fit logistic regression and predict the next close direction.

    Confidence is an uncalibrated model score, not a measured win rate.
    """
    if min_samples < 1 or not 0.5 < threshold < 1:
        raise ValueError("Require positive min_samples and 0.5 < threshold < 1")
    closes = [float(c.close) for c in candles]
    if any(not math.isfinite(c) or c <= 0 for c in closes):
        raise ValueError("Model requires finite, positive closes")
    if any(b.timestamp <= a.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("Model requires strictly chronological candles")
    if len(candles) < min_samples + 21:
        return None, 0.0
    end = len(candles) - 1
    xs = [_features(closes, i) for i in range(20, end)]
    ys = [1.0 if closes[i + 1] > closes[i] else 0.0
          for i in range(20, end)]
    weights = [0.0] * 4
    # Logistic regression with deterministic gradient descent; no external ML
    # runtime is required in production/demo containers.
    for _ in range(120):
        grad = [0.0] * 4
        for x, y in zip(xs, ys):
            z = max(-30.0, min(30.0, sum(a * b for a, b in zip(weights, x))))
            p = 1.0 / (1.0 + math.exp(-z))
            for j in range(4):
                grad[j] += (p - y) * x[j]
        for j in range(4):
            weights[j] -= 0.08 * grad[j] / len(xs)
    p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, sum(a * b for a, b in zip(weights, _features(closes, end)))))))
    if p >= threshold:
        return "buy", p
    if p <= 1.0 - threshold:
        return "sell", 1.0 - p
    return None, max(p, 1.0 - p)
