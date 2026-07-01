"""FastAPI dependencies for user-session auth, CSRF, and signed device auth."""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from mypilot_protocol.signing import (
    DEVICE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    verify_request_signature,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from .config import get_settings
from .db import get_session
from .models import Device, DeviceKey, DeviceStatusValue, KeyStatus, Session, User

settings = get_settings()


def client_ip(request: Request) -> str | None:
    """Best-effort client IP for rate-limit keying and audit attribution.

    Trust order, most to least authoritative — all populated by the reverse proxy, never the client:
      1. ``X-Real-Client-IP`` — when the deployment's proxy resolves the true client and sets this
         header (having first STRIPPED any inbound copy), it is authoritative. Reading a dedicated
         header rather than relying on X-Forwarded-For hop-position is robust to proxy topology
         changes: a stacked/rewritten proxy chain can collapse XFF to a constant, silently keying
         every client into one bucket, whereas a header the proxy explicitly sets stays correct.
      2. last ``X-Forwarded-For`` hop — the proxy appends the genuine peer at the end; the first entry
         is fully client-controlled, so we take the last, never the first.
      3. socket peer (``request.client.host``) — fail-closed when no proxy header is present.

    Reading a proxy-set header directly (not ``request.client``) is safe because the API is reachable
    only through that proxy; a self-hosted single-proxy deploy that sets neither header still works
    via the socket-peer fallback."""
    real = request.headers.get("x-real-client-ip")
    if real and real.strip():
        # Take the FIRST comma token: if two copies of the header reach us they comma-join into
        # "ip1,ip2", which would become a malformed rate-limit key. We don't rely on the proxy always
        # collapsing duplicates — keying integrity stays local. (First, not last: the proxy sets this
        # header itself, so its value leads; a client-injected duplicate would be appended after.)
        return real.split(",")[0].strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else None


@dataclass
class CurrentAuth:
    user: User
    session: Session


async def _load_session(request: Request, db: AsyncSession) -> CurrentAuth:
    from .security import hash_token  # local import avoids a cycle at module load

    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token_hash = hash_token(raw)
    session = (
        await db.execute(select(Session).where(Session.token_hash == token_hash))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    # Compare in UTC; SQLite may return naive datetimes.
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = await db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return CurrentAuth(user=user, session=session)


async def get_current_auth(
    request: Request, db: AsyncSession = Depends(get_session)
) -> CurrentAuth:
    return await _load_session(request, db)


async def get_current_user(auth: CurrentAuth = Depends(get_current_auth)) -> User:
    return auth.user


async def require_csrf(
    request: Request, auth: CurrentAuth = Depends(get_current_auth)
) -> CurrentAuth:
    """Require a valid CSRF token on state-changing requests (double-submit, session-bound)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return auth
    header = request.headers.get("x-csrf-token")
    # Constant-time compare so the token can't be reconstructed via response-timing. The `not header`
    # short-circuit keeps compare_digest from ever receiving None (it raises on non-str input).
    if not header or not hmac.compare_digest(header, auth.session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing or invalid CSRF token"
        )
    return auth


async def require_admin(auth: CurrentAuth = Depends(get_current_auth)) -> CurrentAuth:
    """Admin-only endpoints (e.g. dev tools). 403 for a non-admin authenticated user."""
    if not auth.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return auth


async def require_admin_csrf(auth: CurrentAuth = Depends(require_csrf)) -> CurrentAuth:
    """Admin-only AND CSRF-protected — for state-changing admin endpoints."""
    if not auth.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return auth


async def get_authenticated_device(
    request: Request,
    db: AsyncSession = Depends(get_session),
    x_mypilot_device: str | None = Header(default=None, alias=DEVICE_HEADER),
    x_mypilot_timestamp: str | None = Header(default=None, alias=TIMESTAMP_HEADER),
    x_mypilot_signature: str | None = Header(default=None, alias=SIGNATURE_HEADER),
) -> Device:
    """Authenticate a device by verifying its Ed25519-signed request headers."""
    # Stamp receipt time BEFORE reading the (possibly large/slow) body, so the timestamp-freshness
    # window is measured against when the request arrived — not when its body finished uploading.
    # Otherwise a multi-MB upload that legitimately takes >max_skew seconds on cellular fails the
    # freshness check even though the signature is valid (the bug that 401'd full-res drive uploads).
    received_at = int(time.time())
    if not (x_mypilot_device and x_mypilot_timestamp and x_mypilot_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing device signature"
        )

    device = await db.get(Device, x_mypilot_device)
    if device is None or device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown device")

    key = (
        await db.execute(
            select(DeviceKey).where(
                DeviceKey.device_id == device.id, DeviceKey.status == KeyStatus.ACTIVE
            )
        )
    ).scalars().first()
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device key revoked")

    # Reject an oversized upload from its declared Content-Length BEFORE buffering the body into RAM.
    # The whole body is held in memory (it's signature-verified entire), and this worker also holds
    # every live WebSocket, so an unbounded buffer is a total-availability risk (OOM drops the fleet).
    # The post-read length check in the route handler remains as the backstop for chunked/unknown-length
    # requests. (Signed device requests are not subject to web rate-limits; this is the memory guard.)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload too large"
                )
        except ValueError:
            pass  # malformed header — fall through; the post-read check still bounds it

    try:
        body = await request.body()  # cached by Starlette; route handlers can still read it
    except ClientDisconnect:
        # The client dropped mid-body (e.g. a cellular handoff during a long upload). Surface a clean
        # 4xx the agent can retry, instead of an unhandled ASGI exception / noisy 500 trace.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Client disconnected before body complete"
        )
    ok = verify_request_signature(
        public_key_b64=key.public_key_b64,
        method=request.method,
        path=request.url.path,
        timestamp=x_mypilot_timestamp,
        signature_b64=x_mypilot_signature,
        body=body,
        max_skew=settings.device_signature_max_skew_seconds,
        received_at=received_at,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device signature"
        )
    return device
