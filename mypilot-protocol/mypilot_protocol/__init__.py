"""Shared MyPilot protocol: Ed25519 device identity, request signing, and message schemas.

Used by both the API (``mypilot-stack/api``) and the device agent (``mypilot-agent``) so the
signing/verifying logic is defined exactly once.
"""

from .crypto import (
    KeyPair,
    generate_keypair,
    private_key_from_b64,
    public_key_from_b64,
    sign,
    verify,
)
from .messages import (
    CommandName,
    FrameType,
    pairing_challenge,
    ws_auth_message,
)
from .signing import (
    DEVICE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_signed_headers,
    canonical_request,
    is_timestamp_fresh,
    verify_request_signature,
)
from .telemetry import (
    GPS_STATUSES,
    PANDA_STATUSES,
    THERMAL_STATUSES,
    UPDATE_STATES,
    norm_enum,
)

__all__ = [
    "KeyPair",
    "generate_keypair",
    "public_key_from_b64",
    "private_key_from_b64",
    "sign",
    "verify",
    "SIGNATURE_HEADER",
    "DEVICE_HEADER",
    "TIMESTAMP_HEADER",
    "canonical_request",
    "build_signed_headers",
    "verify_request_signature",
    "is_timestamp_fresh",
    "FrameType",
    "pairing_challenge",
    "ws_auth_message",
    "CommandName",
    "THERMAL_STATUSES",
    "GPS_STATUSES",
    "PANDA_STATUSES",
    "UPDATE_STATES",
    "norm_enum",
]
