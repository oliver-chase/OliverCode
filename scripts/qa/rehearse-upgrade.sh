#!/usr/bin/env bash
# ─── Upgrade Rehearsal ────────────────────────────────────────────────────
# Rehearses the update a main user runs: installs OliverCode from origin/main in a sandbox HOME, moves that
# install's origin to REF (staging's head), then runs `olivercode update`, `health` and `sync-hooks` there. Every
# hook command in the sandbox's settings.json must still name a file that exists, and every launchd job the
# install scheduled must name a command the launcher still has. Nothing outside the sandbox is touched.
#
# Usage: bash scripts/qa/rehearse-upgrade.sh REPO REF   (REPO is a clone with origin/main fetched; REF is a commit that descends from it)
# Exit codes: 0 = the update works, 1 = a step failed (its name and output are printed).
set -u

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE OLIVERCODE_SCAN_TREE
[ $# -eq 2 ] || { echo "Usage: rehearse-upgrade.sh REPO REF" >&2; exit 1; }
REPO="$(cd "$1" && pwd)"; REF="$2"
ROOT="$(mktemp -d)"; H="$ROOT/home"; OC="$ROOT/OliverCode"; UP="$ROOT/up.git"
trap 'rm -rf "$ROOT"' EXIT
mkdir -p "$H"
export PATH="$H/.local/bin:$PATH"  # a new shell in the sandbox finds the install's olivercode first, never the real machine's
case "$H" in "$ROOT"/*) ;; *) echo "ABORT: HOME $H is outside the sandbox"; exit 1 ;; esac

fail() { # $1 = step, $2 = its output
  printf 'Upgrade rehearsal failed at: %s\n%s\n' "$1" "$(printf '%s\n' "$2" | tail -n 40)"; exit 1
}
step() { # $1 = name, rest = command run in the sandbox install with the sandbox HOME
  local name="$1" out; shift
  out="$(cd "$OC" && HOME="$H" "$@" 2>&1)" || fail "$name" "$out"
}
oc() { python3 scripts/olivercode "$@"; }

REAL_ORIGIN="$(git -C "$REPO" remote get-url origin 2>/dev/null)"
git init -q --bare "$UP" || fail "make the sandbox origin" ""
out="$(git -C "$UP" fetch -q "$REPO" refs/remotes/origin/main:refs/heads/main 2>&1)" || fail "put origin/main in the sandbox origin" "$out"
git -C "$UP" symbolic-ref HEAD refs/heads/main
out="$(git clone -q "$UP" "$OC" 2>&1)" || fail "clone main into the sandbox" "$out"
step "install from main" oc install
out="$(git -C "$UP" fetch -q "$REPO" "$REF:refs/heads/main" 2>&1)" || fail "put staging's head in the sandbox origin" "$out"
step "olivercode update" oc update
# update has pulled; the install now has the identity of a real clone, which health reads.
[ -n "$REAL_ORIGIN" ] && git -C "$OC" remote set-url origin "$REAL_ORIGIN"
step "olivercode health" oc health
step "olivercode sync-hooks" oc sync-hooks

out="$(cd "$OC" && HOME="$H" python3 - <<'PY' 2>&1
import json, plistlib, shlex, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from lib import cli
home, bad = Path.home(), []
settings = home / ".claude" / "settings.json"
for event, groups in (json.loads(settings.read_text()).get("hooks", {}) if settings.exists() else {}).items():
    for group in groups:
        for hook in group.get("hooks", []):
            for token in shlex.split(hook.get("command", "")):
                if token.startswith("/") and not Path(token).exists():
                    bad.append(f"{event} hook names {token}, which does not exist")
launcher_commands = {row.split()[1] for row, _ in cli.COMMANDS}
for plist in sorted((home / "Library" / "LaunchAgents").glob("*.plist")):
    args = plistlib.loads(plist.read_bytes()).get("ProgramArguments", [])
    if len(args) > 2 and args[2] not in launcher_commands:
        bad.append(f"{plist.name} runs `olivercode {args[2]}`, which the launcher no longer has")
print("\n".join(bad))
sys.exit(1 if bad else 0)
PY
)" || fail "settings.json hooks and launchd jobs" "$out"
echo "Upgrade rehearsal passed: update, health and sync-hooks exit 0, every hook file exists and every scheduled job's command is still there."
