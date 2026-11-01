#!/usr/bin/env bash
# ─── Clean-Checkout Check ─────────────────────────────────────────────────
# Proves a fresh clone of this repo actually runs: every launcher command
# executes without crashing, the adoption skill resolves, the documented
# install works on a machine with no ~/.claude, and the documented adoption
# path (registering a repo in shared/repo-profiles.json, then sync-hooks)
# actually produces enforcement that blocks a real secret.
#
# Runs against a pristine copy in a temp dir, HOME redirected.
#
# Usage:
#   bash scripts/qa/check-fork-usable.sh            # copy the working tree
#   bash scripts/qa/check-fork-usable.sh --clone    # clone origin/main instead
#
# Exit codes: 0 = a clean clone works, 1 = it's broken.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE="worktree"
while [ $# -gt 0 ]; do
  case "$1" in
    --clone) MODE="clone"; shift ;;
    # full-qa-pass.sh passes --target to every checker. This one always tests the
    # repo it ships in -- it asserts THIS repo works from a clean clone -- so the
    # value is accepted and ignored deliberately rather than silently swallowed.
    --target) shift 2 || shift ;;
    *) echo "check-fork-usable.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done

SANDBOX="$(mktemp -d)"
FAKE_HOME="$SANDBOX/home"
CHECKOUT="$SANDBOX/OliverCode"
mkdir -p "$FAKE_HOME"
trap 'rm -rf "$SANDBOX"' EXIT

echo "=== Clean-checkout check (mode: $MODE) ==="
echo "sandbox: $SANDBOX"
echo ""

if [ "$MODE" = "clone" ]; then
  git clone -q "$REPO_ROOT" "$CHECKOUT" || { echo "FAIL: clone failed"; exit 1; }
else
  # Copy only what git tracks, so the sandbox matches a real clone.
  mkdir -p "$CHECKOUT"
  (cd "$REPO_ROOT" && git ls-files -z | while IFS= read -r -d '' f; do
    mkdir -p "$CHECKOUT/$(dirname "$f")"
    cp -R "$REPO_ROOT/$f" "$CHECKOUT/$f"   # -R: .claude/skills/* is a symlink to a directory
  done)
  # git ls-files does not preserve the executable bit on copy.
  chmod +x "$CHECKOUT/scripts/olivercode" "$CHECKOUT"/scripts/*.sh \
           "$CHECKOUT"/scripts/qa/*.sh "$CHECKOUT"/.githooks/* 2>/dev/null
  # Commit, so the sandbox matches a real clone: files tracked AND the index clean.
  # Leaving everything merely staged is a state no fresh clone is ever in -- it makes
  # the pre-commit hook evaluate every file, and Gate 5 then blocks on the staged
  # workflow YAML because a sandbox HOME has no gh credential. That is a harness
  # artifact, not a clean-clone problem.
  # The identity deliberately contains no "@": an email literal here would trip Gate 3.
  git -C "$CHECKOUT" init -q .
  git -C "$CHECKOUT" add -A >/dev/null 2>&1
  git -C "$CHECKOUT" -c user.email=forkcheck -c user.name=forkcheck \
      commit -q -m "clean-clone baseline" --no-verify >/dev/null 2>&1
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

echo "--- A fresh checkout's commands must run without crashing ---"
step "scripts/olivercode --help"     python3 scripts/olivercode --help
step "scripts/olivercode health"     python3 scripts/olivercode health
step "scripts/olivercode skills"     python3 scripts/olivercode skills
step "bash scripts/validate.sh"      bash scripts/validate.sh
step "bash scripts/link-check.sh"    bash scripts/link-check.sh
step "bash scripts/qa/check-bloat.sh --strict" bash scripts/qa/check-bloat.sh --strict

echo ""
echo "--- The adoption skill must be usable on a fresh clone, before any setup ---"
# README's central promise: open the clone in Claude Code, say "set up OliverCode", and
# the olivercode-adoption skill drives it. That requires the skill to be PROJECT-level
# (.claude/skills/), because a user-level skill would need the setup it is meant to run.
#
# This assertion exists because the copy loop above used plain `cp`, which cannot copy
# the tracked symlink-to-directory and failed silently. The sandbox therefore never
# contained the skill, and the check that exists to prove this property was not testing
# it -- the same "reports success it has not earned" shape this repo keeps finding.
ADOPT_SKILL="$CHECKOUT/.claude/skills/olivercode-adoption/SKILL.md"
if [ -f "$ADOPT_SKILL" ] && grep -q "^name: olivercode-adoption" "$ADOPT_SKILL"; then
  echo "  [OK]   .claude/skills/olivercode-adoption resolves in a fresh clone"
else
  echo "  [FAIL] the adoption skill is not usable from a fresh clone"
  echo "         expected a readable SKILL.md at .claude/skills/olivercode-adoption/"
  FAILED=1
fi

echo ""
echo "--- The documented install must work on a machine with no ~/.claude ---"
if (cd "$CHECKOUT" && HOME="$FAKE_HOME" bash -c '
      mkdir -p ~/.claude/skills
      ln -sfn "$(pwd)/CLAUDE.md" ~/.claude/CLAUDE.md
      ln -sfn "$(pwd)/docs/VOICE.md" ~/.claude/VOICE.md
      for s in skills/*/; do ln -sfn "$(pwd)/$s" ~/.claude/skills/"$(basename "$s")"; done
      OC="$(dirname "$(readlink ~/.claude/CLAUDE.md)")"
      test -f "$OC/docs/RULES.md" && test -f ~/.claude/VOICE.md' >/dev/null 2>&1); then
  echo "  [OK]   README install works and \$OC resolves from a virgin HOME"
else
  echo "  [FAIL] README install path is broken on a fresh machine"
  FAILED=1
fi

echo ""
echo "--- The documented adoption path must actually govern a fleet ---"
# Walks the load-bearing claims of docs/SETUP.md against two throwaway repos.
# The guide is the primary onboarding artifact; an untested guide rots exactly the
# way the --root instruction did (it told forkers to pass a flag that was ignored).
WS="$SANDBOX/ws"
mkdir -p "$WS"
cp -R "$CHECKOUT" "$WS/OliverCode"
for r in probe-web probe-api; do
  mkdir -p "$WS/$r/scripts"
  ( cd "$WS/$r" && git init -q . \
    && printf '#!/usr/bin/env bash\necho "%s ok"\n' "$r" > scripts/validate.sh \
    && chmod +x scripts/validate.sh \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=forkcheck -c user.name=forkcheck commit -qm init --no-verify >/dev/null 2>&1 )
done

adopt() { (cd "$WS/OliverCode" && HOME="$FAKE_HOME" "$@" 2>&1); }

HOME="$FAKE_HOME" python3 - "$WS/OliverCode/shared/repo-profiles.json" <<'PY' >/dev/null 2>&1
import json, sys
p = sys.argv[1]
d = json.load(open(p))
# The tracked registry ships empty with one example entry; a fork that filled it has profiles.
tmpl = next(iter(d["profiles"].values()), None) or d["_exampleProfile"]
d["profiles"] = {}
for name in ("probe-web", "probe-api"):
    entry = json.loads(json.dumps(tmpl))
    entry["name"] = name
    d["profiles"][name] = entry
json.dump(d, open(p, "w"), indent=2)
PY

if adopt python3 scripts/olivercode sync-hooks | grep -q "probe-web"; then
  echo "  [OK]   sync-hooks installs hooks into a registered fleet"
else
  echo "  [FAIL] sync-hooks did not reach the registered fleet"
  FAILED=1
fi

# The claim the whole framework rests on: enforcement actually blocks.
PROBE_BLOCKED=0
( cd "$WS/probe-web" \
  && printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt \
  && git add leak-probe.txt \
  && HOME="$FAKE_HOME" git -c user.email=forkcheck -c user.name=forkcheck \
       commit -m probe >/dev/null 2>&1 ) || PROBE_BLOCKED=1
if [ "$PROBE_BLOCKED" -eq 1 ]; then
  echo "  [OK]   a staged secret is blocked in an adopted repo"
else
  echo "  [FAIL] a staged secret COMMITTED in an adopted repo -- enforcement is absent"
  FAILED=1
fi

if adopt python3 scripts/olivercode health | grep -q "probe-web: hooksPath set"; then
  echo "  [OK]   health confirms the adopted fleet's hooks"
else
  echo "  [FAIL] health does not see the adopted fleet"
  FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "PASS: a fresh clone of this repo works, and the documented adoption path"
  echo "      produces a fleet whose gates actually block."
  exit 0
fi
echo "FAIL: a fresh clone of this repo would NOT work as documented."
exit 1
