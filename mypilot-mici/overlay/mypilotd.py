#!/usr/bin/env python3
"""MyPilot agent launcher — the openpilot ``PythonProcess`` target.

CRITICAL (this is what makes the device boot): this module imports **nothing** at module load.
openpilot's manager pre-imports every PythonProcess module during ``manager_prepare()`` at boot, so
this file must be trivial to import — it only defines ``main()``. All real work (putting the
vendored ``mypilot_agent``/``mypilot_protocol`` packages on ``sys.path`` and running the agent)
happens inside ``main()``, in the forked child process, fully guarded.

We can't use a ``DaemonProcess`` here (that needs a PID param declared in ``params_keys.h``, which is
compiled in — impossible to add on a *prebuilt* branch). So we mirror sunnypilot's plain
``PythonProcess`` daemons (mapd_manager etc.) but keep the import side-effect-free. The agent is a
non-critical sidecar: it can never block boot or affect driving.
"""


def main() -> None:
    import os
    import sys
    import traceback

    # The vendored agent + protocol packages live next to this file.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from mypilot_agent.mypilotd import main as agent_main

        agent_main()
    except Exception:
        # Non-critical: log and exit cleanly. NEVER propagate — the manager must stay healthy.
        traceback.print_exc()


if __name__ == "__main__":
    main()
