#!/usr/bin/env bash
# ─── Fork-Usability Check ─────────────────────────────────────────────────
# Proves a stranger can clone this repo and use it with NO configuration:
# no local/, no runtime/control-plane/, no ~/.claude symlinks, no vault.
#
# This exists because that property kept breaking silently. Every failure it
# now checks was a real regression found by cloning by hand:
#   - validate.sh failed on a clean clone (reference gate flagged gitignored,
#     per-user paths that exist only on the author's machine)
#   - the reference gate only scanned git-TRACKED files, so a new file's
#     dangling ref passed locally and broke after being committed
#   - `ln -s` in the README install died on a machine with no ~/.claude/skills
#
# Runs against a pristine copy in a temp dir. HOME is redirected so nothing
# reads or writes the real one.
#
# Usage:
#   bash scripts/qa/check-fork-usable.sh            # copy the working tree
#   bash scripts/qa/check-fork-usable.sh --clone    # clone origin/main instead
#
# Exit codes: 0 = a fork works, 1 = a fork is broken.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE="worktree"
while [ $# -gt 0 ]; do
  case "$1" in
    --clone) MODE="clone"; shift ;;
    # full-qa-pass.sh passes --target to every checker. This one always tests the
    # repo it ships in -- it asserts THIS repo is forkable -- so the value is
    # accepted and ignored deliberately rather than silently swallowed.
    --target) shift 2 || shift ;;
    *) echo "check-fork-usable.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done

SANDBOX="$(mktemp -d)"
FAKE_HOME="$SANDBOX/home"
CHECKOUT="$SANDBOX/OliverCode"
mkdir -p "$FAKE_HOME"
trap 'rm -rf "$SANDBOX"' EXIT

echo "=== Fork-usability check (mode: $MODE) ==="
echo "sandbox: $SANDBOX"
echo ""

if [ "$MODE" = "clone" ]; then
  git clone -q "$REPO_ROOT" "$CHECKOUT" || { echo "FAIL: clone failed"; exit 1; }
else
  # Copy only what git tracks -- an untracked local/ or runtime/ would defeat
  # the entire point of the check.
  mkdir -p "$CHECKOUT"
  (cd "$REPO_ROOT" && git ls-files -z | while IFS= read -r -d '' f; do
    mkdir -p "$CHECKOUT/$(dirname "$f")"
    cp "$REPO_ROOT/$f" "$CHECKOUT/$f"
  done)
  # git ls-files does not preserve the executable bit on copy.
  chmod +x "$CHECKOUT/scripts/olivercode" "$CHECKOUT"/scripts/*.sh \
           "$CHECKOUT"/scripts/qa/*.sh "$CHECKOUT"/.githooks/* 2>/dev/null
  # Commit, so the sandbox matches a real clone: files tracked AND the index clean.
  # Leaving everything merely staged is a state no fresh clone is ever in -- it makes
  # the pre-commit hook evaluate every file, and Gate 5 then blocks on the staged
  # workflow YAML because a sandbox HOME has no gh credential. That is a harness
  # artifact, not a fork problem.
  # The identity deliberately contains no "@": an email literal here would trip Gate 3.
  git -C "$CHECKOUT" init -q .
  git -C "$CHECKOUT" add -A >/dev/null 2>&1
  git -C "$CHECKOUT" -c user.email=forkcheck -c user.name=forkcheck \
      commit -q -m "fork-usability baseline" --no-verify >/dev/null 2>&1
fi

FAILED=0
step() {
  local label="$1"; shift
  local out
  if out=$(cd "$CHECKOUT" && HOME="$FAKE_HOME" "$@" 2>&1); then
    echo "  [OK]   $label"
  else
    echo "  [FAIL] $label"
    echo "$out" | sed 's/^/           /' | tail -15
    FAILED=1
  fi
}

echo "--- A fresh checkout must work with zero configuration ---"
step "scripts/olivercode --help"     python3 scripts/olivercode --help
step "scripts/olivercode health"     python3 scripts/olivercode health
step "scripts/olivercode skills"     python3 scripts/olivercode skills
step "scripts/olivercode init"       python3 scripts/olivercode init
step "bash scripts/validate.sh"      bash scripts/validate.sh
step "bash scripts/link-check.sh"    bash scripts/link-check.sh
step "bash scripts/qa/check-bloat.sh --strict" bash scripts/qa/check-bloat.sh --strict

echo ""
echo "--- No personal data may be present in a fresh checkout ---"
for leaked in local runtime/control-plane .claude-optimization/memory .claude-optimization/state; do
  if [ -e "$CHECKOUT/$leaked" ] && [ "$leaked" != "local" ]; then
    echo "  [FAIL] $leaked is present in a tracked checkout"
    FAILED=1
  fi
done
# `init` legitimately creates local/, so check its CONTENT is placeholder-only.
if grep -rqI "$(basename "$HOME")" "$CHECKOUT/local" 2>/dev/null; then
  echo "  [FAIL] local/ seeded from examples contains the real username"
  FAILED=1
else
  echo "  [OK]   no personal identifiers in the seeded local/"
fi

echo ""
echo "--- The documented install must work on a machine with no ~/.claude ---"
if (cd "$CHECKOUT" && HOME="$FAKE_HOME" bash -c '
      mkdir -p ~/.claude/skills
      ln -sfn "$(pwd)/CLAUDE.md" ~/.claude/CLAUDE.md
      for s in skills/*/; do ln -sfn "$(pwd)/$s" ~/.claude/skills/"$(basename "$s")"; done
      OC="$(dirname "$(readlink ~/.claude/CLAUDE.md)")"
      test -f "$OC/core/contracts/FRAMEWORK_BASELINE.md"' >/dev/null 2>&1); then
  echo "  [OK]   README install works and \$OC resolves from a virgin HOME"
else
  echo "  [FAIL] README install path is broken on a fresh machine"
  FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "PASS: a fork of this repo works with no configuration."
  exit 0
fi
echo "FAIL: a fork of this repo would NOT work as documented."
exit 1
