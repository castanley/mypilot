"""The per-heartbeat read cache that keeps status() cheap (so it can't spike the shared cores).

_cached() must: recompute only past its TTL; treat ttl<=0 as cache-once (but retry a transient None
so a not-yet-resolved value like the car platform isn't frozen forever); and _invalidate() must force
the next read to recompute (used after a model switch so the UI reflects it immediately)."""

from __future__ import annotations

from mypilot_agent.backends.real import RealDevice


def _bare_device() -> RealDevice:
    d = RealDevice("hw-test", "host")
    d._cache = {}  # start clean
    return d


def test_cached_recomputes_only_after_ttl(monkeypatch):
    d = _bare_device()
    clock = {"t": 1000.0}
    monkeypatch.setattr("mypilot_agent.backends.real.time.time", lambda: clock["t"])
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return f"v{calls['n']}"

    assert d._cached("k", 10.0, producer) == "v1"  # miss
    assert d._cached("k", 10.0, producer) == "v1"  # hit (within ttl)
    assert calls["n"] == 1
    clock["t"] += 11.0  # ttl elapsed
    assert d._cached("k", 10.0, producer) == "v2"
    assert calls["n"] == 2


def test_cache_once_retries_transient_none_then_sticks():
    d = _bare_device()
    seq = {"vals": [None, "RAM", "later"], "i": -1}

    def producer():
        seq["i"] += 1
        return seq["vals"][seq["i"]]

    assert d._cached("platform", 0, producer) is None   # transient None -> not cached
    assert d._cached("platform", 0, producer) == "RAM"  # resolves -> cached
    assert d._cached("platform", 0, producer) == "RAM"  # cached (producer NOT called again)
    assert seq["i"] == 1  # producer ran exactly twice


def test_invalidate_forces_recompute():
    d = _bare_device()
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return calls["n"]

    assert d._cached("active_model", 30.0, producer) == 1
    assert d._cached("active_model", 30.0, producer) == 1  # cached
    d._invalidate("active_model")
    assert d._cached("active_model", 30.0, producer) == 2  # recomputed after invalidation
