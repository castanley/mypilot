"""Password hashing and token helpers.

Passwords use Argon2id (argon2-cffi). Session tokens are high-entropy random strings; only
their SHA-256 hash is stored, so a database read cannot reconstruct a live session cookie.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_token(nbytes: int = 32) -> str:
    """A URL-safe, high-entropy random token (used for session ids and CSRF tokens)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Stable SHA-256 hex of a token, for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_pairing_code(length: int = 8) -> str:
    """Human-enterable one-time pairing code (uppercase, no ambiguous chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
    return "".join(secrets.choice(alphabet) for _ in range(length))
