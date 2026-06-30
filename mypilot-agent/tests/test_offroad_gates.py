"""SAFETY: every driving-affecting agent action must be refused while the car is ONROAD.

This is the agent's most important invariant — a remote command/setting from the Stack must never take
effect on a moving car, regardless of what the Stack sent. The agent is the device-authoritative gate
(defense-in-depth under the Stack's own gate): it re-reads onroad freshly and refuses if onroad.

These tests construct a RealDevice off-device (no openpilot -> _params is None) and drive the `onroad`
property via a stub, so the gate logic is exercised without a car or cereal.
"""

from __future__ import annotations

import pytest
from mypilot_agent.backends.real import RealDevice


class _Params:
    """Minimal stand-in for the on-device Params: records writes, satisfies the gate's needs."""

    def __init__(self) -> None:
        self.puts: dict = {}
        self.removed: list = []

    def put(self, k, v):
        self.puts[k] = v

    def put_bool(self, k, v):
        self.puts[k] = bool(v)

    def remove(self, k):
        self.removed.append(k)

    def get(self, k):
        return None


def _device(*, onroad: bool) -> RealDevice:
    """A RealDevice whose onroad gate reads a deterministic value. The real `onroad` property prefers
    `self._params.get_bool("IsOnroad")`, so we give the stub Params that method."""
    d = RealDevice("hw-test", "host")
    d._params = _Params()
    d._params.get_bool = lambda key, _o=onroad: _o  # type: ignore[attr-defined]
    assert d.onroad is onroad  # the gate reads what we pinned
    return d


# --- apply_setting -------------------------------------------------------------------------------

def test_apply_setting_refused_onroad():
    d = _device(onroad=True)
    ok, detail = d.apply_setting("SomeToggle", True)
    assert ok is False
    assert "onroad" in detail.lower()
    assert d._params.puts == {}  # nothing was written


def test_apply_setting_allowed_offroad():
    d = _device(onroad=False)
    ok, detail = d.apply_setting("SomeToggle", True)
    assert ok is True
    assert d._params.puts == {"SomeToggle": True}


# --- execute(reboot / switch_model / software_update / restore_settings) -------------------------

@pytest.mark.parametrize(
    "name,args",
    [
        ("reboot", {}),
        ("switch_model", {"model_key": "some-ref"}),
        ("software_update", {"branch": "some-branch"}),
        ("restore_settings", {"settings": {"A": True, "B": 3}}),
    ],
)
async def test_execute_refused_onroad(name, args):
    d = _device(onroad=True)
    ok, detail = await d.execute(name, args)
    assert ok is False
    assert "onroad" in detail.lower()
    # No Params mutation of any kind happened while onroad.
    assert d._params.puts == {}
    assert d._params.removed == []


async def test_restore_settings_offroad_applies_all():
    d = _device(onroad=False)
    ok, detail = await d.execute("restore_settings", {"settings": {"A": True, "B": 3}})
    assert ok is True
    assert d._params.puts == {"A": True, "B": 3}


async def test_unknown_command_is_rejected_not_executed():
    d = _device(onroad=False)
    ok, detail = await d.execute("delete_everything", {})
    assert ok is False
    assert "unknown command" in detail.lower()


def test_onroad_is_read_fresh_each_call_not_cached():
    """The gate must reflect a fresh onroad read every time (a stale cache could let a queued change
    ride an offroad->onroad transition). Flip the stub and confirm the gate flips with it."""
    d = _device(onroad=False)
    assert d.apply_setting("X", True)[0] is True
    d._params.get_bool = lambda key: True  # car just went onroad
    ok, detail = d.apply_setting("Y", True)
    assert ok is False and "onroad" in detail.lower()
