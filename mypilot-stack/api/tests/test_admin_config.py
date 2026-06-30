"""Deployment/fork config: defaults, admin update, and install URLs derived from it."""

from __future__ import annotations

from .helpers import setup_admin


async def test_config_defaults(client):
    await setup_admin(client)
    r = await client.get("/api/admin/config")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["project_name"] == "MyPilot"
    assert c["installer_base"] == "https://installer.comma.ai"
    # github_owner / branches default empty — the deployer points them at their own fork (the
    # configured path + URL derivation is covered by test_config_update_drives_install_urls).
    assert c["github_owner"] == ""
    assert "release_install_url" in c and "staging_install_url" in c


async def test_public_site_no_auth(client):
    # Public landing config — readable without a session, non-sensitive only.
    r = await client.get("/api/public/site")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_name"] == "MyPilot"
    assert set(body.keys()) == {"project_name", "stack_url", "source_url"}


async def test_config_update_requires_csrf(client):
    await setup_admin(client)
    no_csrf = await client.patch("/api/admin/config", json={"github_owner": "acme"})
    assert no_csrf.status_code == 403


async def test_config_update_drives_install_urls(client):
    csrf = await setup_admin(client)
    upd = await client.patch(
        "/api/admin/config",
        json={"github_owner": "acme", "release_branch": "op-acme", "staging_branch": "op-acme-rc",
              "stack_url": "https://drive.acme.io"},
        headers={"X-CSRF-Token": csrf},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["release_install_url"] == "https://installer.comma.ai/acme/op-acme"

    # The software catalog now reflects the fork's owner/branches — no code change.
    rel = await client.get("/api/software/releases")
    urls = {r["channel"]: r["install_url"] for r in rel.json()}
    assert urls["release"] == "https://installer.comma.ai/acme/op-acme"
    assert urls["staging"] == "https://installer.comma.ai/acme/op-acme-rc"

    # Persisted across reads.
    again = await client.get("/api/admin/config")
    assert again.json()["github_owner"] == "acme"
    assert again.json()["stack_url"] == "https://drive.acme.io"
