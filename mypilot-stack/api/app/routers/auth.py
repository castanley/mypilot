"""Authentication: first-admin setup, login, logout, and the current-user endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit
from ..config import get_settings
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_auth, require_csrf
from ..models import Session, User
from ..redis_client import get_redis, rate_limit_ok
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    Me,
    Message,
    SetupRequest,
    SetupState,
)
from ..security import generate_token, hash_password, hash_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])
settings = get_settings()


async def _admin_exists(db: AsyncSession) -> bool:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    return count > 0


async def _establish_session(
    db: AsyncSession, response: Response, request: Request, user: User
) -> str:
    raw = generate_token(32)
    csrf = generate_token(24)
    now = datetime.now(timezone.utc)
    session = Session(
        user_id=user.id,
        token_hash=hash_token(raw),
        csrf_token=csrf,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    db.add(session)
    await db.commit()

    response.set_cookie(
        settings.session_cookie_name,
        raw,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        max_age=settings.session_ttl_seconds,
        httponly=False,  # readable by the SPA to echo back in the X-CSRF-Token header
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return csrf


@router.get("/auth/setup-state", response_model=SetupState)
async def setup_state(db: AsyncSession = Depends(get_session)) -> SetupState:
    return SetupState(needs_setup=not await _admin_exists(db))


@router.post("/auth/setup", response_model=Me, status_code=status.HTTP_201_CREATED)
async def setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Me:
    if not await rate_limit_ok(
        redis, f"setup:{client_ip(request)}", settings.login_rate_limit, settings.login_rate_window
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
    if await _admin_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Setup already completed"
        )
    user = User(
        username=payload.username, password_hash=hash_password(payload.password), is_admin=True
    )
    db.add(user)
    await db.flush()
    await record_audit(
        db, action="auth.setup", actor_type="user", actor_id=str(user.id), ip=client_ip(request)
    )
    csrf = await _establish_session(db, response, request, user)
    return Me(id=user.id, username=user.username, is_admin=user.is_admin, csrf_token=csrf)


@router.post("/auth/login", response_model=Me)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Me:
    if not await rate_limit_ok(
        redis, f"login:{client_ip(request)}", settings.login_rate_limit, settings.login_rate_window
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, payload.password):
        # Uniform error; do not reveal whether the username exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )

    await record_audit(
        db, action="auth.login", actor_type="user", actor_id=str(user.id), ip=client_ip(request)
    )
    csrf = await _establish_session(db, response, request, user)
    return Me(id=user.id, username=user.username, is_admin=user.is_admin, csrf_token=csrf)


@router.post("/auth/logout", response_model=Message)
async def logout(
    response: Response,
    auth: CurrentAuth = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> Message:
    auth.session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return Message(detail="Logged out")


@router.post("/auth/change-password", response_model=Message)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Message:
    user = auth.user
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current one",
        )
    user.password_hash = hash_password(payload.new_password)
    # Invalidate all other sessions (force re-login elsewhere); keep the current one.
    now = datetime.now(timezone.utc)
    others = (
        await db.execute(
            select(Session).where(
                Session.user_id == user.id,
                Session.id != auth.session.id,
                Session.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for s in others:
        s.revoked_at = now
    await record_audit(
        db, action="auth.password.change", actor_type="user", actor_id=str(user.id),
        ip=client_ip(request),
    )
    await db.commit()
    return Message(detail="Password changed")


@router.get("/me", response_model=Me)
async def me(auth: CurrentAuth = Depends(get_current_auth)) -> Me:
    return Me(
        id=auth.user.id,
        username=auth.user.username,
        is_admin=auth.user.is_admin,
        csrf_token=auth.session.csrf_token,
    )
