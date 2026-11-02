#!/usr/bin/env bash
# ─── Secret-Gate Probe ─────────────────────────────────────────────────────
# Proves Gate 1 (secrets) actually blocks a commit, rather than assuming it
# does because sync-hooks reported "done" -- that only confirms the hook
# files were written, not that git is running them. Extracted 2026-09-09
# from the identical inline snippet duplicated in README.md, docs/SETUP.md,
# and skills/olivercode-adoption/SKILL.md so the three walkthroughs invoke one script instead of three copies of
# the same shell that could silently drift apart.
#
# Writes the probe file straight into the current repo, not staged through
# /tmp: the gate scans what is staged, so a copy step would prove nothing.
#
# Usage: bash scripts/qa/probe-secret-gate.sh   (run from inside the repo to probe)

set -u

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[probe] not inside a git repository -- cd into the repo to probe first" >&2
  exit 2
fi

printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt
git add leak-probe.txt
COMMIT_OUT="$(git commit -m probe -- leak-probe.txt 2>&1)"
COMMIT_EXIT=$?

# A blocked commit counts as proof only when Gate 1 says so. A commit that failed for any other
# reason (no identity, a broken hook, another gate) proves nothing about the secret gate.
if [ "$COMMIT_EXIT" -ne 0 ] && printf '%s\n' "$COMMIT_OUT" | grep -q 'Gate 1/[0-9]*: Secret scan' \
   && printf '%s\n' "$COMMIT_OUT" | grep -q 'matches secret pattern'; then
  git rm -q --cached leak-probe.txt >/dev/null 2>&1 || git reset -q HEAD leak-probe.txt >/dev/null 2>&1 || true
  rm -f leak-probe.txt
  echo "[probe] PASS -- the commit was blocked, Gate 1 is live"
  exit 0
elif [ "$COMMIT_EXIT" -ne 0 ]; then
  git rm -q --cached leak-probe.txt >/dev/null 2>&1 || git reset -q HEAD leak-probe.txt >/dev/null 2>&1 || true
  rm -f leak-probe.txt
  echo "[probe] INCONCLUSIVE -- the commit failed, but not at Gate 1. Git said:" >&2
  printf '%s\n' "$COMMIT_OUT" | tail -8 >&2
  exit 1
else
  echo "[probe] FAIL -- the commit with a fake secret SUCCEEDED. Hooks are not installed." >&2
  echo "[probe] Check: git config --get core.hooksPath   (expect .githooks)" >&2
  echo "[probe] Fix:   scripts/olivercode sync-hooks" >&2
  echo "[probe] A real commit now exists in this repo's history (leak-probe.txt) -- reset it by hand." >&2
  exit 1
fi
