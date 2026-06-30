"""Persistent device identity: Ed25519 keypair + hardware id + (post-pairing) device id.

The private key is generated locally and never leaves the device. Stored with 0600 perms.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass

from mypilot_protocol.crypto import KeyPair, generate_keypair


@dataclass
class Identity:
    private_key_b64: str
    public_key_b64: str
    hardware_id: str
    hostname: str
    device_id: str | None = None

    @property
    def keypair(self) -> KeyPair:
        return KeyPair(private_key_b64=self.private_key_b64, public_key_b64=self.public_key_b64)

    @property
    def is_paired(self) -> bool:
        return bool(self.device_id)


def _path(data_dir: str) -> str:
    return os.path.join(data_dir, "identity.json")


def load_or_create(data_dir: str, hardware_id: str | None = None) -> Identity:
    os.makedirs(data_dir, exist_ok=True)
    path = _path(data_dir)
    if os.path.exists(path):
        with open(path) as fh:
            data = json.load(fh)
        return Identity(**data)

    keys = generate_keypair()
    identity = Identity(
        private_key_b64=keys.private_key_b64,
        public_key_b64=keys.public_key_b64,
        hardware_id=hardware_id or uuid.uuid4().hex,
        hostname=socket.gethostname(),
    )
    save(data_dir, identity)
    return identity


def save(data_dir: str, identity: Identity) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = _path(data_dir)
    with open(path, "w") as fh:
        json.dump(identity.__dict__, fh, indent=2)
    os.chmod(path, 0o600)


def reset(data_dir: str) -> None:
    path = _path(data_dir)
    if os.path.exists(path):
        os.remove(path)
