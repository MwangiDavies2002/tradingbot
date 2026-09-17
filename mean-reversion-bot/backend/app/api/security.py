"""Fail-closed role-based access for both local and deployed API instances."""
import hashlib
import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings


def authenticate(header: str) -> str | None:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or len(token) < 32:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    for role in ("admin", "operator", "viewer"):
        expected = getattr(settings, f"API_{role.upper()}_KEY_HASH")
        if len(expected) == 64 and hmac.compare_digest(digest, expected):
            return role
    return None


async def protect_api(request: Request, call_next):
    if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)
    role = authenticate(request.headers.get("authorization", ""))
    if not role:
        return JSONResponse({"detail": "A valid access key is required"}, 401,
                            headers={"WWW-Authenticate": "Bearer"})
    request.state.role = role
    if request.method not in {"GET", "HEAD"}:
        admin_only = (request.url.path.startswith("/api/config") or
                      request.url.path.endswith("/circuit-breaker/reset") or
                      request.url.path.endswith("/resolve"))
        if role == "viewer" or (admin_only and role != "admin"):
            return JSONResponse({"detail": "Insufficient permissions"}, 403)
    return await call_next(request)
