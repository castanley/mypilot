"""Tests for the device request-signing contract — in particular the two fixes that let large drive
uploads succeed over cellular:

  1. freshness is gated against request RECEIPT time, not 'now-after-the-body-arrived', so a slow
     multi-MB upload can't age a valid signature out of the window;
  2. a body can be signed by its precomputed sha256 (streamed/chunked) and still verifies identically
     to signing the in-memory bytes.
"""

from __future__ import annotations

import hashlib
import time

from mypilot_protocol.crypto import generate_keypair
from mypilot_protocol.signing import (
    DEFAULT_MAX_SKEW,
    build_signed_headers,
    canonical_request,
    is_timestamp_fresh,
    verify_request_signature,
)

KP = generate_keypair()


def _sign(method, path, body, ts):
    return build_signed_headers(
        "dev-1", KP.private_key_b64, method, path, body, timestamp=ts
    )


def test_valid_signature_round_trips():
    body = b"hello"
    ts = int(time.time())
    h = _sign("PUT", "/api/ingest/x", body, ts)
    assert verify_request_signature(
        KP.public_key_b64, "PUT", "/api/ingest/x", h["X-MyPilot-Timestamp"],
        h["X-MyPilot-Signature"], body=body, received_at=ts,
    )


def test_slow_body_passes_when_checked_against_receipt_time():
    """The bug: a body that takes longer than the skew window to upload used to 401 even though the
    signature was valid. With received_at = the time the request ARRIVED (when the signature was
    fresh), it must verify regardless of how long the body then took to stream in."""
    body = b"x" * 4096
    sign_ts = 1_000_000  # when the device minted the signature
    received_at = sign_ts + 3  # request arrived 3s later — fresh
    h = _sign("PUT", "/api/ingest/big", body, sign_ts)
    # Even though "now" is far past the window, receipt time is what matters.
    assert verify_request_signature(
        KP.public_key_b64, "PUT", "/api/ingest/big", h["X-MyPilot-Timestamp"],
        h["X-MyPilot-Signature"], body=body,
        max_skew=DEFAULT_MAX_SKEW, received_at=received_at,
    )


def test_stale_signature_still_rejected_at_receipt():
    """Replay protection must still hold: if the signature was already stale when the request
    arrived, it's rejected."""
    body = b"data"
    sign_ts = 1_000_000
    received_at = sign_ts + DEFAULT_MAX_SKEW + 5  # arrived after the window — stale
    h = _sign("PUT", "/p", body, sign_ts)
    assert not verify_request_signature(
        KP.public_key_b64, "PUT", "/p", h["X-MyPilot-Timestamp"],
        h["X-MyPilot-Signature"], body=body, received_at=received_at,
    )


def test_is_timestamp_fresh_uses_now_override():
    ts = 5_000_000
    assert is_timestamp_fresh(ts, 60, now=ts + 30)
    assert not is_timestamp_fresh(ts, 60, now=ts + 61)


def test_body_sha256_signing_matches_in_memory_body():
    """Signing via a precomputed body_sha256 (the streaming path) yields the SAME canonical message
    as signing the raw bytes — so a chunk-hashed large file verifies just like a buffered one."""
    body = b"segment-bytes" * 1000
    digest = hashlib.sha256(body).hexdigest()
    ts = int(time.time())
    from_body = canonical_request("PUT", "/f", ts, body)
    from_hash = canonical_request("PUT", "/f", ts, body_sha256=digest)
    assert from_body == from_hash

    h = build_signed_headers("dev-1", KP.private_key_b64, "PUT", "/f", timestamp=ts, body_sha256=digest)
    assert verify_request_signature(
        KP.public_key_b64, "PUT", "/f", h["X-MyPilot-Timestamp"],
        h["X-MyPilot-Signature"], body=body, received_at=ts,
    )


def test_tampered_body_fails():
    body = b"original"
    ts = int(time.time())
    h = _sign("PUT", "/f", body, ts)
    assert not verify_request_signature(
        KP.public_key_b64, "PUT", "/f", h["X-MyPilot-Timestamp"],
        h["X-MyPilot-Signature"], body=b"tampered", received_at=ts,
    )
