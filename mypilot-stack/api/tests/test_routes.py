"""M4 routes & logs: signed ingest, listing, byte-exact download, delete, and retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .helpers import device_post, device_put, pair_device, setup_admin

ROUTE_NAME = "2026-06-25--08-30-00"


async def _ingest_route(client, device_id, keys, *, name=ROUTE_NAME, payload=b"QLOG-BYTES" * 8):
    start = await device_post(
        client,
        device_id,
        keys,
        "/api/ingest/routes/start",
        {
            "name": name,
            "duration_s": 612,
            "distance_m": 8200.5,
            "segment_count": 1,
            "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}],
        },
    )
    assert start.status_code == 201, start.text
    route_id = start.json()["route_id"]

    put = await device_put(
        client, device_id, keys, f"/api/ingest/routes/{route_id}/files/0/qlog.zst", payload
    )
    assert put.status_code == 200, put.text

    comp = await device_post(
        client, device_id, keys, f"/api/ingest/routes/{route_id}/complete", {}
    )
    assert comp.status_code == 200, comp.text
    return route_id


async def test_route_ingest_list_download_delete(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    payload = b"QLOG-REAL-BYTES-0123456789" * 6
    route_id = await _ingest_route(client, device_id, keys, payload=payload)

    # Web list reflects the completed upload + accumulated size.
    lst = await client.get(f"/api/devices/{device_id}/routes")
    assert lst.status_code == 200, lst.text
    rows = lst.json()
    assert len(rows) == 1
    assert rows[0]["upload_status"] == "complete"
    assert rows[0]["size_bytes"] == len(payload)
    assert rows[0]["distance_m"] == 8200.5

    # Detail exposes the per-segment files.
    detail = await client.get(f"/api/routes/{route_id}")
    assert detail.status_code == 200, detail.text
    files = detail.json()["files"]
    assert len(files) == 1 and files[0]["uploaded"] is True
    file_id = files[0]["id"]

    # Download returns the exact bytes the device uploaded.
    dl = await client.get(f"/api/routes/{route_id}/files/{file_id}/download")
    assert dl.status_code == 200
    assert dl.content == payload

    # Delete removes it from the listing.
    d = await client.request("DELETE", f"/api/routes/{route_id}", headers={"X-CSRF-Token": csrf})
    assert d.status_code == 200, d.text
    assert (await client.get(f"/api/devices/{device_id}/routes")).json() == []
    # Bytes are gone too.
    assert (await client.get(f"/api/routes/{route_id}/files/{file_id}/download")).status_code == 404


async def test_missing_object_serves_404_not_500(client):
    """A RouteFile row whose stored bytes are absent (swept, or never landed) must 404 — never 500.
    Mirrors a real prod state where the DB row outlived its object."""
    from app import storage

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    route_id = await _ingest_route(client, device_id, keys, payload=b"VIDEO" * 10)
    detail = await client.get(f"/api/routes/{route_id}")
    file_id = detail.json()["files"][0]["id"]

    # The row still says uploaded=true, but drop the object out from under it.
    storage._MEM.clear()

    assert (await client.get(f"/api/routes/{route_id}/files/{file_id}/download")).status_code == 404
    assert (await client.get(f"/api/routes/{route_id}/files/{file_id}/stream")).status_code == 404
    # Range request on the missing object is also a clean 404 (not 500).
    r = await client.get(f"/api/routes/{route_id}/files/{file_id}/stream", headers={"Range": "bytes=0-3"})
    assert r.status_code == 404


async def test_reconcile_storage_flags_orphaned_files(client):
    """Admin maintenance: rows whose object is gone get uploaded=false (UI stops offering a broken
    download); route metadata is kept. Idempotent + admin-gated."""
    from app import storage

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    route_id = await _ingest_route(client, device_id, keys, payload=b"BYTES" * 20)
    detail = await client.get(f"/api/routes/{route_id}")
    assert detail.json()["files"][0]["uploaded"] is True

    # Object vanishes from storage, row still says uploaded.
    storage._MEM.clear()

    r = await client.post("/api/maintenance/reconcile-storage", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert r.json()["route_files_reconciled"] == 1

    # Row now reads not-uploaded; the route itself still exists.
    detail2 = await client.get(f"/api/routes/{route_id}")
    assert detail2.status_code == 200
    assert detail2.json()["files"][0]["uploaded"] is False

    # Idempotent — a second run reconciles nothing.
    r2 = await client.post("/api/maintenance/reconcile-storage", headers={"X-CSRF-Token": csrf})
    assert r2.json()["route_files_reconciled"] == 0


async def test_reconcile_storage_requires_auth(client):
    # Unauthenticated (no session) is rejected before the admin check — the endpoint is not open.
    assert (await client.post("/api/maintenance/reconcile-storage")).status_code == 401


async def test_missing_log_object_serves_404_not_500(client):
    from app import storage

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    start = await device_post(
        client, device_id, keys, "/api/ingest/logs/start",
        {"name": "boot.log", "kind": "system"},
    )
    log_id = start.json()["id"]
    await device_put(client, device_id, keys, f"/api/ingest/logs/{log_id}/content", b"LOGDATA")
    storage._MEM.clear()
    assert (await client.get(f"/api/logs/{log_id}/download")).status_code == 404


async def test_uploaded_object_key_layout(client):
    """An uploaded route file lands under the expected `routes/{device}/{route}/...` object key."""
    from app import storage

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    route_id = await _ingest_route(client, device_id, keys, payload=b"BYTES" * 4)

    keys_stored = [k for k in storage._MEM if route_id in k]
    assert keys_stored, "expected a stored object for the route"
    assert all(k.startswith("routes/") for k in keys_stored), keys_stored


async def test_delete_route_removes_exact_stored_keys(client):
    """delete_route must delete each file's EXACT stored key (so it works regardless of key scheme),
    not a recomputed prefix. Upload multiple segments, then assert all their objects are gone."""
    from app import storage

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    start = await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": "2026-06-26--07-00-00", "segment_count": 2,
         "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"},
                   {"segment_index": 1, "name": "qlog.zst", "kind": "qlog"}]},
    )
    route_id = start.json()["route_id"]
    for seg in (0, 1):
        put = await device_put(
            client, device_id, keys, f"/api/ingest/routes/{route_id}/files/{seg}/qlog.zst", b"SEG" + bytes([seg])
        )
        assert put.status_code == 200
    await device_post(client, device_id, keys, f"/api/ingest/routes/{route_id}/complete", {})

    assert len([k for k in storage._MEM if route_id in k]) == 2  # both segments stored
    d = await client.request("DELETE", f"/api/routes/{route_id}", headers={"X-CSRF-Token": csrf})
    assert d.status_code == 200, d.text
    assert [k for k in storage._MEM if route_id in k] == []  # every object removed


async def test_oversized_upload_rejected_before_buffering(client, monkeypatch):
    """An upload whose Content-Length exceeds the cap is rejected 413 in the auth dependency, BEFORE
    the body is buffered into RAM (the OOM guard). Lower the cap so a small body trips it."""
    from app import deps

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    start = await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": "2026-06-27--09-00-00", "segment_count": 1,
         "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]},
    )
    route_id = start.json()["route_id"]

    monkeypatch.setattr(deps.settings, "max_upload_bytes", 16, raising=False)
    big = b"X" * 64  # 64 bytes > the patched 16-byte cap
    put = await device_put(client, device_id, keys, f"/api/ingest/routes/{route_id}/files/0/qlog.zst", big)
    assert put.status_code == 413, put.text


async def test_route_start_is_idempotent(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await _ingest_route(client, device_id, keys)
    # Re-declaring the same route name must not create a duplicate.
    again = await device_post(
        client,
        device_id,
        keys,
        "/api/ingest/routes/start",
        {"name": ROUTE_NAME, "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]},
    )
    assert again.status_code == 201
    assert len((await client.get(f"/api/devices/{device_id}/routes")).json()) == 1


async def test_log_ingest_list_download_delete(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    start = await device_post(
        client,
        device_id,
        keys,
        "/api/ingest/logs/start",
        {"kind": "crash", "name": "crash_2026-06-25.txt", "route_name": ROUTE_NAME},
    )
    assert start.status_code == 201, start.text
    log_id = start.json()["id"]

    content = b"Traceback (most recent call last):\n  RuntimeError: simulated crash\n"
    put = await device_put(
        client, device_id, keys, f"/api/ingest/logs/{log_id}/content", content, content_type="text/plain"
    )
    assert put.status_code == 200, put.text

    lst = await client.get(f"/api/devices/{device_id}/logs")
    assert lst.status_code == 200
    assert len(lst.json()) == 1
    assert lst.json()[0]["upload_status"] == "complete"
    assert lst.json()[0]["kind"] == "crash"

    dl = await client.get(f"/api/logs/{log_id}/download")
    assert dl.status_code == 200
    assert dl.content == content

    d = await client.request("DELETE", f"/api/logs/{log_id}", headers={"X-CSRF-Token": csrf})
    assert d.status_code == 200
    assert (await client.get(f"/api/devices/{device_id}/logs")).json() == []


async def test_ingest_requires_signature(client):
    csrf = await setup_admin(client)
    device_id, _keys = await pair_device(client, csrf)
    # Unsigned start.
    unsigned = await client.post("/api/ingest/routes/start", json={"name": "x", "files": []})
    assert unsigned.status_code == 401
    # Unsigned file PUT.
    put = await client.put(
        "/api/ingest/routes/whatever/files/0/qlog.zst", content=b"data"
    )
    assert put.status_code == 401


async def test_web_routes_require_auth(client):
    csrf = await setup_admin(client)
    device_id, _keys = await pair_device(client, csrf)
    # Drop the session cookie -> unauthenticated.
    client.cookies.clear()
    assert (await client.get(f"/api/devices/{device_id}/routes")).status_code == 401
    assert (await client.get(f"/api/devices/{device_id}/logs")).status_code == 401


async def test_retention_config_and_run(client, app):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await _ingest_route(client, device_id, keys, name="2026-06-01--10-00-00")

    # Disabled by default -> running errors.
    assert (await _get(client)).json()["days"] == 0
    run0 = await client.post("/api/retention/run", headers={"X-CSRF-Token": csrf})
    assert run0.status_code == 400

    # Configure a 7-day window.
    put = await client.put("/api/retention", json={"days": 7}, headers={"X-CSRF-Token": csrf})
    assert put.status_code == 200 and put.json()["days"] == 7

    # Backdate the route past the cutoff so retention reaps it.
    from app.db import SessionLocal
    from app.models import Route
    from sqlalchemy import update

    async with SessionLocal() as session:
        await session.execute(
            update(Route)
            .where(Route.device_id == device_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=30))
        )
        await session.commit()

    run = await client.post("/api/retention/run", headers={"X-CSRF-Token": csrf})
    assert run.status_code == 200, run.text
    assert run.json()["routes_deleted"] == 1
    assert (await client.get(f"/api/devices/{device_id}/routes")).json() == []


async def test_retention_per_category(client, app):
    """route_days reaps routes while log_days=0 keeps logs (and vice-versa)."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await _ingest_route(client, device_id, keys, name="2026-06-01--10-00-00")
    # ingest a log too (two-step: start + content)
    log_start = await device_post(
        client, device_id, keys, "/api/ingest/logs/start",
        {"kind": "system", "name": "boot.log"},
    )
    assert log_start.status_code == 201, log_start.text
    log_id = log_start.json()["id"]
    await device_put(
        client, device_id, keys, f"/api/ingest/logs/{log_id}/content", b"boot log line\n",
        content_type="text/plain",
    )

    # routes: 7-day window; logs: keep forever (0)
    put = await client.put(
        "/api/retention",
        json={"route_days": 7, "log_days": 0},
        headers={"X-CSRF-Token": csrf},
    )
    assert put.status_code == 200, put.text
    assert put.json()["route_days"] == 7 and put.json()["log_days"] == 0

    # backdate both route + log well past the cutoff
    from app.db import SessionLocal
    from app.models import Log, Route
    from sqlalchemy import update

    old = datetime.now(timezone.utc) - timedelta(days=30)
    async with SessionLocal() as session:
        await session.execute(update(Route).where(Route.device_id == device_id).values(created_at=old))
        await session.execute(update(Log).where(Log.device_id == device_id).values(created_at=old))
        await session.commit()

    run = await client.post("/api/retention/run", headers={"X-CSRF-Token": csrf})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["routes_deleted"] == 1   # route reaped (7-day window)
    assert body["logs_deleted"] == 0     # logs kept (log_days=0)
    assert (await client.get(f"/api/devices/{device_id}/routes")).json() == []
    assert len((await client.get(f"/api/devices/{device_id}/logs")).json()) == 1


async def test_delete_all_routes(client, app):
    """Bulk delete removes all of the user's routes; scoping to a device is honored."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await _ingest_route(client, device_id, keys, name="2026-06-01--10-00-00")
    await _ingest_route(client, device_id, keys, name="2026-06-02--11-00-00")
    assert len((await client.get(f"/api/devices/{device_id}/routes")).json()) == 2

    res = await client.request(
        "DELETE", "/api/routes", headers={"X-CSRF-Token": csrf}
    )
    assert res.status_code == 200, res.text
    assert res.json()["routes_deleted"] == 2
    assert (await client.get(f"/api/devices/{device_id}/routes")).json() == []


async def _get(client):
    return await client.get("/api/retention")
