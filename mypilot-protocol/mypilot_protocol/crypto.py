"""Ed25519 key generation, signing, and verification.

Keys and signatures are exchanged as standard base64 strings (raw 32-byte keys, raw 64-byte
RFC-8032 signatures). Private keys never leave the device; only the base64 public key is sent to
the Stack during pairing.

Dual backend: the Stack and dev tooling use **cryptography**; comma devices ship **pycryptodome**
instead. Both produce byte-identical (deterministic) Ed25519 signatures for the same key+message,
so a device signed with pycryptodome verifies on the Stack with cryptography and vice-versa.

Whichever backend libraries are importable register themselves into ``_BACKENDS`` below; the
ACTIVE backend used by the module-level helpers is chosen by preference (cryptography first, then
pycryptodome). When BOTH are installed — e.g. in the test environment — each stays individually
reachable, so the cross-backend interoperability the whole fleet depends on can be exercised
directly against the shipped code paths (see tests/test_crypto_interop.py) rather than a stand-in.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Callable


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


@dataclass(frozen=True)
class _Backend:
    """One Ed25519 implementation. ``sign_raw`` / ``verify_raw`` accept and return the same base64
    strings and byte payloads regardless of backend, so two backends are interchangeable on the
    wire — that interchangeability is exactly what the interop test pins."""

    name: str
    gen_raw: Callable[[], tuple[bytes, bytes]]
    private_key_from_b64: Callable[[str], Any]
    public_key_from_b64: Callable[[str], Any]
    sign_raw: Callable[[str, bytes], bytes]
    verify_raw: Callable[[str, bytes, bytes], bool]


# A backend registers here iff its library imports cleanly. Keyed by name so a test can select a
# specific backend; production uses the preferred ACTIVE backend chosen below.
_BACKENDS: dict[str, _Backend] = {}


try:  # ---- backend: cryptography (Stack, dev, CI) ------------------------------------------------
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    def _cryptography_gen_raw() -> tuple[bytes, bytes]:
        priv = Ed25519PrivateKey.generate()
        return priv.private_bytes_raw(), priv.public_key().public_bytes_raw()

    def _cryptography_private_key_from_b64(value: str) -> Any:
        return Ed25519PrivateKey.from_private_bytes(_b64d(value))

    def _cryptography_public_key_from_b64(value: str) -> Any:
        return Ed25519PublicKey.from_public_bytes(_b64d(value))

    def _cryptography_sign_raw(private_key_b64: str, data: bytes) -> bytes:
        return _cryptography_private_key_from_b64(private_key_b64).sign(data)

    def _cryptography_verify_raw(public_key_b64: str, signature: bytes, data: bytes) -> bool:
        try:
            _cryptography_public_key_from_b64(public_key_b64).verify(signature, data)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    _BACKENDS["cryptography"] = _Backend(
        name="cryptography",
        gen_raw=_cryptography_gen_raw,
        private_key_from_b64=_cryptography_private_key_from_b64,
        public_key_from_b64=_cryptography_public_key_from_b64,
        sign_raw=_cryptography_sign_raw,
        verify_raw=_cryptography_verify_raw,
    )
except ImportError:
    pass


try:  # ---- backend: pycryptodome (comma AGNOS device) --------------------------------------------
    from Crypto.PublicKey import ECC  # type: ignore
    from Crypto.Signature import eddsa  # type: ignore

    def _pycryptodome_gen_raw() -> tuple[bytes, bytes]:
        key = ECC.generate(curve="Ed25519")
        return key.seed, key.public_key().export_key(format="raw")

    def _pycryptodome_private_key_from_b64(value: str) -> Any:
        return eddsa.import_private_key(_b64d(value))

    def _pycryptodome_public_key_from_b64(value: str) -> Any:
        return eddsa.import_public_key(_b64d(value))

    def _pycryptodome_sign_raw(private_key_b64: str, data: bytes) -> bytes:
        signer = eddsa.new(_pycryptodome_private_key_from_b64(private_key_b64), "rfc8032")
        return signer.sign(data)

    def _pycryptodome_verify_raw(public_key_b64: str, signature: bytes, data: bytes) -> bool:
        try:
            verifier = eddsa.new(_pycryptodome_public_key_from_b64(public_key_b64), "rfc8032")
            verifier.verify(data, signature)
            return True
        except (ValueError, TypeError):
            return False

    _BACKENDS["pycryptodome"] = _Backend(
        name="pycryptodome",
        gen_raw=_pycryptodome_gen_raw,
        private_key_from_b64=_pycryptodome_private_key_from_b64,
        public_key_from_b64=_pycryptodome_public_key_from_b64,
        sign_raw=_pycryptodome_sign_raw,
        verify_raw=_pycryptodome_verify_raw,
    )
except ImportError:
    pass


if not _BACKENDS:  # pragma: no cover - a build with neither library cannot sign or verify at all
    raise ImportError(
        "No Ed25519 backend available: install 'cryptography' (Stack) or 'pycryptodome' (device)."
    )

# Preferred backend for THIS process: cryptography on the Stack/CI, pycryptodome on the device.
_ACTIVE: _Backend = _BACKENDS.get("cryptography") or _BACKENDS["pycryptodome"]
CRYPTO_BACKEND = _ACTIVE.name


def private_key_from_b64(value: str) -> Any:
    return _ACTIVE.private_key_from_b64(value)


def public_key_from_b64(value: str) -> Any:
    return _ACTIVE.public_key_from_b64(value)


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 keypair, base64-encoded for storage/transport."""

    private_key_b64: str
    public_key_b64: str

    def private_key(self) -> Any:
        return private_key_from_b64(self.private_key_b64)


def generate_keypair() -> KeyPair:
    """Generate a fresh Ed25519 keypair (raw 32-byte keys, base64-encoded)."""
    priv_raw, pub_raw = _ACTIVE.gen_raw()
    return KeyPair(private_key_b64=_b64e(priv_raw), public_key_b64=_b64e(pub_raw))


def sign(private_key_b64: str, data: bytes) -> str:
    """Sign ``data`` with the base64 private key; return a base64 signature."""
    return _b64e(_ACTIVE.sign_raw(private_key_b64, data))


def verify(public_key_b64: str, signature_b64: str, data: bytes) -> bool:
    """Return True iff ``signature_b64`` is a valid signature of ``data`` for the public key.

    Total at the auth boundary: returns False (never raises) on a bad signature OR on malformed /
    wrong-type / ``None`` key or signature. An attacker controls these bytes, so an exception here
    would be an error-handling hole / DoS at the device-auth boundary rather than a clean reject.
    The leading type guard makes the ``None``/non-str case explicit; the backend's own decode/verify
    handles bad-base64, wrong-length, and invalid-signature inputs.
    """
    if not isinstance(public_key_b64, str) or not isinstance(signature_b64, str):
        return False
    try:
        signature = _b64d(signature_b64)
    except (ValueError, TypeError):
        return False
    return _ACTIVE.verify_raw(public_key_b64, signature, data)
