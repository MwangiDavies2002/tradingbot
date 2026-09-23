"""Signed European option exposures and explicit, pre-expiry scenario repricing."""
from math import fsum

from pydantic import Field, model_validator

from app.institutional.data import Record
from app.institutional.derivatives import OptionRequest, price_option
from app.institutional.instruments import Currency

GREEKS = ("delta", "gamma", "theta_per_day", "vega_per_vol_point", "rho_per_rate_point")


class OptionPosition(Record):
    position_id: str = Field(min_length=1, max_length=128)
    underlying: str = Field(min_length=1, max_length=128)
    currency: Currency
    contracts: int = Field(ge=-1_000_000, le=1_000_000, strict=True)
    multiplier: float = Field(gt=0, le=1e6)
    option: OptionRequest


class OptionShock(Record):
    spot_return: float = Field(default=0, gt=-1, le=10)
    volatility_change: float = Field(default=0, ge=-10, le=10)
    rate_change: float = Field(default=0, ge=-2, le=2)
    dividend_yield_change: float = Field(default=0, ge=-2, le=2)


class OptionScenario(Record):
    name: str = Field(min_length=1, max_length=128)
    elapsed_days: float = Field(default=0, ge=0, le=36500)
    shocks: dict[str, OptionShock] = Field(min_length=1, max_length=100)


class OptionPortfolioRequest(Record):
    currency: Currency
    positions: list[OptionPosition] = Field(min_length=1, max_length=100)
    scenarios: list[OptionScenario] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def consistent(self):
        if len({p.position_id for p in self.positions}) != len(self.positions):
            raise ValueError("Position IDs must be unique")
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario names must be unique")
        spots = {}
        for p in self.positions:
            if p.currency != self.currency:
                raise ValueError("All positions must share the reporting currency; FX conversion is not modeled")
            if p.underlying in spots and spots[p.underlying] != p.option.spot:
                raise ValueError("Positions on the same underlying must share the same spot")
            spots[p.underlying] = p.option.spot
        for scenario in self.scenarios:
            if set(scenario.shocks) != set(spots):
                raise ValueError("Each scenario must cover exactly all underlyings, including zero shocks")
            for p in self.positions:
                shocked_option(p, scenario)  # Validate transformed inputs before computation.
        return self


def shocked_option(position, scenario):
    option = position.option
    shock = scenario.shocks[position.underlying]
    years = option.years - scenario.elapsed_days / 365
    if years <= 0:
        raise ValueError("Scenarios must remain strictly before every option expiry; settlement is not modeled")
    return OptionRequest.model_validate(option.model_dump() | {
        "spot": option.spot * (1 + shock.spot_return), "years": years,
        "volatility": option.volatility + shock.volatility_change,
        "rate": option.rate + shock.rate_change,
        "dividend_yield": option.dividend_yield + shock.dividend_yield_change})


def position_value(position, option):
    unit = price_option(option)
    scale = position.contracts * position.multiplier
    return {"position_id": position.position_id, "underlying": position.underlying,
            "unit_price": unit["price"], "value": scale * unit["price"],
            **{key: scale * unit[key] for key in GREEKS}}


def aggregate(rows):
    # Delta/gamma for different assets have different units; never sum across them.
    return {underlying: {key: fsum(row[key] for row in rows if row["underlying"] == underlying)
                        for key in ("value", *GREEKS)}
            for underlying in sorted({row["underlying"] for row in rows})}


def option_portfolio(request: OptionPortfolioRequest) -> dict:
    base = [position_value(p, p.option) for p in request.positions]
    base_value = fsum(row["value"] for row in base)
    scenarios = []
    for scenario in request.scenarios:
        rows = [position_value(p, shocked_option(p, scenario)) for p in request.positions]
        for row, original in zip(rows, base):
            row["pnl"] = row["value"] - original["value"]
        scenarios.append({"name": scenario.name, "elapsed_days": scenario.elapsed_days,
                          "value": fsum(row["value"] for row in rows),
                          "pnl": fsum(row["pnl"] for row in rows),
                          "positions": rows, "by_underlying": aggregate(rows)})
    return {"currency": request.currency, "base_value": base_value,
            "gross_option_value": fsum(abs(row["value"]) for row in base),
            "positions": base, "by_underlying": aggregate(base), "scenarios": scenarios,
            "live_authorized": False,
            "units": "Signed contracts times supplied multiplier. Delta/gamma grouped by underlying; theta per calendar day; vega/rho per 0.01 change. Shocks use decimal changes, not percentage points.",
            "limitations": ["European Black-Scholes-Merton marks; no smile dynamics, American exercise or discrete dividends.",
                            "Scenario P&L is model value change, not realized return; no premiums paid, financing, costs, collateral or settlement.",
                            "Horizons must remain before all expiries. No FX conversion or executable hedge proposal.",
                            "Net sensitivities do not establish legal, counterparty or margin netting rights."]}
