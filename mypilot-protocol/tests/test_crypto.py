"""Ed25519 sign/verify — the primitive behind ALL device authentication. A break here is a full
device-auth bypass, so pin the contract: valid signatures verify, tampered ones don't, and a
signature is bound to BOTH the exact message bytes and the exact keypair."""

from __future__ import annotations

from mypilot_protocol.crypto import generate_keypair, sign, verify


def test_sign_verify_roundtrip():
    kp = generate_keypair()
    msg = b"device-auth-nonce-12345"
    sig = sign(kp.private_key_b64, msg)
    assert verify(kp.public_key_b64, sig, msg) is True


def test_tampered_message_fails():
    kp = generate_keypair()
    sig = sign(kp.private_key_b64, b"original")
    assert verify(kp.public_key_b64, sig, b"original ") is False  # one extra byte
    assert verify(kp.public_key_b64, sig, b"0riginal") is False   # one changed byte


def test_tampered_signature_fails():
    kp = generate_keypair()
    sig = sign(kp.private_key_b64, b"msg")
    # Flip a character in the b64 signature.
    bad = sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    assert verify(kp.public_key_b64, bad, b"msg") is False


def test_wrong_key_fails():
    a, b = generate_keypair(), generate_keypair()
    sig = sign(a.private_key_b64, b"msg")
    assert verify(b.public_key_b64, sig, b"msg") is False  # signed by A, verified against B


def test_each_keypair_is_distinct():
    a, b = generate_keypair(), generate_keypair()
    assert a.private_key_b64 != b.private_key_b64
    assert a.public_key_b64 != b.public_key_b64


def test_verify_is_total_on_garbage_input():
    """verify() must return False (not raise) on malformed signature/key — an attacker controls these
    bytes, so an exception would be a DoS / error-handling hole at the auth boundary."""
    kp = generate_keypair()
    assert verify(kp.public_key_b64, "not-base64!!", b"msg") is False
    assert verify("not-a-key", sign(kp.private_key_b64, b"msg"), b"msg") is False
    assert verify(kp.public_key_b64, "", b"msg") is False


def test_verify_is_total_on_none_and_wrong_type():
    """verify() must also return False (not raise) when the key or signature is None or a non-str.
    A None public key reaches the boundary if a device row is missing its key; a non-str can arrive
    from a malformed/JSON-decoded header. The previous implementation raised AttributeError on a None
    public key (it skipped the b64-decode guard that only wrapped the signature) — pin that it can't
    recur, so the 'never raises' contract is strictly total."""
    kp = generate_keypair()
    sig = sign(kp.private_key_b64, b"msg")
    # None / non-str public key (the gap that used to raise).
    assert verify(None, sig, b"msg") is False
    assert verify(123, sig, b"msg") is False
    # None / non-str signature.
    assert verify(kp.public_key_b64, None, b"msg") is False
    assert verify(kp.public_key_b64, b"bytes-not-str", b"msg") is False
    # Both bad at once.
    assert verify(None, None, b"msg") is False
