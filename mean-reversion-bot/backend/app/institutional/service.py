"""Versioned, reproducible report facade shared by HTTP and offline CLI."""
from pathlib import Path
import platform
from importlib.metadata import version

from pydantic import Field

from app.institutional.data import BookEvent, Observation, Record, fingerprint, point_in_time, replay
from app.institutional.derivatives import OptionRequest, price_option
from app.institutional.execution import CostRequest, RouteRequest, ScheduleRequest, estimate_cost, route, schedule
from app.institutional.market_making import MarketMakingRequest, QuoteRequest, quote, simulate_market_making
from app.institutional.research import ExperimentRequest, MultipleTestingRequest, adjust_tests, experiment
from app.institutional.risk import AllocationRequest, PortfolioRequest, allocate, portfolio_risk
from app.institutional.instruments import ConversionRequest, InstrumentOrderRequest, convert_currency, validate_instrument_order
from app.institutional.instrument_planning import InstrumentPlanRequest, plan_instrument_order
from app.institutional.option_portfolio import OptionPortfolioRequest, option_portfolio
from app.institutional.order_lifecycle import LifecycleRequest, simulate_lifecycle
from app.institutional.auto_quoting import AutoQuoteRequest, simulate_auto_quotes


class ReplayRequest(Record):
    events: list[BookEvent] = Field(min_length=1, max_length=1000)
    max_age_ms: int = Field(default=1000, ge=0, le=60000)


class FeatureRequest(Record):
    observations: list[Observation] = Field(min_length=1, max_length=10000)
    decision_times: list[int] = Field(min_length=1, max_length=1000)
    max_age_ms: int = Field(ge=0)


OPERATIONS = {
    "auto-quoting": (AutoQuoteRequest, simulate_auto_quotes),
    "order-lifecycle": (LifecycleRequest, simulate_lifecycle),
    "option-portfolio": (OptionPortfolioRequest, option_portfolio),
    "instrument-plan": (InstrumentPlanRequest, plan_instrument_order),
    "instrument-order": (InstrumentOrderRequest, validate_instrument_order),
    "currency-convert": (ConversionRequest, convert_currency),
    "replay": (ReplayRequest, lambda r: replay(r.events, r.max_age_ms)),
    "features": (FeatureRequest, lambda r: {"rows": point_in_time(r.observations, r.decision_times, r.max_age_ms)}),
    "route": (RouteRequest, route), "schedule": (ScheduleRequest, schedule),
    "cost": (CostRequest, estimate_cost), "risk": (PortfolioRequest, portfolio_risk),
    "allocate": (AllocationRequest, allocate), "option": (OptionRequest, price_option),
    "quote": (QuoteRequest, quote), "experiment": (ExperimentRequest, experiment),
    "market-making": (MarketMakingRequest, simulate_market_making),
    "multiple-testing": (MultipleTestingRequest, adjust_tests),
}


def provenance() -> dict:
    source = {p.name: p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))}
    return {"implementation_hash": fingerprint(source),
            "runtime": {"python": platform.python_version(), "numpy": version("numpy"), "pydantic": version("pydantic")}}


def analyze(operation: str, payload: dict) -> dict:
    if operation not in OPERATIONS:
        raise ValueError(f"Unknown analysis: {operation}")
    schema, function = OPERATIONS[operation]
    request = schema.model_validate(payload)
    canonical = request.model_dump(mode="json")
    # Hash source as well as data/config: changed code must change report identity.
    identity = provenance()
    implementation_hash, runtime = identity["implementation_hash"], identity["runtime"]
    result = function(request)
    fingerprint(result)  # Refuse NaN/Infinity before serialization or persistence.
    return {"schema_version": 1, "operation": operation, "mode": "offline_research",
            "live_authorized": False, "request": canonical, "result": result,
            "implementation_hash": implementation_hash,
            "runtime": runtime,
            "report_id": fingerprint({"operation": operation, "request": canonical, "implementation": implementation_hash, "runtime": runtime})}
