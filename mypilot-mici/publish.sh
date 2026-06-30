#!/usr/bin/env bash
# Rebuild every MyPilot device channel = <upstream base> + the MyPilot overlay, and force-push the
# changed branches to the delivery repo (castanley/openpilot). Run from a checkout of that repo,
# with this monorepo cloned somewhere ($MYPILOT_MONOREPO). Pure git + python3 — no extra deps.
#
# Per-channel failures are isolated and logged (an experimental base can't block the validated one);
# the script still exits non-zero if anything failed so CI surfaces it.
set -uo pipefail

MONO="${MYPILOT_MONOREPO:?set MYPILOT_MONOREPO to the cloned monorepo path}"
ASSEMBLE="$MONO/mypilot-mici/assemble.py"

git config user.name "mypilot-sync[bot]"
git config user.email "mypilot-sync@users.noreply.github.com"

mapfile -t CHANNELS < <(python3 "$ASSEMBLE" plan)
overall=0

for line in "${CHANNELS[@]}"; do
  # shellcheck disable=SC2086
  set -- $line
  base=$1; upstream=$2; branch=$3; out=$4; status=$6
  # Optional filter: MYPILOT_ONLY_BASE=sunnypilot re-publishes just one base.
  if [ -n "${MYPILOT_ONLY_BASE:-}" ] && [ "${MYPILOT_ONLY_BASE}" != "$base" ]; then
    continue
  fi
  echo "::group::$out  ($base/$branch · $status)"
  ok=1
  remote="up_${base}"

  git remote get-url "$remote" >/dev/null 2>&1 || git remote add "$remote" "$upstream"
  git fetch --depth 1 "$remote" "$branch" || ok=0
  # Start each channel from a pristine tree (a prior channel's failure can't bleed over).
  git reset --hard -q 2>/dev/null || true
  git clean -fdq 2>/dev/null || true
  [ $ok -eq 1 ] && { git checkout -B sync-tmp "$remote/$branch" || ok=0; }
  [ $ok -eq 1 ] && { python3 "$ASSEMBLE" build --base "$base" --target "$PWD" || ok=0; }
  # CI gate: a channel that re-enabled sunnylink phone-home, lost the agent registration, or kept
  # dead sunnylink UI must NEVER be published. Fail the channel loudly instead.
  [ $ok -eq 1 ] && { python3 "$MONO/mypilot-mici/verify_assembled.py" --target "$PWD" || ok=0; }

  if [ $ok -eq 1 ]; then
    git add -A
    short="$(git rev-parse --short "$remote/$branch")"
    if git commit -q -m "sync: $out = $base/$branch@$short + MyPilot agent"; then
      if git rev-parse --verify "origin/$out" >/dev/null 2>&1 && git diff --quiet sync-tmp "origin/$out"; then
        echo "no change for $out; skipping push"
      elif [ -n "${DRY_RUN:-}" ]; then
        echo "[dry-run] would push $out ($(git diff --shortstat "origin/$out" sync-tmp 2>/dev/null || echo 'new branch'))"
      else
        git push --force origin "sync-tmp:$out" && echo "pushed $out" || ok=0
      fi
    else
      echo "nothing to commit for $out"
    fi
  fi

  # A validated base failing fails the run; experimental bases are best-effort (warn only).
  if [ $ok -ne 1 ]; then
    echo "::warning::$out failed ($status)"
    [ "$status" = "validated" ] && overall=1
  fi
  echo "::endgroup::"
done

exit $overall
