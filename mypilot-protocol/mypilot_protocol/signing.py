"""Signed HTTP request helpers for authenticated device -> Stack calls.

A device signs the canonical string ``METHOD\\nPATH\\nTIMESTAMP\\nSHA256_HEX(body)`` with its
Ed25519 private key. The server recomputes the string and verifies against the stored public
key, additionally enforcing a freshness window on the timestamp to prevent replay.
"""

from __future__ import annotations

import hashlib
import time

from .crypto import sign, verify

DEVICE_HEADER = "X-MyPilot-Device"
TIMESTAMP_HEADER = "X-MyPilot-Timestamp"
SIGNATURE_HEADER = "X-MyPilot-Signature"

# Maximum allowed clock skew (seconds) between device and server for a signed request.
DEFAULT_MAX_SKEW = 60


def canonical_request(
    method: str,
    path: str,
    timestamp: int | str,
    body: bytes | None = None,
    *,
    body_sha256: str | None = None,
) -> bytes:
    """Build the canonical byte string that gets signed/verified.

    Pass either the raw ``body`` (hashed here) or a precomputed ``body_sha256`` hex digest. The
    latter lets a large upload be hashed by streaming the file in chunks, so the whole body never
    has to be held in memory just to sign it."""
    if body_sha256 is None:
        body_sha256 = hashlib.sha256(body or b"").hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{body_sha256}".encode("utf-8")


def build_signed_headers(
    device_id: str,
    private_key_b64: str,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: int | None = None,
    *,
    body_sha256: str | None = None,
) -> dict[str, str]:
    """Produce the X-MyPilot-* headers for an authenticated device request. For large uploads pass
    ``body_sha256`` (computed by streaming the file) instead of ``body`` to avoid buffering it."""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    message = canonical_request(method, path, ts, body, body_sha256=body_sha256)
    signature = sign(private_key_b64, message)
    return {
        DEVICE_HEADER: device_id,
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: signature,
    }


def is_timestamp_fresh(
    timestamp: int | str, max_skew: int = DEFAULT_MAX_SKEW, *, now: int | None = None
) -> bool:
    """Return True iff ``timestamp`` is within ``max_skew`` seconds of ``now`` (default: current
    time). The server passes the request RECEIPT time as ``now`` so a slow body transfer doesn't
    age the timestamp out of the window — freshness gates replay, not upload duration."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    ref = int(time.time()) if now is None else int(now)
    return abs(ref - ts) <= max_skew


def verify_request_signature(
    public_key_b64: str,
    method: str,
    path: str,
    timestamp: int | str,
    signature_b64: str,
    body: bytes = b"",
    max_skew: int = DEFAULT_MAX_SKEW,
    *,
    received_at: int | None = None,
) -> bool:
    """Verify a signed device request: both the timestamp freshness and the signature.

    ``received_at`` (seconds, the time the server began handling the request) is the reference for
    the freshness window. Pass it so the freshness check is independent of how long the body took
    to arrive; without it, the window is measured against 'now', which on a large/slow upload is
    after the full body has been read (the bug that 401'd valid multi-MB uploads over cellular)."""
    if not is_timestamp_fresh(timestamp, max_skew, now=received_at):
        return False
    message = canonical_request(method, path, timestamp, body)
    return verify(public_key_b64, signature_b64, message)
