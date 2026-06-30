# Device Registration & Pairing

MyPilot pairs a device to your account using locally generated keys and a short-lived,
one-time pairing code. No shared secret is trusted forever; after pairing, the device signs
every request with its private key.

## The handshake

```
Device (MyPilot Agent)                 MyPilot Stack                 You (MyPilot Web)
──────────────────────                 ─────────────                 ─────────────────
1. generate Ed25519 keypair
   (private key stays on device)
2. POST /api/devices/register/start ──> create pending pairing,
   {hardware_id, public_key}            store code in Redis (TTL 10m)
   <───────────────────────────────── {pairing_id, code, expires_at}
3. display CODE on device
   (QR with Stack URL later)
                                                                  4. enter CODE in
                                                                     Devices → Add device
                                        <──── POST /api/devices/claim {code, alias?}
                                        validate one-time/unexpired,
                                        bind public key to your account,
                                        create device (pending_activation),
                                        consume code, write audit
5. POST /api/devices/register/complete ─> while pending: {status: pending}
   {pairing_id, signature}               once claimed: verify signature
   (Ed25519 over challenge)              against stored public key →
   <───────────────────────────────── {device_id, status: active, config}
6. store identity; from now on,
   sign every request
```

## Properties

- **Short-lived:** pairing codes expire (default 10 minutes).
- **One-time:** a code is consumed on first successful claim.
- **Rate-limited:** `register/start`, `claim`, and `register/complete` are throttled.
- **Proof of possession:** activation requires a valid Ed25519 signature, so a stolen code
  alone cannot impersonate the device.
- **Revocable:** unpairing/deleting a device revokes its key; later signed requests fail.

## Post-pairing request signing

Every authenticated device request carries:

| Header | Value |
| --- | --- |
| `X-MyPilot-Device` | device id |
| `X-MyPilot-Timestamp` | unix seconds (server enforces ±60s) |
| `X-MyPilot-Signature` | base64 Ed25519 signature over `method\npath\ntimestamp\nsha256(body)` |

The same signing/verifying helpers are shared by the agent and the API via
`mypilot-protocol`.

## Simulated device

A **simulated device** performs this exact handshake so the full flow is testable without hardware
— and the real comma-4 agent uses the identical flow:

```bash
./scripts/dev-sim-device.sh
```

It prints the pairing code to enter in the web UI, then maintains a WebSocket, sends heartbeats
and simulated status, and handles the (offroad-only) reboot command.
