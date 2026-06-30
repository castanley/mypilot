"""SAFETY: the agent must run at yield-to-everything priority so it can never starve the driving
stack's CPU (the regression that caused 'Communication Issue Between Processes' / TAKE-CONTROL alerts).

These cover the pure CPU-list parser and the best-effort `_lower_priority()` (which must never raise,
and must actually lower scheduling where the OS supports it). The thread-inheritance property (a
`to_thread` worker inherits the main thread's policy/affinity) is asserted here too, since the qlog
upload path relies on it.
"""

from __future__ import annotations

import os

import pytest
from mypilot_agent.mypilotd import _lower_priority, _parse_cpu_list


@pytest.mark.parametrize(
    "text,expected",
    [
        ("6-7", {6, 7}),
        ("0,3-5", {0, 3, 4, 5}),
        (" 6-7\n", {6, 7}),
        ("2", {2}),
        ("", set()),
        ("garbage", set()),
        ("0-2,5,7-8", {0, 1, 2, 5, 7, 8}),
    ],
)
def test_parse_cpu_list(text, expected):
    assert _parse_cpu_list(text) == expected


def test_lower_priority_never_raises():
    """Best-effort by contract: on a dev machine / odd topology / missing privilege it must be a
    silent no-op, never an exception that would crash the agent before it even connects."""
    _lower_priority()  # must not raise


@pytest.mark.skipif(not hasattr(os, "sched_getscheduler"), reason="no POSIX scheduler control")
def test_lower_priority_sets_idle_policy_when_supported():
    if not hasattr(os, "SCHED_IDLE"):
        pytest.skip("SCHED_IDLE not available on this kernel")
    _lower_priority()
    # On Linux with SCHED_IDLE, the calling thread's policy should now be SCHED_IDLE.
    assert os.sched_getscheduler(0) == os.SCHED_IDLE


@pytest.mark.skipif(
    not (hasattr(os, "sched_getaffinity") and hasattr(os, "sched_getscheduler")),
    reason="no POSIX affinity/scheduler control",
)
def test_to_thread_worker_inherits_scheduling():
    """The qlog-extraction worker is the one CPU-heavy path; it runs via asyncio.to_thread and relies
    on inheriting the main thread's low-priority policy. New threads inherit the creator's sched policy
    + affinity on Linux, and the agent lowers priority before any worker spawns — verify that holds."""
    import asyncio

    if not hasattr(os, "SCHED_IDLE"):
        pytest.skip("SCHED_IDLE not available on this kernel")

    async def main():
        _lower_priority()
        main_policy = os.sched_getscheduler(0)
        main_aff = os.sched_getaffinity(0)
        worker_policy, worker_aff = await asyncio.to_thread(
            lambda: (os.sched_getscheduler(0), os.sched_getaffinity(0))
        )
        return main_policy, main_aff, worker_policy, worker_aff

    mp, ma, wp, wa = asyncio.run(main())
    assert wp == mp == os.SCHED_IDLE
    assert wa == ma
