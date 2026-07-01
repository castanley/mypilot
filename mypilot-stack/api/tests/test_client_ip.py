"""client_ip trust order: X-Real-Client-IP -> last X-Forwarded-For hop -> socket peer (fail-closed).

client_ip keys the per-IP rate limiter and stamps audit events, so getting the trusted source right
is a security property: the value must come from the reverse proxy, never a client-supplied header,
and it must degrade safely when a header is absent (self-hosted single-proxy / dev)."""

from __future__ import annotations

from app.deps import client_ip


class _Headers(dict):
    """Case-insensitive header lookup, like Starlette's Headers (which client_ip relies on)."""

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _Client:
    def __init__(self, host):
        self.host = host


class _Request:
    def __init__(self, headers=None, peer="10.0.0.1"):
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.client = _Client(peer) if peer is not None else None


def test_prefers_x_real_client_ip_over_forwarded_for():
    # The proxy-set real-client header is authoritative even when XFF carries other (client-supplied) hops.
    req = _Request({"X-Real-Client-IP": "9.9.9.9", "X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, peer="10.0.0.1")
    assert client_ip(req) == "9.9.9.9"


def test_falls_back_to_last_forwarded_hop_when_no_real_client_header():
    # No proxy real-client header: take the LAST XFF hop (the proxy-appended genuine peer), never the
    # first (client-controlled).
    req = _Request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, peer="10.0.0.1")
    assert client_ip(req) == "5.6.7.8"


def test_falls_back_to_socket_peer_when_no_proxy_headers():
    # Self-hosted single-proxy / dev: neither header present -> fail-closed to the real socket peer.
    req = _Request({}, peer="203.0.113.7")
    assert client_ip(req) == "203.0.113.7"


def test_empty_or_whitespace_real_client_header_falls_through():
    # A present-but-empty real-client header must not shadow the XFF fallback.
    req = _Request({"X-Real-Client-IP": "   ", "X-Forwarded-For": "1.2.3.4"}, peer="10.0.0.1")
    assert client_ip(req) == "1.2.3.4"


def test_real_client_header_is_case_insensitive():
    req = _Request({"x-real-client-ip": "8.8.4.4"}, peer="10.0.0.1")
    assert client_ip(req) == "8.8.4.4"


def test_none_when_no_headers_and_no_client():
    req = _Request({}, peer=None)
    assert client_ip(req) is None


def test_real_client_header_value_is_trimmed():
    req = _Request({"X-Real-Client-IP": "  7.7.7.7  "}, peer="10.0.0.1")
    assert client_ip(req) == "7.7.7.7"


def test_duplicate_real_client_header_keys_on_first_token():
    # If two copies of the header reach the app they comma-join ("ip1,ip2"). Key on the FIRST token
    # only, so a duplicate can't produce a malformed rate-limit key. (The proxy sets this header
    # itself, so its value leads; a client-injected dup would be appended after.)
    req = _Request({"X-Real-Client-IP": "9.9.9.9, 6.6.6.6"}, peer="10.0.0.1")
    assert client_ip(req) == "9.9.9.9"
    # ...with surrounding whitespace on the tokens too.
    req2 = _Request({"X-Real-Client-IP": "  9.9.9.9 ,  6.6.6.6 "}, peer="10.0.0.1")
    assert client_ip(req2) == "9.9.9.9"
