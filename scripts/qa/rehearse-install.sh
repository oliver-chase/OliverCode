#!/usr/bin/env bash
# ─── Install Rehearsal ────────────────────────────────────────────────────
# Runs every documented setup case against a copy of this repo, each in a sandbox with its
# own HOME, and runs the real `olivercode install`, `sync-hooks`, `health`, `update` and
# `uninstall` there. It never touches the real ~/.claude: every command runs with HOME set to
# a folder under the sandbox, and the script stops if that folder is anywhere else.
#
# Cases: a fresh clone's commands, the adoption skill, a virgin machine, an existing
# ~/.claude, a scattered fleet, --root layouts, discover, bootstrap, hookVariant, the full
# backout, idempotency, update, the no-commit probe and zero-config basics. Every claim is a
# sentence in README.md or docs/SETUP.md, so a failure means the code or that sentence is wrong.
#
# Usage:
#   bash scripts/qa/rehearse-install.sh            # copy the working tree's tracked files
#   bash scripts/qa/rehearse-install.sh --clone    # clone this repo's HEAD instead
#
# The secret probe is scripts/qa/probe-secret-gate.sh, which counts a block as proof only when the
# commit output carries the Gate 1 line, so a commit that failed for any other reason never reads as one.
# Exit codes: 0 = every case holds, 1 = at least one documented claim is false.
set -u

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE OLIVERCODE_SCAN_TREE

MODE="worktree"
while [ $# -gt 0 ]; do
  case "$1" in
    --clone) MODE="clone"; shift ;;
    *) echo "rehearse-install.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT="$(mktemp -d)"
PASS=0; FAIL=0; FAILED_NAMES=""
trap 'rm -rf "$ROOT"' EXIT

say()  { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  [OK]   $1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES $2"; say "  [FAIL] $1"; }

# A fresh copy of the checkout as a committed git repo, matching a real clone.
mk_oc() { # $1 = dest
  local dest="$1"
  if [ "$MODE" = "clone" ]; then
    git clone -q "$REPO" "$dest" || { say "FAIL: clone failed"; exit 1; }
    # The clone's origin is a local path. Point it at the source's real origin URL, in the clone only
    # and without fetching, so health and validate.sh see the identity a real clone has.
    local origin_url
    origin_url="$(git -C "$REPO" remote get-url origin 2>/dev/null)" \
      && git -C "$dest" remote set-url origin "$origin_url"
    return
  fi
  mkdir -p "$dest"
  (cd "$REPO" && git ls-files -z | while IFS= read -r -d '' f; do
    mkdir -p "$dest/$(dirname "$f")"
    cp -R "$REPO/$f" "$dest/$f" 2>/dev/null   # -R: .claude/skills/* is a symlink to a directory
  done)
  chmod +x "$dest/scripts/olivercode" "$dest"/scripts/*.sh "$dest"/scripts/qa/*.sh "$dest"/.githooks/* 2>/dev/null
  git -C "$dest" init -q .
  git -C "$dest" add -A >/dev/null 2>&1
  # The identity has no "@": an email literal would trip the PII gate.
  git -C "$dest" -c user.email=rehearsal -c user.name=rehearsal commit -q -m base --no-verify >/dev/null 2>&1
}

mk_repo() { # $1 = dest, $2 = optional rules filename
  mkdir -p "$1/scripts"
  printf '#!/usr/bin/env bash\necho ok\n' > "$1/scripts/validate.sh"
  chmod +x "$1/scripts/validate.sh"
  [ -n "${2:-}" ] && printf '# rules\n' > "$1/$2"
  git -C "$1" init -q .
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" -c user.email=rehearsal -c user.name=rehearsal commit -q -m init --no-verify >/dev/null 2>&1
}

register() { # $1 = oc dir, $2.. = "name[:path]" entries
  local oc="$1"; shift
  HOME="$H" python3 - "$oc/shared/repo-profiles.json" "$@" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
tmpl = next(iter(d["profiles"].values()), None) or d["_exampleProfile"]
d["profiles"] = {}
for spec in sys.argv[2:]:
    name, _, path = spec.partition(":")
    e = json.loads(json.dumps(tmpl)); e["name"] = name
    if path: e["path"] = path
    d["profiles"][name] = e
json.dump(d, open(p, "w"), indent=2)
PY
}

# Returns 0 only when scripts/qa/probe-secret-gate.sh sees the secret blocked at Gate 1. The probe
# is the one home of that check; this runs it with the sandbox HOME and a throwaway git identity.
probe_blocked() { # $1 = repo dir
  ( cd "$1" && HOME="$H" GIT_AUTHOR_NAME=rehearsal GIT_AUTHOR_EMAIL=rehearsal \
      GIT_COMMITTER_NAME=rehearsal GIT_COMMITTER_EMAIL=rehearsal \
      bash "$SCRIPT_DIR/probe-secret-gate.sh" ) >/dev/null 2>&1
}

new_case() { # $1 = case id
  H="$ROOT/$1/home"; WS="$ROOT/$1/ws"
  mkdir -p "$H" "$WS"
  case "$H" in "$ROOT"/*) ;; *) say "ABORT: HOME $H is outside the sandbox"; exit 1 ;; esac
}

oc() { (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode "$@"); }

# ------------------------------------------------ S1 fresh machine, real install
say "--- S1: brand-new machine, sibling layout, the real install ---"
new_case s1
mk_oc "$WS/OliverCode"; mk_repo "$WS/app-a"; mk_repo "$WS/app-b"
oc install >/dev/null 2>&1 && ok "install on virgin HOME" s1 || bad "install on virgin HOME" s1
[ -L "$H/.claude/CLAUDE.md" ] && ok "CLAUDE.md symlinked" s1 || bad "CLAUDE.md symlinked" s1
OCR="$(dirname "$(readlink "$H/.claude/CLAUDE.md" 2>/dev/null)" 2>/dev/null)"
[ -f "$OCR/docs/RULES.md" ] && [ -L "$H/.claude/VOICE.md" ] \
  && ok "\$OC resolves from a virgin HOME" s1 || bad "\$OC resolves from a virgin HOME" s1
ADOPT="$H/.claude/skills/olivercode-adoption/SKILL.md"
[ -f "$WS/OliverCode/.claude/skills/olivercode-adoption/SKILL.md" ] && grep -q "^name: olivercode-adoption" "$WS/OliverCode/.claude/skills/olivercode-adoption/SKILL.md" \
  && ok "adoption skill resolves in a fresh clone, before any setup" s1 || bad "adoption skill resolves in a fresh clone, before any setup" s1
[ -e "$ADOPT" ] && ok "adoption skill linked into ~/.claude/skills" s1 || bad "adoption skill linked into ~/.claude/skills" s1
register "$WS/OliverCode" app-a app-b
oc sync-hooks 2>&1 | grep -q "app-a: hooks synced" && ok "sync-hooks reaches fleet" s1 || bad "sync-hooks reaches fleet" s1
probe_blocked "$WS/app-a" && ok "secret blocked in app-a (Gate 1 line seen)" s1 || bad "secret blocked in app-a" s1
probe_blocked "$WS/app-b" && ok "secret blocked in app-b (Gate 1 line seen)" s1 || bad "secret blocked in app-b" s1
oc conform --offline 2>&1 | grep -A8 "^app-a" | grep -q "\[OK\] hooks" && ok "conform confirms the adopted fleet's hooks" s1 || bad "conform confirms the adopted fleet's hooks" s1

# ------------------------------------------------- S2 existing ~/.claude preserved
say "--- S2: existing ~/.claude (real rules + vendor skill + foreign symlink) ---"
new_case s2
mk_oc "$WS/OliverCode"
mkdir -p "$H/.claude/skills/vendor-skill" "$H/elsewhere/other-skill"
printf 'my precious rules\n' > "$H/.claude/CLAUDE.md"
printf 'vendor content\n' > "$H/.claude/skills/vendor-skill/SKILL.md"
ln -s "$H/elsewhere/other-skill" "$H/.claude/skills/other-skill"
oc install >/dev/null 2>&1
grep -q "my precious rules" "$H/.claude/CLAUDE.md.pre-olivercode" 2>/dev/null \
  && ok "old rules backed up verbatim" s2 || bad "old rules backed up verbatim" s2
[ -L "$H/.claude/CLAUDE.md" ] && ok "new symlink in place" s2 || bad "new symlink in place" s2
[ -f "$H/.claude/skills/vendor-skill/SKILL.md" ] && grep -q vendor "$H/.claude/skills/vendor-skill/SKILL.md" \
  && ok "vendor real dir untouched" s2 || bad "vendor real dir untouched" s2
[ -L "$H/.claude/skills/other-skill" ] && [ "$(readlink "$H/.claude/skills/other-skill")" = "$H/elsewhere/other-skill" ] \
  && ok "foreign symlink untouched" s2 || bad "foreign symlink untouched" s2

# --------------------------------------------- S3 scattered fleet via profile path
say "--- S3: scattered repos, explicit path field, no shared parent ---"
new_case s3
mk_oc "$WS/OliverCode"
mkdir -p "$WS/deep/work/clients" "$WS/side"
mk_repo "$WS/deep/work/clients/api"; mk_repo "$WS/side/tool"
register "$WS/OliverCode" "api:$WS/deep/work/clients/api" "tool:$WS/side/tool"
oc sync-hooks 2>&1 | grep -q "api: hooks synced" && ok "path field resolves absolute" s3 || bad "path field resolves absolute" s3
probe_blocked "$WS/deep/work/clients/api" && ok "secret blocked in scattered repo" s3 || bad "secret blocked in scattered repo" s3
oc conform --offline 2>&1 | grep -q "^api$" && ok "conform finds scattered repo" s3 || bad "conform finds scattered repo" s3

# ------------------------------------------------------------- S4 --root layout
say "--- S4: fleet shares a parent that is not OliverCode's parent ---"
new_case s4
mkdir -p "$WS/tools" "$WS/code"
mk_oc "$WS/tools/OliverCode"; mk_repo "$WS/code/web"; mk_repo "$WS/code/api"
oc4() { (cd "$WS/tools/OliverCode" && HOME="$H" python3 scripts/olivercode "$@"); }
register "$WS/tools/OliverCode" web api
oc4 sync-hooks --root "$WS/code" 2>&1 | grep -q "web: hooks synced" && ok "--root honored by sync-hooks" s4 || bad "--root honored by sync-hooks" s4
probe_blocked "$WS/code/web" && ok "secret blocked under --root" s4 || bad "secret blocked under --root" s4
oc4 conform --offline --root "$WS/code" 2>&1 | grep -q "^web$" && ok "--root honored by conform" s4 || bad "--root honored by conform" s4
# A wrong --root must not read as success.
oc4 sync-hooks --root "$WS/nowhere" >/dev/null 2>&1 \
  && bad "nonexistent --root should hard-error" s4 || ok "nonexistent --root hard-errors" s4
mkdir -p "$WS/emptydir"
oc4 sync-hooks --root "$WS/emptydir" 2>&1 | grep -q "0 target(s) synced" \
  && ok "wrong --root reports 0 synced, not success" s4 || bad "wrong --root reports 0 synced, not success" s4

# --------------------------------------------------------------- S5 discover
say "--- S5: discover on a messy existing setup ---"
new_case s5
mk_oc "$WS/OliverCode"
mk_repo "$WS/r1" AGENTS.md; mk_repo "$WS/r2" .cursorrules; mk_repo "$WS/r3" CLAUDE.md; mk_repo "$WS/r4"
out5="$( (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode discover --root "$WS") 2>&1 )"
echo "$out5" | grep -q "AGENTS.md"     && ok "discover flags AGENTS.md" s5     || bad "discover flags AGENTS.md" s5
echo "$out5" | grep -q ".cursorrules"  && ok "discover flags .cursorrules" s5  || bad "discover flags .cursorrules" s5
echo "$out5" | grep -qi "hooksPath"    && ok "discover reports hook state" s5  || bad "discover reports hook state" s5
echo "$out5" | sed -n '/^{/,/^}/p' | python3 -c "import json,sys; d=json.load(sys.stdin); assert all('path' in v for v in d.values()), 'no path'" 2>/dev/null \
  && ok "emitted profile skeleton is valid JSON with paths" s5 || bad "emitted profile skeleton is valid JSON with paths" s5

# --------------------------------------------------------------- S6 bootstrap
say "--- S6: bootstrap a repo (dry-run, real, presence vs strict, idempotent) ---"
new_case s6
mk_oc "$WS/OliverCode"; mk_repo "$WS/newrepo"
printf 'hand-written\n' > "$WS/newrepo/CLAUDE.md"
before6="$(find "$WS/newrepo" -type f -not -path '*/.git/*' | sort | xargs cat | cksum)"
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode bootstrap "$WS/newrepo" --dry-run) >/dev/null 2>&1
after6="$(find "$WS/newrepo" -type f -not -path '*/.git/*' | sort | xargs cat | cksum)"
[ "$before6" = "$after6" ] && ok "dry-run writes nothing" s6 || bad "dry-run writes nothing" s6
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode bootstrap "$WS/newrepo") >/dev/null 2>&1
grep -q "hand-written" "$WS/newrepo/CLAUDE.md" && ok "presence file not clobbered" s6 || bad "presence file not clobbered" s6
[ -x "$WS/newrepo/.githooks/pre-commit" ] && ok "hooks stamped executable" s6 || bad "hooks stamped executable" s6
run1="$( (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode bootstrap "$WS/newrepo") 2>&1 )"
run2="$( (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode bootstrap "$WS/newrepo") 2>&1 )"
[ "$run1" = "$run2" ] && ok "bootstrap idempotent (same report twice)" s6 || bad "bootstrap idempotent (same report twice)" s6

# --------------------------------------------------------------- S7 hookVariant
say "--- S7: a repo with a declared hook variant ---"
new_case s7
mk_oc "$WS/OliverCode"; mk_repo "$WS/special"
mkdir -p "$WS/special/.githooks"
printf '#!/usr/bin/env bash\necho custom-gate\nexit 0\n' > "$WS/special/.githooks/pre-commit"
chmod +x "$WS/special/.githooks/pre-commit"
git -C "$WS/special" config core.hooksPath .githooks
register "$WS/OliverCode" special
HOME="$H" python3 - "$WS/OliverCode/shared/repo-profiles.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["profiles"]["special"]["hookVariant"] = "custom governance path"
json.dump(d, open(p, "w"), indent=2)
PY
oc sync-hooks 2>&1 | grep -q "special: declared hook variant" && ok "variant skipped by sync-hooks" s7 || bad "variant skipped by sync-hooks" s7
grep -q "custom-gate" "$WS/special/.githooks/pre-commit" && ok "variant hook not overwritten" s7 || bad "variant hook not overwritten" s7
h7="$(oc conform --offline 2>&1)"
echo "$h7" | grep -A8 "^special" | grep -q "declared hook variant" && ok "conform reports the variant with a note" s7 || bad "conform reports the variant with a note" s7
echo "$h7" | grep -A8 "^special" | grep -q "\[FAIL\] hooks" && bad "variant does not fail the hooks check" s7 || ok "variant does not fail the hooks check" s7

# --------------------------------------------------------------- S8 backout
say "--- S8: the documented backout removes everything ---"
new_case s8
mk_oc "$WS/OliverCode"; mk_repo "$WS/app"
mkdir -p "$H/.claude/skills/vendor-skill" "$H/elsewhere/other-skill"
printf 'original rules\n' > "$H/.claude/CLAUDE.md"
ln -s "$H/elsewhere/other-skill" "$H/.claude/skills/other-skill"
cat > "$H/.claude/settings.json" <<'JSON'
{"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "~/mine.sh"}]}]}}
JSON
oc install >/dev/null 2>&1
register "$WS/OliverCode" app
oc sync-hooks >/dev/null 2>&1
probe_blocked "$WS/app" || bad "precondition: hooks active before backout" s8
grep -q "scripts/hooks/" "$H/.claude/settings.json" || bad "precondition: install wrote its settings.json hooks" s8
[ -L "$H/.claude/VOICE.md" ] || bad "precondition: install linked VOICE.md" s8
oc uninstall >/dev/null 2>&1 && ok "uninstall exits 0" s8 || bad "uninstall exits 0" s8
git -C "$WS/app" config --unset core.hooksPath
grep -q "original rules" "$H/.claude/CLAUDE.md" && [ ! -L "$H/.claude/CLAUDE.md" ] \
  && ok "backout restores original rules" s8 || bad "backout restores original rules" s8
[ ! -e "$H/.claude/VOICE.md" ] && [ ! -L "$H/.claude/VOICE.md" ] \
  && ok "backout removes the VOICE.md link" s8 || bad "backout removes the VOICE.md link" s8
n_links="$(find "$H/.claude" -type l -lname "*/OliverCode/*" 2>/dev/null | wc -l | tr -d ' ')"
[ "$n_links" = "0" ] && ok "backout leaves no link into OliverCode" s8 || bad "backout leaves no link into OliverCode ($n_links left)" s8
grep -q "scripts/hooks/" "$H/.claude/settings.json" \
  && bad "backout leaves OliverCode hook entries in settings.json" s8 || ok "backout removes the settings.json hook entries" s8
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d=={"model":"opus","hooks":{"PreToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":"~/mine.sh"}]}]}}' \
  "$H/.claude/settings.json" 2>/dev/null \
  && ok "backout keeps the owner's own settings and hook" s8 || bad "backout keeps the owner's own settings and hook" s8
[ -d "$H/.claude/skills/vendor-skill" ] && [ "$(readlink "$H/.claude/skills/other-skill")" = "$H/elsewhere/other-skill" ] \
  && ok "backout keeps the owner's skill folder and foreign link" s8 || bad "backout keeps the owner's skill folder and foreign link" s8
oc uninstall >/dev/null 2>&1 && ok "uninstall twice exits 0" s8 || bad "uninstall twice exits 0" s8
# With hooksPath unset the secret commits again: the commit must SUCCEED for the gates to be gone.
( cd "$WS/app" && printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt && git add leak-probe.txt \
  && HOME="$H" git -c user.email=rehearsal -c user.name=rehearsal commit -qm probe >/dev/null 2>&1 ) \
  && ok "backout: hooks genuinely gone (secret commits again)" s8 || bad "backout: hooks still firing after unset" s8

say "--- S8b: backout after the checkout moved leaves nothing behind ---"
new_case s8b
mk_oc "$WS/OliverCode"
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode install) >/dev/null 2>&1
mv "$WS/OliverCode" "$WS/Moved"
(cd "$WS/Moved" && HOME="$H" python3 scripts/olivercode uninstall) >/dev/null 2>&1 \
  && ok "uninstall from the moved checkout exits 0" s8b || bad "uninstall from the moved checkout exits 0" s8b
n_left="$(find "$H/.claude" -type l 2>/dev/null | wc -l | tr -d ' ')"
[ "$n_left" = "0" ] && ok "no dangling link left after a move" s8b || bad "no dangling link left after a move ($n_left left)" s8b
[ ! -e "$H/.claude/settings.json" ] && ok "settings.json that held only OliverCode's hooks is gone" s8b \
  || bad "settings.json that held only OliverCode's hooks is gone" s8b
n_files="$(find "$H/.claude" -type f 2>/dev/null | wc -l | tr -d ' ')"
[ "$n_files" = "0" ] && ok "no file of OliverCode's left in ~/.claude, install record included" s8b \
  || bad "no file of OliverCode's left in ~/.claude ($n_files left)" s8b

# --------------------------------------------------------------- S9 idempotency
say "--- S9: every command safe to run twice ---"
new_case s9
mk_oc "$WS/OliverCode"; mk_repo "$WS/app"
oc install >/dev/null 2>&1 && oc install >/dev/null 2>&1 && ok "install x2" s9 || bad "install x2" s9
register "$WS/OliverCode" app
oc sync-hooks >/dev/null 2>&1 && oc sync-hooks >/dev/null 2>&1 && ok "sync-hooks x2" s9 || bad "sync-hooks x2" s9
probe_blocked "$WS/app" && ok "still enforcing after re-runs" s9 || bad "still enforcing after re-runs" s9

# --------------------------------------------------------------- S10 update
say "--- S10: update pulls the tracking branch and re-syncs ---"
new_case s10
mk_oc "$WS/origin"
git -C "$WS/origin" branch -m main 2>/dev/null
git clone -q "$WS/origin" "$WS/OliverCode"
chmod +x "$WS/OliverCode/scripts/olivercode" "$WS/OliverCode"/scripts/*.sh 2>/dev/null
mk_repo "$WS/app"
register "$WS/OliverCode" app
( cd "$WS/origin" && printf '\n# upstream change\n' >> README.md \
  && git add README.md && git -c user.email=rehearsal -c user.name=rehearsal commit -q -m upstream --no-verify )
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode update) >/dev/null 2>&1
grep -q "upstream change" "$WS/OliverCode/README.md" && ok "update pulled upstream commit" s10 || bad "update pulled upstream commit" s10
[ -x "$WS/app/.githooks/pre-commit" ] && ok "update re-synced fleet hooks" s10 || bad "update re-synced fleet hooks" s10

# ------------------------------------------------- S11 probe in a no-commit repo
say "--- S11: the probe script works in a repo with no commits ---"
new_case s11
mk_oc "$WS/OliverCode"
mkdir -p "$WS/fresh" && git -C "$WS/fresh" init -q .
register "$WS/OliverCode" fresh
oc sync-hooks >/dev/null 2>&1
( cd "$WS/fresh" && HOME="$H" bash "$WS/OliverCode/scripts/qa/probe-secret-gate.sh" ) >/dev/null 2>&1 \
  && ok "probe-secret-gate.sh passes and cleans up with no HEAD" s11 \
  || bad "probe-secret-gate.sh passes and cleans up with no HEAD" s11
[ ! -e "$WS/fresh/leak-probe.txt" ] && ok "probe leaves no file behind" s11 || bad "probe leaves no file behind" s11
# A commit that fails for another reason must read as inconclusive, never as proof.
mkdir -p "$WS/ungated" && git -C "$WS/ungated" init -q . && git -C "$WS/ungated" config user.useConfigOnly true
( cd "$WS/ungated" && HOME="$H" bash "$WS/OliverCode/scripts/qa/probe-secret-gate.sh" ) >/dev/null 2>&1 \
  && bad "probe counted a non-Gate-1 failure as proof" s11 || ok "probe rejects a commit that failed outside Gate 1" s11

# --------------------------------------------------------------- S12 zero-config
say "--- S12: zero-config clone basics ---"
new_case s12
mk_oc "$WS/OliverCode"
for cmd in "--help" "health" "skills"; do
  (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode $cmd) >/dev/null 2>&1 \
    && ok "olivercode $cmd" s12 || bad "olivercode $cmd" s12
done
(cd "$WS/OliverCode" && HOME="$H" bash scripts/validate.sh) >/dev/null 2>&1 \
  && ok "validate.sh on a clean copy" s12 || bad "validate.sh on a clean copy" s12

say ""
say "================ REHEARSAL: $PASS passed, $FAIL failed ================"
[ -n "$FAILED_NAMES" ] && say "failing cases:$FAILED_NAMES"
[ "$FAIL" -eq 0 ]
