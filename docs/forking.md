# Forking MyPilot (use your own URLs — nothing is hard-coded)

MyPilot is meant to be forked and self-hosted. Two layers carry deployment identity, and **neither
requires code edits**:

## 1. The control plane (Stack URL + install source) — in **Settings**

Sign in as admin → **Settings** (system). Set:

- **Public Stack URL** — the URL your devices pair to and that you use to reach your Stack (e.g.
  `https://drive.yourdomain.com`).
- **Build / install source** — your **GitHub owner** + **release/staging branches** + installer
  base. The panel **derives every install URL from these** (shown live as you type), e.g.
  `installer.comma.ai/<owner>/<release-branch>` and the device shorthand `<owner>/<release-branch>`.

These are stored server-side (`SystemConfig`), so the Software page, the device commands, and the
displayed URLs all update instantly when you change them — no rebuild, no code.

API: `GET /api/admin/config`, `PUT /api/admin/config` (admin + CSRF, audited).

## 2. The device build (default Stack URL) — one file: `fork.json`

The on-device agent needs to know where your Stack is *before* it can pair, so that default is
baked into the build. It lives in **one file** in your monorepo (the recipe vendors it into every
device branch):

```
mypilot-agent/mypilot_agent/fork.json   →  { "stack_url": "https://drive.yourdomain.com" }
```

Precedence on-device: `MYPILOT_STACK_URL` env > `/data/mypilot/config.json` (runtime) > `fork.json`
(build default) > the built-in fallback. So a fork edits that one JSON value and its builds pair to
its Stack.

## 3. The repos + branches (two repos, one source of truth)

MyPilot uses **two repos** (see the repo-root README for the full picture):

- **Your monorepo** — `github.com/<you>/mypilot`, where you work. Set your Stack URL in
  `mypilot-agent/mypilot_agent/fork.json` and your channels in
  [`mypilot-mici/recipe.json`](../mypilot-mici/recipe.json).
- **Your delivery repo** — `github.com/<you>/openpilot`, which **must** be named `openpilot` for
  the comma installer. Its `mypilot-*` branches are **generated** from the monorepo by
  [`mypilot-mici/assemble.py`](../mypilot-mici/assemble.py); never hand-edit them.

The **`sync-mypilot`** GitHub Action lives on the **delivery** repo's default branch. Each run
clones your (public) monorepo and runs `mypilot-mici/publish.sh`, which rebuilds every channel =
`<upstream base>` + the freshly assembled overlay and force-pushes only what changed. Point
**Settings → Build/install source** at your owner + branches.

## Checklist for a new fork

1. Fork/clone this monorepo → `github.com/<you>/mypilot` (keep it **public** so the delivery repo's
   Action can read it without a token).
2. Create the delivery repo `github.com/<you>/openpilot` (named exactly `openpilot`).
3. Edit `mypilot-agent/mypilot_agent/fork.json` → your Stack URL; set your owner/branches in
   `mypilot-mici/recipe.json`; push the monorepo.
4. Add `sync-mypilot.yml` to the **delivery** repo's default branch (it clones your monorepo and
   runs `mypilot-mici/publish.sh`); enable Actions and run it once.
5. Deploy the Stack (`./scripts/install.sh`), create the first admin, and in **Settings** set the
   Stack URL + your GitHub owner/branches.
6. Flash `<you>/mypilot-mici` on the device; pair from the on-screen code. Done.
