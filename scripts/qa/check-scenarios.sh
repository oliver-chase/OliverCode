#!/usr/bin/env bash
# ─── Scenario Matrix ──────────────────────────────────────────────────────
# Every documented setup and walkthrough case, each in an isolated sandbox with a
# throwaway HOME: fresh machine, existing ~/.claude, scattered fleet via `path`,
# --root layouts (right and wrong), discover, bootstrap, hookVariant, the full
# documented backout, idempotency, update, the no-commit probe, zero-config basics.
#
# check-fork-usable.sh stays the fast gate (CI + full-qa-pass): clone works, the
# core adoption path governs. This is the exhaustive complement -- run it after
# changing the launcher, the hooks, or docs/ADOPTING.md. Everything it asserts is
# a sentence somewhere in ADOPTING.md or the README; when one fails, either the
# code or that sentence is lying.
#
# Exercises the WORKING TREE's tracked files, so uncommitted fixes are what gets
# tested. macOS userland (md5, BSD find), same declared platform as the repo.
#
# Exit codes: 0 = every scenario holds, 1 = at least one documented claim is false.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT="$(mktemp -d)"
PASS=0; FAIL=0; FAILED_NAMES=""

say()  { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  [OK]   $1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES $2"; say "  [FAIL] $1"; }

# Fresh copy of the working tree's tracked files as a committed git repo.
mk_oc() { # $1 = dest
  local dest="$1"
  mkdir -p "$dest"
  (cd "$REPO" && git ls-files -z | while IFS= read -r -d '' f; do
    mkdir -p "$dest/$(dirname "$f")"
    cp -R "$REPO/$f" "$dest/$f" 2>/dev/null
  done)
  chmod +x "$dest/scripts/olivercode" "$dest"/scripts/*.sh "$dest"/scripts/qa/*.sh "$dest"/.githooks/* 2>/dev/null
  git -C "$dest" init -q .
  git -C "$dest" add -A >/dev/null 2>&1
  git -C "$dest" -c user.email=matrix -c user.name=matrix commit -q -m base --no-verify >/dev/null 2>&1
}

mk_repo() { # $1 = dest, $2 = optional rules filename
  mkdir -p "$1/scripts"
  printf '#!/usr/bin/env bash\necho ok\n' > "$1/scripts/validate.sh"
  chmod +x "$1/scripts/validate.sh"
  [ -n "${2:-}" ] && printf '# rules\n' > "$1/$2"
  git -C "$1" init -q .
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" -c user.email=matrix -c user.name=matrix commit -q -m init --no-verify >/dev/null 2>&1
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

probe_blocked() { # $1 = repo dir; returns 0 if a staged secret is BLOCKED
  ( cd "$1" \
    && printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt \
    && git add leak-probe.txt \
    && HOME="$H" git -c user.email=matrix -c user.name=matrix commit -m probe >/dev/null 2>&1 )
  local committed=$?
  ( cd "$1" && git rm -q --cached leak-probe.txt 2>/dev/null; rm -f leak-probe.txt )
  [ "$committed" -ne 0 ]
}

new_case() { # $1 = case id
  H="$ROOT/$1/home"; WS="$ROOT/$1/ws"
  mkdir -p "$H" "$WS"
}

# ---------------------------------------------------------------- S1 fresh machine
say "--- S1: brand-new machine, sibling layout, full manual path ---"
new_case s1
mk_oc "$WS/OliverCode"; mk_repo "$WS/app-a"; mk_repo "$WS/app-b"
oc() { (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode "$@"); }
oc install >/dev/null 2>&1 && ok "install on virgin HOME" s1 || bad "install on virgin HOME" s1
[ -L "$H/.claude/CLAUDE.md" ] && ok "CLAUDE.md symlinked" s1 || bad "CLAUDE.md symlinked" s1
register "$WS/OliverCode" app-a app-b
oc sync-hooks 2>&1 | grep -q "app-a: hooks synced" && ok "sync-hooks reaches fleet" s1 || bad "sync-hooks reaches fleet" s1
probe_blocked "$WS/app-a" && ok "secret blocked in app-a" s1 || bad "secret blocked in app-a" s1
probe_blocked "$WS/app-b" && ok "secret blocked in app-b" s1 || bad "secret blocked in app-b" s1
oc health >/dev/null 2>&1 && ok "health exits 0" s1 || bad "health exits 0" s1

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
oc health 2>&1 | grep -q "api: hooksPath set" && ok "health finds scattered repo" s3 || bad "health finds scattered repo" s3

# ------------------------------------------------------------- S4 --root layout
say "--- S4: fleet shares a parent that is not OliverCode's parent ---"
new_case s4
mkdir -p "$WS/tools" "$WS/code"
mk_oc "$WS/tools/OliverCode"; mk_repo "$WS/code/web"; mk_repo "$WS/code/api"
oc4() { (cd "$WS/tools/OliverCode" && HOME="$H" python3 scripts/olivercode "$@"); }
register "$WS/tools/OliverCode" web api
oc4 sync-hooks --root "$WS/code" 2>&1 | grep -q "web: hooks synced" && ok "--root honored by sync-hooks" s4 || bad "--root honored by sync-hooks" s4
probe_blocked "$WS/code/web" && ok "secret blocked under --root" s4 || bad "secret blocked under --root" s4
oc4 health --root "$WS/code" 2>&1 | grep -q "web: hooksPath set" && ok "--root honored by health" s4 || bad "--root honored by health" s4
# The failure the docs warn about: a wrong --root must NOT read as success.
# Nonexistent dir: hard error. Existing-but-wrong dir: visible "0 target(s) synced".
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
# the emitted skeleton must be valid JSON containing explicit paths
echo "$out5" | sed -n '/^{/,/^}/p' | python3 -c "import json,sys; d=json.load(sys.stdin); assert all('path' in v for v in d.values()), 'no path'" 2>/dev/null \
  && ok "emitted profile skeleton is valid JSON with paths" s5 || bad "emitted profile skeleton is valid JSON with paths" s5

# --------------------------------------------------------------- S6 bootstrap
say "--- S6: bootstrap a repo (dry-run, real, presence vs strict, idempotent) ---"
new_case s6
mk_oc "$WS/OliverCode"; mk_repo "$WS/newrepo"
printf 'hand-written\n' > "$WS/newrepo/CLAUDE.md"   # presence-mode file pre-exists
before6="$(find "$WS/newrepo" -type f | sort | md5)"
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode bootstrap "$WS/newrepo" --dry-run) >/dev/null 2>&1
after6="$(find "$WS/newrepo" -type f | sort | md5)"
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
h7="$(oc health 2>&1)"
echo "$h7" | grep -q "special.*WARN\|WARN.*special\|\[WARN\] special" && ok "health reports variant as WARN" s7 || bad "health reports variant as WARN" s7
oc health >/dev/null 2>&1 && ok "variant does not fail health" s7 || bad "variant does not fail health" s7

# --------------------------------------------------------------- S8 backout
say "--- S8: the documented backout actually removes everything ---"
new_case s8
mk_oc "$WS/OliverCode"; mk_repo "$WS/app"
printf 'original rules\n' > "$H/.claude-orig-marker"
mkdir -p "$H/.claude"
printf 'original rules\n' > "$H/.claude/CLAUDE.md"
oc install >/dev/null 2>&1
register "$WS/OliverCode" app
oc sync-hooks >/dev/null 2>&1
probe_blocked "$WS/app" || bad "precondition: hooks active before backout" s8
# docs/ADOPTING.md "Backing out", verbatim steps
( HOME="$H" bash -c '
  mv ~/.claude/CLAUDE.md.pre-olivercode ~/.claude/CLAUDE.md
  find ~/.claude/skills -maxdepth 1 -type l -lname "*/OliverCode/skills/*" -delete
' ) 2>/dev/null
git -C "$WS/app" config --unset core.hooksPath
grep -q "original rules" "$H/.claude/CLAUDE.md" && ok "backout restores original rules" s8 || bad "backout restores original rules" s8
n_links="$(find "$H/.claude/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')"
[ "$n_links" = "0" ] && ok "backout removes all skill symlinks" s8 || bad "backout removes all skill symlinks ($n_links left)" s8
probe_blocked "$WS/app" && bad "backout: hooks still firing after unset" s8 || ok "backout: hooks genuinely gone (secret commits again)" s8
( cd "$WS/app" && git log --oneline | grep -q probe && git reset -q --hard HEAD~1 )

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
  && git add README.md && git -c user.email=matrix -c user.name=matrix commit -q -m upstream --no-verify )
(cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode update) >/dev/null 2>&1
grep -q "upstream change" "$WS/OliverCode/README.md" && ok "update pulled upstream commit" s10 || bad "update pulled upstream commit" s10
[ -x "$WS/app/.githooks/pre-commit" ] && ok "update re-synced fleet hooks" s10 || bad "update re-synced fleet hooks" s10

# ------------------------------------------------- S11 probe in a no-commit repo
say "--- S11: ADOPTING's probe cleanup works in a repo with no commits ---"
new_case s11
mk_oc "$WS/OliverCode"
mkdir -p "$WS/fresh" && git -C "$WS/fresh" init -q .
register "$WS/OliverCode" fresh
oc sync-hooks >/dev/null 2>&1
( cd "$WS/fresh" \
  && printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt \
  && git add leak-probe.txt \
  && ! HOME="$H" git -c user.email=matrix -c user.name=matrix commit -m probe >/dev/null 2>&1 \
  && git rm -q --cached leak-probe.txt && rm -f leak-probe.txt ) \
  && ok "probe blocked + documented cleanup works with no HEAD" s11 \
  || bad "probe blocked + documented cleanup works with no HEAD" s11

# --------------------------------------------------------------- S12 zero-config
say "--- S12: zero-config clone basics ---"
new_case s12
mk_oc "$WS/OliverCode"
for cmd in "--help" "health" "skills"; do
  (cd "$WS/OliverCode" && HOME="$H" python3 scripts/olivercode $cmd) >/dev/null 2>&1 \
    && ok "olivercode $cmd" s12 || bad "olivercode $cmd" s12
done
(cd "$WS/OliverCode" && HOME="$H" bash scripts/validate.sh) >/dev/null 2>&1 \
  && ok "validate.sh on clean copy" s12 || bad "validate.sh on clean copy" s12

# ----------------------------------------------------------------------- summary
say ""
say "================ MATRIX: $PASS passed, $FAIL failed ================"
[ -n "$FAILED_NAMES" ] && say "failing cases:$FAILED_NAMES"
rm -rf "$ROOT"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
exit 0
