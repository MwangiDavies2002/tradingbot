from typing import Literal

BrokerName = Literal["deriv", "oanda", "fxcm"]

def validate_broker(name: str) -> BrokerName:
    value = name.lower().strip()
    if value not in {"deriv", "oanda", "fxcm"}:
        raise ValueError("Broker must be one of: deriv, oanda, fxcm")
    return value  # type: ignore[return-value]

def broker_status(settings) -> dict:
    name = validate_broker(getattr(settings, "BROKER", "deriv"))
    if name == "oanda":
        configured = bool(settings.OANDA_API_TOKEN and settings.OANDA_ACCOUNT_ID)
        environment = settings.OANDA_ENVIRONMENT
    elif name == "deriv":
        configured = bool(settings.DERIV_API_TOKEN and settings.DERIV_ACCOUNT_ID)
        environment = "demo" if settings.DERIV_DEMO else "live"
    else:
        configured, environment = False, "not_configured"
    return {"broker": name, "environment": environment, "configured": configured,
            "execution_ready": name == "deriv" and configured}


def require_execution_broker(settings) -> None:
    name = validate_broker(getattr(settings, "BROKER", "deriv"))
    if name != "deriv":
        raise ValueError(f"Execution adapter for {name} is not implemented")
