# mypilot-mici — device build recipe (comma 4)

This directory turns the monorepo into the branches a comma 4 (codename **mici**) actually installs.
It is the **single source of truth** for the device build: the overlay is assembled fresh from
`../mypilot-agent` + `../mypilot-protocol` every run, so the agent never lives in two places.

## The model

```
this monorepo ──assemble──> castanley/openpilot @ <out branch> ──installer.comma.ai──> comma 4
```

The delivery repo **must** be named `openpilot` (the comma installer clones
`github.com/<owner>/openpilot@<branch>`). It is auto-generated — never hand-edited. See the
repo-root `README.md` for the two-repo overview.

## Files

| File | Role |
|---|---|
| `recipe.json` | the matrix: each base (sunnypilot/openpilot/frogpilot) × its channels (release/staging) |
| `assemble.py` | vendors agent + protocol + shim + the base's `install_process` into the overlay dir |
| `bases/sunnypilot/install_process.py` | registers `mypilotd` + the pairing alert for the sunnypilot layout (`sunnypilot/mypilot/`) |
| `bases/root/install_process.py` | same, for bases that overlay at the repo root (`mypilot/`) — openpilot & frogpilot |
| `overlay/mypilotd.py`, `overlay/__init__.py` | the entrypoint shim + package marker placed in every overlay |
| `publish.sh` | CI entry: loops the recipe, assembles each channel, force-pushes changed branches |

## Channels

| Base | Upstream | Branches | Installs as | Status |
|---|---|---|---|---|
| sunnypilot | `sunnypilot/sunnypilot` | `release-mici` / `-staging` | `castanley/mypilot-mici` / `-staging` | **validated** |
| openpilot | `commaai/openpilot` | `release-mici` / `-staging` | `castanley/mypilot-mici-op` / `-op-staging` | experimental |
| frogpilot | `FrogAi/FrogPilot` | `FrogPilot` / `-Staging` | `castanley/mypilot-mici-frog` / `-frog-staging` | experimental · publish blocked\* |

> **Experimental** = generated and structurally valid, but not yet validated on a physical comma 4
> (overlay path, process registration, and on-screen pairing rendering can differ per base). The
> sunnypilot channel is the validated default; openpilot publishes successfully and awaits device
> validation.
>
> **\*frogpilot publish is currently blocked.** FrogPilot's git history diverges from
> `castanley/openpilot` (no shared objects) and it uses Git LFS, so the shallow push is rejected
> (`did not receive expected object`). Enabling it needs a full fetch + LFS mirroring (or an
> orphan-branch push) — and on-device validation regardless. Experimental-base failures are
> non-fatal to the sync, so the validated channel stays green.

## Local use

```bash
# list the channels CI will build
python3 mypilot-mici/assemble.py plan

# assemble just the overlay into a scratch tree (what the byte-identical gate checks)
python3 mypilot-mici/assemble.py overlay --base sunnypilot --target /tmp/scratch

# assemble + run install_process against a real upstream checkout
python3 mypilot-mici/assemble.py build --base sunnypilot --target /path/to/openpilot-checkout
```

Adding a device codename (e.g. tici/tizi) or a new base is just another row in `recipe.json`.
