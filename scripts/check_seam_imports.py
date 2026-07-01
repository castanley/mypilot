#!/usr/bin/env python3
"""Guard: a handful of module-level functions are *late-bound* and must always be called
module-qualified — never imported as a bare symbol.

Why this matters
----------------
A deployment may replace certain module-level functions at startup to layer in extra behavior —
for example an additional per-object access check on ``app.ownership.owns_device``, or storage
accounting/instrumentation around ``app.storage.put_object`` / ``delete_object``. That replacement
only takes effect for call sites that look the function up *through its module at call time*::

    from .. import ownership
    ...
    if await ownership.owns_device(user, device, db):   # honors a runtime replacement

A symbol import binds the ORIGINAL function once, at import time, so the call site keeps invoking
the un-replaced version no matter what the startup wiring does — silently, with no error and no
failing test (behavior is unchanged unless a replacement is installed)::

    from ..ownership import owns_device          # BANNED — captures the original
    from ..ownership import owns_device as check  # BANNED — alias evades a name grep, same bug

This guard fails the build on that import style so the late-binding seam can't be defeated by an
otherwise-innocent refactor. It is purely about *import style*; it does not care who, if anyone,
replaces the functions.

Scope
-----
Only flags importing one of the GUARDED SYMBOLS *from its guarded module*. Importing the module
itself (``from .. import ownership`` / ``import storage``) is correct and never flagged. Importing
OTHER names from those modules (e.g. ``device_owner_filter``, ``get_object``) is fine.

Usage
-----
    python scripts/check_seam_imports.py [PATH ...]      # default: the api app + its tests
    python scripts/check_seam_imports.py --selftest      # prove the guard flags the bad style

Exit code 0 = clean, 1 = violation(s) found, 2 = self-test failed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# (module-name → the symbols that must be called module-qualified, never imported directly).
# A module matches when an import's source path ENDS with this name (so both ``..ownership`` and
# ``app.ownership`` match). Keep this list tiny and explicit — each entry is a function some
# deployment may replace at runtime.
GUARDED: dict[str, frozenset[str]] = {
    "ownership": frozenset({"owns_device"}),
    "storage": frozenset({"put_object", "delete_object"}),
}

# Default scan roots, relative to the repo root (this file lives in scripts/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROOTS = [
    _REPO_ROOT / "mypilot-stack" / "api" / "app",
    _REPO_ROOT / "mypilot-stack" / "api" / "tests",
]


class Violation:
    __slots__ = ("path", "lineno", "module", "symbol", "alias")

    def __init__(self, path: str, lineno: int, module: str, symbol: str, alias: str | None):
        self.path = path
        self.lineno = lineno
        self.module = module
        self.symbol = symbol
        self.alias = alias

    def __str__(self) -> str:
        shown = f"{self.symbol} as {self.alias}" if self.alias else self.symbol
        return (
            f"{self.path}:{self.lineno}: `from {self.module} import {shown}` binds a late-bound "
            f"function at import time — import the module and call `{_last(self.module)}.{self.symbol}(...)` instead"
        )


def _last(module: str) -> str:
    """Last dotted component of a (possibly relative) module path: '..app.ownership' -> 'ownership'."""
    return module.rstrip(".").split(".")[-1] if module else module


def _guarded_symbols_for(module: str | None) -> frozenset[str]:
    """The guarded symbols if this ImportFrom source is a guarded module, else empty."""
    if not module:
        return frozenset()  # `from . import x` / `from .. import x` — no module name, it's a pkg import
    return GUARDED.get(_last(module), frozenset())


def scan_source(src: str, path: str) -> list[Violation]:
    """Return any guarded symbol-imports in ``src``. AST-based, so comments/strings can't false-hit
    and the ``as`` alias form is caught (we read the imported name, not the local binding)."""
    tree = ast.parse(src, filename=path)
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        # node.module is None for `from . import ownership` (that's a MODULE import — allowed).
        guarded = _guarded_symbols_for(node.module)
        if not guarded:
            continue
        for alias in node.names:
            if alias.name in guarded:
                out.append(
                    Violation(path, node.lineno, node.module or "", alias.name, alias.asname)
                )
    return out


def scan_paths(paths: list[Path]) -> list[Violation]:
    out: list[Violation] = []
    for root in paths:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for f in files:
            if "__pycache__" in f.parts:
                continue
            try:
                out.extend(scan_source(f.read_text(encoding="utf-8"), str(f)))
            except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - report, don't crash
                print(f"{f}: could not parse ({exc})", file=sys.stderr)
    return out


_SELFTEST_BAD = [
    "from ..ownership import owns_device",
    "from ..ownership import owns_device as check",
    "from app.ownership import owns_device, device_owner_filter",  # only owns_device is the hit
    "from ..storage import put_object",
    "from . storage import delete_object".replace(". storage", ".storage"),
    "from ..storage import put_object as _put, get_object",  # only put_object is the hit
]
_SELFTEST_GOOD = [
    "from .. import ownership",
    "from . import storage",
    "import storage",
    "from ..ownership import device_owner_filter",  # a non-guarded symbol from a guarded module
    "from ..storage import get_object, object_size, ObjectNotFound",
    "from ..models import Device, User",
    "owned = device.owner_id == user.id  # not an import at all",
]


def _selftest() -> int:
    ok = True
    for sample in _SELFTEST_BAD:
        if not scan_source(sample, "<bad>"):
            print(f"SELFTEST FAIL: guard MISSED a banned import: {sample!r}", file=sys.stderr)
            ok = False
    for sample in _SELFTEST_GOOD:
        hits = scan_source(sample, "<good>")
        if hits:
            print(f"SELFTEST FAIL: guard FALSE-FLAGGED a legit line: {sample!r} -> {hits[0]}", file=sys.stderr)
            ok = False
    # The mixed-import samples must flag exactly ONE symbol each (the guarded one), not the sibling.
    mixed = scan_source("from app.ownership import owns_device, device_owner_filter", "<mixed>")
    if len(mixed) != 1 or mixed[0].symbol != "owns_device":
        print(f"SELFTEST FAIL: mixed import should flag only owns_device, got {[str(v) for v in mixed]}", file=sys.stderr)
        ok = False
    if ok:
        print("seam-import guard self-test: OK (flags the banned style, passes legit module imports)")
        return 0
    return 2


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    roots = [Path(a) for a in argv] if argv else _DEFAULT_ROOTS
    violations = scan_paths(roots)
    if violations:
        print("Late-bound seam functions must be called module-qualified, not imported directly:\n", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            f"\n{len(violations)} violation(s). Import the module (e.g. `from .. import ownership`) "
            "and call it qualified, so a runtime replacement of the function is honored.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
