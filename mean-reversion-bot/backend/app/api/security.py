from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database.session import get_db
from app.database.models import User

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(reusable_oauth2)
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid password is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = authenticate(f"Bearer {token}")
    if role:
        result = await db.execute(select(User).where(User.is_active == True).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=1, email="admin@local", hashed_password="", is_active=True)
        return user

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user

import hashlib
import hmac
from fastapi.responses import JSONResponse


def authenticate(header: str) -> str | None:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or len(token) < 8:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    for role in ("admin", "operator", "viewer"):
        role_name = role.upper()
        key_hash = getattr(settings, f"API_{role_name}_KEY_HASH", "")
        pass_hash = getattr(settings, f"API_{role_name}_PASSWORD_HASH", "")
        if (len(key_hash) == 64 and hmac.compare_digest(digest, key_hash)) or \
           (len(pass_hash) == 64 and hmac.compare_digest(digest, pass_hash)):
            return role
    return None


def any_key_configured() -> bool:
    for role in ("admin", "operator", "viewer"):
        role_name = role.upper()
        expected = (getattr(settings, f"API_{role_name}_PASSWORD_HASH", "") or
                    getattr(settings, f"API_{role_name}_KEY_HASH", ""))
        if len(expected) == 64:
            return True
    return False


async def protect_api(request: Request, call_next):
    # Public paths
    if not request.url.path.startswith("/api/") or \
       request.url.path.startswith("/api/auth/login") or \
       request.url.path.startswith("/api/auth/register") or \
       request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    role = authenticate(auth_header)

    if not role:
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                if payload.get("sub"):
                    role = "user"
            except JWTError:
                pass

    if not role:
        return JSONResponse({"detail": "A valid password is required"}, 401,
                            headers={"WWW-Authenticate": "Bearer"})

    request.state.role = role

    if request.method not in {"GET", "HEAD"}:
        admin_only = (request.url.path.startswith("/api/config") or
                      request.url.path.endswith("/circuit-breaker/reset") or
                      request.url.path.endswith("/resolve"))
        if role == "viewer" or (admin_only and role != "admin"):
            return JSONResponse({"detail": "Insufficient permissions"}, 403)

    return await call_next(request)

