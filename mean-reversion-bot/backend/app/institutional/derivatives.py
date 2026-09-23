"""European Black-Scholes-Merton research pricing with continuous dividend yield."""
import math
from typing import Literal

from pydantic import Field

from app.institutional.data import Record


class OptionRequest(Record):
    kind: Literal["call", "put"]
    spot: float = Field(gt=0, le=1e12)
    strike: float = Field(gt=0, le=1e12)
    years: float = Field(gt=0, le=100)
    volatility: float = Field(gt=0, le=10)
    rate: float = Field(default=0, ge=-1, le=1)
    dividend_yield: float = Field(default=0, ge=-1, le=1)


def price_option(request: OptionRequest) -> dict:
    s, k, t, vol, r, q = (request.spot, request.strike, request.years,
                          request.volatility, request.rate, request.dividend_yield)
    root = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + vol * vol / 2) * t) / (vol * root)
    d2 = d1 - vol * root
    cdf = lambda x: .5 * (1 + math.erf(x / math.sqrt(2)))
    density = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    ds, dk = math.exp(-q * t), math.exp(-r * t)
    gamma = ds * density / (s * vol * root)
    vega = s * ds * density * root
    common_theta = -s * ds * density * vol / (2 * root)
    if request.kind == "call":
        price = s * ds * cdf(d1) - k * dk * cdf(d2)
        delta = ds * cdf(d1)
        theta = common_theta - r * k * dk * cdf(d2) + q * s * ds * cdf(d1)
        rho = k * t * dk * cdf(d2)
    else:
        price = k * dk * cdf(-d2) - s * ds * cdf(-d1)
        delta = ds * (cdf(d1) - 1)
        theta = common_theta + r * k * dk * cdf(-d2) - q * s * ds * cdf(-d1)
        rho = -k * t * dk * cdf(-d2)
    return {"model": "European Black-Scholes-Merton", "price": max(0.0, price),
            "delta": delta, "gamma": gamma, "theta_per_day": theta / 365,
            "vega_per_vol_point": vega / 100, "rho_per_rate_point": rho / 100,
            "units": "Per underlying unit; volatility/rate point = 0.01. Multiply by signed contracts and contract multiplier for position Greeks.",
            "limitations": "European exercise, constant volatility/rates, continuous yield; no smile, jumps, discrete dividends or American exercise."}
