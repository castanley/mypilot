"""DrivingTelemetry coordinate validation — reject non-finite / out-of-range at the ingest boundary.

A device (or a spoofed heartbeat) sending NaN/inf or |lat|>90 / |lon|>180 must be rejected before the
value can reach the live-trail accumulator, where it is a live per-device DoS (inf -> math.cos(inf) ->
ValueError crashes the heartbeat every beat; NaN freezes the trail). None stays valid — GPS warms up
~20-30s so an early-drive position is legitimately absent.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
from app.schemas import DrivingTelemetry
from pydantic import ValidationError


@pytest.mark.parametrize(
    "lat,lon",
    [
        (float("inf"), -122.0),
        (float("-inf"), -122.0),
        (float("nan"), -122.0),
        (37.0, float("inf")),
        (37.0, float("nan")),
        (90.0001, -122.0),   # just past the lat pole
        (-90.5, -122.0),
        (37.0, 180.5),       # just past the antimeridian
        (37.0, -181.0),
        ("nan", -122.0),     # numeric-string smuggling a non-finite
        ("inf", -122.0),
    ],
)
def test_rejects_bad_coords(lat, lon):
    with pytest.raises(ValidationError):
        DrivingTelemetry(latitude=lat, longitude=lon)


@pytest.mark.parametrize(
    "lat,lon",
    [
        (37.5, -122.3),
        (0.0, 0.0),
        (90.0, 180.0),       # exact bounds are valid
        (-90.0, -180.0),
        (None, None),        # GPS warming up / offroad — legitimately absent
        (37.5, None),        # partial fix
    ],
)
def test_accepts_valid_coords(lat, lon):
    m = DrivingTelemetry(latitude=lat, longitude=lon)
    if lat is not None:
        assert math.isfinite(m.latitude)
    if lon is not None:
        assert math.isfinite(m.longitude)


def test_other_fields_unaffected():
    m = DrivingTelemetry(speed_ms=12.0, heading_deg=90.0, latitude=37.0, longitude=-122.0,
                         accuracy_m=3.5, gear="drive")
    assert m.latitude == 37.0 and m.longitude == -122.0 and m.gear == "drive"


@pytest.mark.parametrize("bad", [True, False])
def test_bool_coordinate_rejected(bad):
    """bool is an int subtype, so float(True)==1.0 would silently pass as a real coordinate (0,0-ish)."""
    with pytest.raises(ValidationError):
        DrivingTelemetry(latitude=bad, longitude=-122.0)


# --- HTTP transport: a non-finite coordinate literal must yield a clean 422, not a 500. ---
# FastAPI echoes the raw input in the validation-error detail, and Starlette's JSONResponse renders with
# json.dumps(allow_nan=False) — so a raw `NaN`/`Infinity` literal in the body would make the ERROR
# RESPONSE render crash -> 500, masking the 422 and polluting error monitoring. A genuinely-buggy device
# emitting a real NaN hits exactly this. The app installs a RequestValidationError handler that scrubs
# non-finite floats so the 422 always renders. We test the app's REGISTERED handler directly (a raw NaN
# literal can't traverse TestClient's JSON encoder, and a copied sub-app doesn't wire the validation
# handler through Starlette the same way — testing the handler is the faithful, hermetic check).

def _registered_validation_handler():
    from app.main import create_app
    from fastapi.exceptions import RequestValidationError
    return create_app().exception_handlers[RequestValidationError]


async def _run_handler_on(errors: list) -> tuple[int, bytes]:
    """Invoke the app's RequestValidationError handler with a synthetic error list and return
    (status_code, rendered_body). Rendering the body is the crux — it's where a non-finite echoed input
    would crash (json.dumps(allow_nan=False)) and turn a 422 into a 500."""
    from fastapi.exceptions import RequestValidationError
    handler = _registered_validation_handler()
    resp = await handler(None, RequestValidationError(errors))
    return resp.status_code, resp.body  # .body render happens here; must not raise


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_input", [float("nan"), float("inf"), float("-inf"), 200.0, "nan"])
async def test_non_finite_validation_error_renders_as_422(bad_input):
    """A validation error whose echoed `input` is a non-finite float must still render as a clean 422 —
    the scrub in the handler prevents the allow_nan=False render crash that would surface as a 500."""
    errors = [{
        "type": "value_error",
        "loc": ("body", "subsystems", "driving", "latitude"),
        "msg": "Value error, coordinate must be finite (no NaN/inf)",
        "input": bad_input,
        "ctx": {"error": ValueError("coordinate must be finite (no NaN/inf)")},
    }]
    status, body = await _run_handler_on(errors)
    assert status == 422
    import json
    parsed = json.loads(body)  # the rendered body is valid JSON (no bare NaN/Infinity tokens)
    assert parsed.get("detail")


def test_heartbeat_with_bad_coordinate_is_rejected_not_crashed():
    """End-to-end at the model layer: a bad coordinate in a heartbeat payload raises ValidationError
    (rejected), never reaching the accumulator — and a valid one parses fine."""
    from app.schemas import HeartbeatRequest
    with pytest.raises(ValidationError):
        HeartbeatRequest(onroad=True, subsystems={"driving": {"latitude": float("nan"), "longitude": -122.0}})
    ok = HeartbeatRequest(onroad=True, subsystems={"driving": {"latitude": 37.5, "longitude": -122.0}})
    assert ok.subsystems.driving.latitude == 37.5


def _try_catches_validation_error(node: ast.Try) -> bool:
    for h in node.handlers:
        names: list[str] = []
        if isinstance(h.type, ast.Name):
            names = [h.type.id]
        elif isinstance(h.type, ast.Tuple):
            names = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
        if "ValidationError" in names:
            return True
    return False


def test_ws_status_frame_parse_is_guarded_against_validation_error():
    """SB-B (structural guard): a single malformed STATUS frame on the device WebSocket must NOT escape
    to the connection-level handler (whose finally clause runs set_offline and flaps the device's
    socket/presence/trail). The STATUS branch must build HeartbeatRequest inside a try that catches
    ValidationError and `continue`s past the bad frame. AST-checked so a refactor that drops the guard
    fails the build. (A full WS behavioral test needs the signed auth handshake; this pins the specific
    resilience property cheaply and reliably.)"""
    src = (Path(__file__).resolve().parent.parent / "app" / "routers" / "realtime.py").read_text()
    tree = ast.parse(src)

    total_calls = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "HeartbeatRequest"
    )
    assert total_calls >= 1, "expected HeartbeatRequest to be constructed in the WS handler"

    # Count HeartbeatRequest calls that sit inside a ValidationError-catching Try.
    guarded_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and _try_catches_validation_error(node):
            guarded_calls += sum(
                1 for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "HeartbeatRequest"
            )

    assert guarded_calls == total_calls, (
        "every HeartbeatRequest(...) in the WS handler must be built inside a try/except ValidationError "
        "so one bad frame can't tear down the connection"
    )
