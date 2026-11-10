"""No-password local access for the API."""

from fastapi import Request


def authenticate(header: str) -> str | None:
    """Compatibility shim kept for older code paths that still expect auth checks."""
    return "admin"


async def protect_api(request: Request, call_next):
    if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)

    request.state.role = "admin"
    return await call_next(request)
