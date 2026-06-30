"""Ed25519 key generation, signing, and verification.

Keys and signatures are exchanged as standard base64 strings (raw 32-byte keys, raw 64-byte
RFC-8032 signatures). Private keys never leave the device; only the base64 public key is sent to
the Stack during pairing.

Dual backend: the Stack and dev tooling use **cryptography**; comma devices ship **pycryptodome**
instead. Both produce byte-identical (deterministic) Ed25519 signatures for the same key+message,
so a device signed with pycryptodome verifies on the Stack with cryptography and vice-versa.
The backend is chosen at import time by availability — `cryptography` is preferred.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


try:  # ---- preferred backend: cryptography (Stack, dev, CI) -----------------------------------
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    CRYPTO_BACKEND = "cryptography"

    def _gen_raw() -> tuple[bytes, bytes]:
        priv = Ed25519PrivateKey.generate()
        return priv.private_bytes_raw(), priv.public_key().public_bytes_raw()

    def private_key_from_b64(value: str) -> Any:
        return Ed25519PrivateKey.from_private_bytes(_b64d(value))

    def public_key_from_b64(value: str) -> Any:
        return Ed25519PublicKey.from_public_bytes(_b64d(value))

    def _sign_raw(private_key_b64: str, data: bytes) -> bytes:
        return private_key_from_b64(private_key_b64).sign(data)

    def _verify_raw(public_key_b64: str, signature: bytes, data: bytes) -> bool:
        try:
            public_key_from_b64(public_key_b64).verify(signature, data)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

except ImportError:  # ---- device backend: pycryptodome (comma AGNOS) ------------------------
    from Crypto.PublicKey import ECC  # type: ignore
    from Crypto.Signature import eddsa  # type: ignore

    CRYPTO_BACKEND = "pycryptodome"

    def _gen_raw() -> tuple[bytes, bytes]:
        key = ECC.generate(curve="Ed25519")
        return key.seed, key.public_key().export_key(format="raw")

    def private_key_from_b64(value: str) -> Any:
        return eddsa.import_private_key(_b64d(value))

    def public_key_from_b64(value: str) -> Any:
        return eddsa.import_public_key(_b64d(value))

    def _sign_raw(private_key_b64: str, data: bytes) -> bytes:
        signer = eddsa.new(private_key_from_b64(private_key_b64), "rfc8032")
        return signer.sign(data)

    def _verify_raw(public_key_b64: str, signature: bytes, data: bytes) -> bool:
        try:
            verifier = eddsa.new(public_key_from_b64(public_key_b64), "rfc8032")
            verifier.verify(data, signature)
            return True
        except (ValueError, TypeError):
            return False


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 keypair, base64-encoded for storage/transport."""

    private_key_b64: str
    public_key_b64: str

    def private_key(self) -> Any:
        return private_key_from_b64(self.private_key_b64)


def generate_keypair() -> KeyPair:
    """Generate a fresh Ed25519 keypair (raw 32-byte keys, base64-encoded)."""
    priv_raw, pub_raw = _gen_raw()
    return KeyPair(private_key_b64=_b64e(priv_raw), public_key_b64=_b64e(pub_raw))


def sign(private_key_b64: str, data: bytes) -> str:
    """Sign ``data`` with the base64 private key; return a base64 signature."""
    return _b64e(_sign_raw(private_key_b64, data))


def verify(public_key_b64: str, signature_b64: str, data: bytes) -> bool:
    """Return True iff ``signature_b64`` is a valid signature of ``data`` for the public key.

    Never raises on a bad signature or malformed input — returns False instead.
    """
    try:
        signature = _b64d(signature_b64)
    except (ValueError, TypeError):
        return False
    return _verify_raw(public_key_b64, signature, data)
