"""HTTP client for the pairing handshake against the MyPilot Stack.

Uses aiohttp so the agent runs identically on the dev container and on the comma device (AGNOS
ships aiohttp + pycryptodome; the shared protocol's crypto falls back to pycryptodome there).
"""

from __future__ import annotations

import aiohttp
from mypilot_protocol.crypto import sign
from mypilot_protocol.messages import pairing_challenge

from .config import AgentConfig
from .identity import Identity


class StackClient:
    def __init__(self, config: AgentConfig) -> None:
        self.cfg = config
        self.http = aiohttp.ClientSession()

    async def close(self) -> None:
        await self.http.close()

    async def register_start(self, identity: Identity) -> dict:
        async with self.http.post(
            f"{self.cfg.api_base}/api/devices/register/start",
            json={
                "public_key": identity.public_key_b64,
                "hardware_id": identity.hardware_id,
                "hostname": identity.hostname,
            },
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def register_complete(self, pairing_id: str, identity: Identity) -> dict:
        signature = sign(identity.private_key_b64, pairing_challenge(pairing_id))
        async with self.http.post(
            f"{self.cfg.api_base}/api/devices/register/complete",
            json={"pairing_id": pairing_id, "signature": signature},
        ) as resp:
            if resp.status == 410:
                return {"status": "expired"}
            resp.raise_for_status()
            return await resp.json()
