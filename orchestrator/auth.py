"""Multi-user authentication: bcrypt password hashing + JWT bearer tokens.

Isolation model (see IMPLEMENTATION_PLAN / CLAUDE.md): only the per-user Data
Entry schema is user-scoped. Meetings, standups, templates and summaries stay
shared — login merely gates access. So most routes only need "a valid user is
logged in"; the Data Entry / Insights routes additionally read *which* user
(for their ``dataentry_schema``).

Enforcement is a single app-level dependency ``require_auth`` (mirrors how the
old static-key ``verify_api_key`` worked), which stashes the resolved ``User``
on ``request.state.current_user``. Routes that need the identity depend on the
cheap ``current_user`` accessor rather than re-decoding the token.
"""
import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db
from shared.models import User

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Paths that never require a logged-in user.
_EXEMPT_PREFIXES = ("/webhooks/",)
_EXEMPT_EXACT = {"/health", "/", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
_EXEMPT_AUTH = {"/api/auth/login", "/api/auth/register"}


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expiry_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT or path in _EXEMPT_AUTH:
        return True
    if path.endswith("/stream"):  # browser EventSource can't send headers
        return True
    return any(path.startswith(p) for p in _EXEMPT_PREFIXES)


async def _resolve_user(token: str, db: AsyncSession) -> User:
    claims = _decode_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def require_auth(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """App-level gate. Exempts health/webhooks/stream/auth; otherwise requires a
    valid JWT and stashes the ``User`` on ``request.state.current_user``."""
    if _is_exempt(request.url.path):
        return
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    request.state.current_user = await _resolve_user(token, db)


def current_user(request: Request) -> User:
    """Return the user resolved by ``require_auth``. Use in routes that need the
    caller's identity (Data Entry, Insights). 401 if somehow unauthenticated."""
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
