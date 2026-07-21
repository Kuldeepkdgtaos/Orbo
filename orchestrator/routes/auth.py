import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.models import User
from shared.schemas import TokenResponse, UserLogin, UserRead, UserRegister

from ..auth import create_access_token, current_user, hash_password, verify_password
from ..dataentry_service import derive_schema_name, ensure_schema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


async def _unique_schema_name(db: AsyncSession, email: str) -> str:
    """Derive the user's Data Entry schema name, resolving the rare case where
    two different emails sanitize to the same identifier."""
    base = derive_schema_name(email)
    candidate = base
    suffix = 1
    while True:
        exists = (await db.execute(
            select(User.id).where(User.dataentry_schema == candidate)
        )).scalar_one_or_none()
        if not exists:
            return candidate
        tag = f"_{suffix}"
        candidate = (base[: 63 - len(tag)] + tag)
        suffix += 1


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=422, detail="Invalid email address")

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    schema_name = await _unique_schema_name(db, email)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        dataentry_schema=schema_name,
    )
    db.add(user)
    await db.flush()
    # Provision the user's dedicated Data Entry schema up front.
    await ensure_schema(db, schema_name)
    await db.commit()
    await db.refresh(user)

    logger.info("User registered", extra={"user_id": user.id, "schema": schema_name})
    return TokenResponse(access_token=create_access_token(user), user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user), user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def me(request: Request):
    return UserRead.model_validate(current_user(request))
