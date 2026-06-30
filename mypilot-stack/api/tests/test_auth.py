"""Auth: first-admin setup, login, logout, /me, and CSRF enforcement."""

from __future__ import annotations

from .helpers import ADMIN_PASS, ADMIN_USER, setup_admin


async def test_setup_state_then_setup(client):
    state = await client.get("/api/auth/setup-state")
    assert state.status_code == 200
    assert state.json()["needs_setup"] is True

    csrf = await setup_admin(client)
    assert csrf

    # Setup is one-time.
    again = await client.post(
        "/api/auth/setup", json={"username": "other", "password": "anotherpass1"}
    )
    assert again.status_code == 409

    state2 = await client.get("/api/auth/setup-state")
    assert state2.json()["needs_setup"] is False


async def test_login_logout_me(client):
    await setup_admin(client)
    # Logout to clear the setup session cookie, then exercise login.
    await client.post("/api/auth/logout")

    bad = await client.post(
        "/api/auth/login", json={"username": ADMIN_USER, "password": "wrong"}
    )
    assert bad.status_code == 401

    ok = await client.post(
        "/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert ok.status_code == 200
    csrf = ok.json()["csrf_token"]

    me = await client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == ADMIN_USER
    assert me.json()["csrf_token"] == csrf

    out = await client.post("/api/auth/logout")
    assert out.status_code == 200
    me2 = await client.get("/api/me")
    assert me2.status_code == 401


async def test_change_password(client):
    csrf = await setup_admin(client)
    NEW = "newstrongpass1"

    # Wrong current password is rejected.
    wrong = await client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": NEW},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong.status_code == 401

    # Correct current password succeeds.
    ok = await client.post(
        "/api/auth/change-password",
        json={"current_password": ADMIN_PASS, "new_password": NEW},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200, ok.text

    # Old password no longer logs in; new one does.
    await client.post("/api/auth/logout")
    assert (
        await client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    ).status_code == 401
    assert (
        await client.post("/api/auth/login", json={"username": ADMIN_USER, "password": NEW})
    ).status_code == 200


async def test_change_password_requires_csrf(client):
    await setup_admin(client)
    no_csrf = await client.post(
        "/api/auth/change-password",
        json={"current_password": ADMIN_PASS, "new_password": "whateverpass1"},
    )
    assert no_csrf.status_code == 403


async def test_csrf_required_on_mutation(client):
    csrf = await setup_admin(client)
    # A state-changing request without the CSRF header is rejected...
    no_csrf = await client.post("/api/devices/claim", json={"code": "WHATEVER"})
    assert no_csrf.status_code == 403
    # ...with the header present, it passes CSRF (and fails later on the bad code).
    with_csrf = await client.post(
        "/api/devices/claim", json={"code": "WHATEVER"}, headers={"X-CSRF-Token": csrf}
    )
    assert with_csrf.status_code == 400
