"""HARDEN-1 (Part A) — ARCHITECTURAL authz-chokepoint regression test (structural / AST).

The behavioral isolation test (test_owner_scoping.py) proves the routes that EXIST are owner-scoped.
This test guards the route that does NOT exist yet: it FAILS the build when a new or refactored
single-object access path reaches a device-owned object WITHOUT going through the one chokepoint,
`ownership.owns_device(user, device, db)` — called MODULE-QUALIFIED and WITH the db session.

Why module-qualified + with db: `owns_device` is late-bound (a deployment may wrap it at startup to
add an extra per-call access gate). A bare `owns_device(...)` import captures the original (HARDEN-2
lints that), and a call that DROPS db takes the no-session early-return that skips the wrapped gate —
both are the documented #1 silent regression. This file pins the positive at the call site; HARDEN-2
bans the bad import globally.

Design (per HARDEN-1-SPEC.md, Security-owned):
  A1  NEGATIVE: no single-object inline `*.owner_id ==/!= *.id` (both orderings) outside a closed,
      function-granular allowlist. Comparisons that are arguments to `.where()/.filter()` (list
      scoping) are NOT flagged. Scoped to `owner_id` specifically — `created_by` user-scoping is a
      different, correct gate and must not trip this.
  A3  POSITIVE, FOLLOWING THE HELPER LAYER: each sanctioned ownership helper body must terminate in a
      module-qualified `owns_device(..., db)` call with a real db arg; this fail-closes on an inline
      bypass planted INSIDE a helper (which an endpoint-body-only scan would miss).
  A4  Allowlists are CLOSED and function-granular. A new inline owner-compare ANYWHERE else fails.

AST-based (not regex) so comments/strings/docstrings can't create false hits, and so the `!=`
imperative-guard form and both operand orderings are matched reliably. Runs in /tmp/pubcore-venv.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
_ROUTERS = _APP / "routers"

# --- Scope of the scan -------------------------------------------------------------------------
# Files that load single user-owned objects by id for a SESSION-authenticated request. Device-signed
# and pre-ownership paths are out of scope (see _OUT_OF_SCOPE) and excluded explicitly, not silently.
_IN_SCOPE_FILES = [
    _ROUTERS / "routes.py",
    _ROUTERS / "backups.py",
    _ROUTERS / "devices.py",
    _ROUTERS / "models.py",
    _ROUTERS / "software.py",
    _ROUTERS / "settings.py",
    _ROUTERS / "devtools.py",
    _APP / "routes_service.py",
]

# --- A4 allowlists (CLOSED, function-granular, commented) --------------------------------------
# Category 1 — sanctioned OWNERSHIP helpers: each MUST terminate in module-qualified owns_device(...,db).
#   A new id-param endpoint must reach owns_device directly or via one of these.
_OWNS_DEVICE_HELPERS: set[tuple[str, str]] = {
    ("routes.py", "_owned_device"),
    ("routes.py", "_owned_route"),
    ("routes.py", "_owned_log"),
    ("backups.py", "_owned_device"),
    ("devices.py", "_owned_device"),
    ("models.py", "_owned"),     # models.py names its helper `_owned`, not `_owned_device`
    ("software.py", "_owned"),   # software.py likewise
    ("settings.py", "_owned"),   # settings.py likewise (helper at settings.py:_owned, calls owns_device(...,db))
}

# Category 2 — sanctioned USER-SCOPED (created_by) gate; a Backup is a user-owned settings snapshot
#   keyed to its creator, NOT device-owned, so it does NOT (and must not) call owns_device.
#   Access isolation is still enforced via `backup.created_by == user.id` (a user may read only its
#   OWN backups). By-design: the device-ownership gate does not apply to a user-owned snapshot.
_CREATED_BY_HELPERS: set[tuple[str, str]] = {
    ("backups.py", "_owned_backup"),
}

# A1 inline-compare allowlist — pre-existing accepted-LOW (F6): admin-only + is_simulated + still
# owner==self, no real-device/driving reach. TODO: route these through
# `ownership.owns_device(...) and device.is_simulated` (owns_device does NOT check is_simulated, so
# that extra guard must stay) and then delete these entries.
_SANCTIONED_INLINE: set[tuple[str, str]] = {
    ("devtools.py", "_owned_sim"),
    ("devtools.py", "replay_drive"),
}

# Documented OUT-OF-SCOPE (correctly do NOT use owns_device — excluded so their absence isn't a gap):
#   ingest.py, device_self.py  -> Ed25519 device-signed (act on the signed device.id)
#   realtime.py                -> server-side owner-scoping (manager.add_web(ws, user.id)) + challenge
#   pairing.py                 -> pre-ownership handshake
#   routes_service.run_retention / delete_all_routes -> global admin janitor / .where list-scope
_OUT_OF_SCOPE = {"ingest.py", "device_self.py", "realtime.py", "pairing.py"}


# ================================================================================================
# AST helpers
# ================================================================================================
def _attr_tail(node: ast.expr) -> str | None:
    """Final attribute name of an attribute access, e.g. `device.owner_id` -> 'owner_id'."""
    return node.attr if isinstance(node, ast.Attribute) else None


def _is_owner_id(node: ast.expr) -> bool:
    return _attr_tail(node) == "owner_id"


def _enclosing_funcs(tree: ast.AST) -> dict[ast.AST, str]:
    """Map each node to the name of the nearest enclosing function (or '<module>')."""
    owner: dict[ast.AST, str] = {}

    def walk(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            owner[child] = name
            walk(child, name)

    walk(tree, "<module>")
    return owner


def _within_where_filter(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True if `node` is (transitively) an argument to a `.where(...)`/`.filter(...)` call — a
    sanctioned LIST-scoping filter, not an imperative single-object check."""
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute) and cur.func.attr in {
            "where",
            "filter",
            "filter_by",
        }:
            return True
        cur = parents.get(cur)
    return False


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _parse(path: Path) -> tuple[ast.AST, str]:
    src = path.read_text(encoding="utf-8")
    return ast.parse(src, filename=str(path)), src


def _find_inline_owner_compares(tree: ast.AST) -> list[ast.Compare]:
    """All single-object `*.owner_id ==/!= <x>` Compare nodes — either operator, either operand
    order. We key ONLY on a `.owner_id` operand (device ownership), deliberately NOT on the other
    side's shape: the right side may be `user.id` (Attribute) OR a bare `user_id` param (Name), and
    both are imperative single-object owner checks that bypass the chokepoint. Staying owner_id-
    specific is intentional — a `created_by == user.id` user-scoping gate is a different, correct
    pattern and must not trip this. `.where()/.filter()` list-scoping is excluded by the caller."""
    hits: list[ast.Compare] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            continue
        if _is_owner_id(node.left) or _is_owner_id(node.comparators[0]):
            hits.append(node)
    return hits


def _func_calls(func: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Call)]


def _is_module_qualified_owns_device(call: ast.Call) -> bool:
    """`ownership.owns_device(...)` — an attribute call `owns_device` on something named `ownership`."""
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "owns_device"
        and isinstance(f.value, ast.Name)
        and f.value.id == "ownership"
    )


def _owns_device_call_has_db(call: ast.Call) -> bool:
    """True iff the owns_device call passes a db arg that isn't literal None.

    Accepts a 3rd POSITIONAL arg or a `db=`/`session=` kwarg. Rejects a missing arg (hits the
    no-session early-return that skips the wrapped gate) and an explicit `None`."""
    # Positional: owns_device(user, device, db)
    if len(call.args) >= 3:
        third = call.args[2]
        if not (isinstance(third, ast.Constant) and third.value is None):
            return True
    # Keyword: owns_device(user, device, db=db). Compare the Constant's VALUE (kw.value.value), not
    # the AST node identity (kw.value is None is always False) — else owns_device(..., db=None) would
    # be wrongly accepted, which is the exact no-session bypass this check exists to catch.
    for kw in call.keywords:
        if kw.arg in {"db", "session"}:
            if not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                return True
    return False


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    """Top-level + nested function defs by name (last definition wins; names are unique per file here)."""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


# ================================================================================================
# A1 — NO inlined single-object owner comparison outside the allowlist
# ================================================================================================
def test_a1_no_unsanctioned_inline_owner_compare():
    offenders: list[str] = []
    for path in _IN_SCOPE_FILES:
        tree, _ = _parse(path)
        parents = _parent_map(tree)
        func_of = _enclosing_funcs(tree)
        for cmp_node in _find_inline_owner_compares(tree):
            if _within_where_filter(cmp_node, parents):
                continue  # sanctioned LIST-scoping (.where/.filter) — not an imperative check
            func = func_of.get(cmp_node, "<module>")
            if (path.name, func) in _SANCTIONED_INLINE:
                continue  # closed F6 allowlist
            offenders.append(f"{path.name}:{cmp_node.lineno} (in {func}()) inline owner_id compare")
    assert not offenders, (
        "Unsanctioned inline single-object owner check(s) — route through "
        "ownership.owns_device(user, device, db) instead:\n  " + "\n  ".join(offenders)
    )


# ================================================================================================
# A3 — each sanctioned ownership helper terminates in module-qualified owns_device(..., db)
# ================================================================================================
@pytest.mark.parametrize("file_name,func_name", sorted(_OWNS_DEVICE_HELPERS))
def test_a3_owns_device_helper_calls_chokepoint_with_db(file_name: str, func_name: str):
    tree, _ = _parse(_ROUTERS / file_name)
    func = _functions(tree).get(func_name)
    assert func is not None, f"sanctioned helper {file_name}:{func_name} not found — inventory drift"
    owns_calls = [c for c in _func_calls(func) if _is_module_qualified_owns_device(c)]
    assert owns_calls, (
        f"{file_name}:{func_name} must call module-qualified ownership.owns_device(...) — "
        "a bare owns_device(...) would bind the original at import time and bypass the runtime gate"
    )
    assert any(_owns_device_call_has_db(c) for c in owns_calls), (
        f"{file_name}:{func_name} calls owns_device WITHOUT a db arg — that hits the no-session "
        "early-return and skips the wrapped per-call access gate (the #1 silent bypass)"
    )


def test_a3_created_by_helpers_do_not_falsely_require_owns_device():
    """Category-2 (created_by) helpers are user-scoped by design and must NOT be expected to call
    owns_device. Pin that they exist and gate on a created_by comparison, so a refactor that drops
    their gate entirely is still visible."""
    for file_name, func_name in sorted(_CREATED_BY_HELPERS):
        tree, _ = _parse(_ROUTERS / file_name)
        func = _functions(tree).get(func_name)
        assert func is not None, f"{file_name}:{func_name} not found — inventory drift"
        has_created_by = any(
            isinstance(n, ast.Compare)
            and len(n.ops) == 1
            and isinstance(n.ops[0], (ast.Eq, ast.NotEq))
            and (_attr_tail(n.left) == "created_by" or _attr_tail(n.comparators[0]) == "created_by")
            for n in ast.walk(func)
        )
        assert has_created_by, f"{file_name}:{func_name} no longer gates on created_by — gate dropped?"


# ================================================================================================
# A3 (coverage) — every id-param session route reaches the chokepoint via a sanctioned helper or
# an inline module-qualified owns_device(..., db) (settings.py pattern). Enumerating the LIVE route
# table (not a static list) is what makes a NEW route auto-appear and FAIL until it gates.
# ================================================================================================
_ID_PARAMS = {"device_id", "route_id", "log_id", "backup_id", "key"}
# `key` (settings) only ever appears alongside device_id, so device-scoping covers it; listed for clarity.
_SINGLE_OBJECT_ID_PARAMS = {"device_id", "route_id", "log_id", "backup_id"}

# Routes that take an id path-param but are NOT single-object owner-gated access, with the reason.
# Closed + commented so a new id-param route can't hide here silently.
_COVERAGE_EXCEPTIONS: dict[str, str] = {
    # (no current entries — all id-param session routes are owner-gated. Add with a reason if ever needed.)
}


def _session_authed(func: ast.AST) -> bool:
    """Heuristic: the handler depends on a user/session auth dependency (get_current_user/
    get_current_auth/require_csrf/require_admin*). Device-signed handlers use get_authenticated_device."""
    src = ast.dump(func)
    return any(
        dep in src
        for dep in (
            "get_current_user",
            "get_current_auth",
            "require_csrf",
            "require_admin",
            "require_admin_csrf",
        )
    )


def _reaches_chokepoint(func: ast.AST, file_name: str) -> bool:
    """True if the handler reaches owns_device directly (module-qualified, with db) OR calls a
    sanctioned gate helper. Helpers are matched by (FILE, func), NOT bare name: the gate helpers are
    per-file privates, so `(file_name, helper)` must be the sanctioned tuple. Matching by bare name
    would let a globally-sanctioned helper name (e.g. `_owned`, which models.py/software.py/settings.py
    each define) vouch for a DIFFERENT file's same-named helper that may not actually gate — the
    false-green Audit caught. Sanctioned = a Category-1 owns_device helper, a Category-2 created_by
    helper, or an F6-allowlisted inline helper (devtools `_owned_sim` — sim-only/admin-only accepted-LOW,
    gates owner==self + is_simulated inline by design). Category-1 helpers are independently asserted to
    terminate in owns_device(...,db) by test_a3_owns_device_helper_calls_chokepoint_with_db, so a gutted
    one fails THERE; this (file,func) match stops cross-file vouching here."""
    sanctioned_here = (
        {h for (f, h) in _OWNS_DEVICE_HELPERS if f == file_name}
        | {h for (f, h) in _CREATED_BY_HELPERS if f == file_name}
        | {h for (f, h) in _SANCTIONED_INLINE if f == file_name}
    )
    for call in _func_calls(func):
        if _is_module_qualified_owns_device(call) and _owns_device_call_has_db(call):
            return True
        f = call.func
        if isinstance(f, ast.Name) and f.id in sanctioned_here:
            return True
        if isinstance(f, ast.Attribute) and f.attr in sanctioned_here:
            return True
    return False


def test_a3_coverage_every_id_param_session_route_reaches_chokepoint():
    """Walk the live FastAPI route table; for each session-authed handler with a single-object id
    path-param, assert it reaches the chokepoint. A new such route that forgets to gate FAILS here."""
    import os

    os.environ.setdefault("MYPILOT_ENV", "test")
    os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    from app.main import create_app

    app = create_app()

    # Pre-parse every in-scope router file's functions once.
    parsed: dict[str, dict[str, ast.AST]] = {}
    for p in _IN_SCOPE_FILES:
        if p.parent.name == "routers":
            parsed[p.name] = _functions(_parse(p)[0])

    ungated: list[str] = []
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        # Single-object id path-param?
        params = {seg[1:-1] for seg in path.split("/") if seg.startswith("{") and seg.endswith("}")}
        if not (params & _SINGLE_OBJECT_ID_PARAMS):
            continue
        fname = getattr(endpoint, "__name__", "")
        module = getattr(endpoint, "__module__", "")
        short = module.split(".")[-1] + ".py"
        if short in _OUT_OF_SCOPE:
            continue
        if short not in parsed or fname not in parsed[short]:
            continue  # not one of our in-scope router files (e.g. a mounted plugin route)
        if fname in _COVERAGE_EXCEPTIONS:
            continue
        func = parsed[short][fname]
        if not _session_authed(func):
            continue
        checked += 1
        if not _reaches_chokepoint(func, short):
            ungated.append(f"{short}:{fname} (path {path}) does not reach ownership.owns_device(...,db)")

    assert checked > 0, "coverage check found NO id-param session routes — enumeration is broken"
    assert not ungated, (
        "id-param session route(s) that don't reach the ownership chokepoint:\n  "
        + "\n  ".join(ungated)
    )


# ================================================================================================
# A4 — the allowlists are CLOSED: every sanctioned inline site still exists (no stale entries that
# would mask a real new hit), and inventory hasn't silently drifted.
# ================================================================================================
def test_a4_sanctioned_inline_sites_still_present():
    """Each F6 inline-allowlist entry must still correspond to a real inline owner compare. A stale
    entry (function gone / no longer inline) is removed so the allowlist stays minimal and a future
    real bypass can't hide behind a dead exemption."""
    by_file: dict[str, set[str]] = {}
    for fname, func in _SANCTIONED_INLINE:
        by_file.setdefault(fname, set()).add(func)
    for fname, funcs in by_file.items():
        tree, _ = _parse(_ROUTERS / fname)
        func_of = _enclosing_funcs(tree)
        funcs_with_inline = {
            func_of.get(c, "<module>") for c in _find_inline_owner_compares(tree)
        }
        for func in funcs:
            assert func in funcs_with_inline, (
                f"stale allowlist entry ({fname},{func}): no inline owner compare there anymore — "
                "remove it from _SANCTIONED_INLINE"
            )
