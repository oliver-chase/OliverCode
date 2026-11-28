#!/usr/bin/env bash
# A new user's first run, checked in an empty HOME against real GitHub (#1497).
# Clones OliverCode's staging branch into a new HOME, runs install there, then backlog-setup and drain on a private
# sandbox repo whose board holds plain issues. The repo and its Project are made by the first run and reused after,
# and a plain issue that is no longer open is made again. Each gap is filed as a Ready P1 story under this checkout's
# error epic, unless an open story already carries its mark.
#
# Usage: bash scripts/first_run_check.sh
# Needs `gh` signed in with the repo and project scopes: the new HOME gets that token as GH_TOKEN.
# Exit 0: no gap. 1: each gap is a `GAP:` line with a story. 2: the check could not run, or a gap has no story.
set -uo pipefail

[ $# -eq 0 ] || { echo "Usage: bash scripts/first_run_check.sh" >&2; exit 2; }
die() { echo "first_run_check: $*" >&2; exit 2; }
GAPS=0
FOUND=()
gap() { GAPS=$((GAPS + 1)); FOUND+=("$1" "$2"); echo "GAP: $2"; }  # gap "FILES AREA" "WHAT IS WRONG"

BRANCH=staging
NAME=olivercode-first-run-sandbox
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OC_URL="$(git -C "$REPO" remote get-url origin)" || die "this checkout has no origin to clone"
TOKEN="$(gh auth token)" || die "gh is not signed in"
OWNER="$(gh api user --jq .login)" || die "the GitHub account could not be read"
SLUG="$OWNER/$NAME"

WORK="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/oc-first-run.XXXXXX")" && pwd -P)" || die "no temporary folder"
H="$WORK/home"

# file_gaps AREA TEXT ...: runs as the owner, after the listing, because it writes the card queue under ~/.olivercode.
file_gaps() {
  python3 -I - "$REPO" "$@" <<'PY'
import datetime, subprocess, sys
from pathlib import Path
root, found = Path(sys.argv[1]), sys.argv[2:]
sys.path.insert(0, str(root / "scripts"))
from lib import intake, cmd_dispatch
from lib.local_config import backlog_config
dest = intake.destination(root, root)
if not dest:
    sys.exit("No gap was filed: this checkout's backlog config names no errorEpic.")
slug, epic = dest
batch, cfg = cmd_dispatch.batch_project, backlog_config(root)
gh = lambda args: subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
stories, failed = intake.open_stories(slug), False
for area, text in zip(found[::2], found[1::2]):
    mark = intake.signature("first-run", text)  # numbers are flattened, so one gap on three issues is one story
    number = next((n for n, s in stories.items() if mark in (s.get("body") or "")), None)
    if number:
        print(f"Already filed as #{number}: {text}")
        continue
    body = f"""**As a new user**, I want a first run without this gap, so that it works or says exactly what I must do.

```gherkin
Feature: A new user's first run
  Scenario: The first-run check no longer finds this gap
    Given this story has landed on staging
    When `bash scripts/first_run_check.sh` runs
    Then it prints no GAP line for the gap below
```

Gap: {text}

Epic: #{epic}
Blocked by: none.
Priority: P1. Size: S. Work type: Story.

Existing coverage checked: no open story carried {mark} when the first-run check (#1497) found this on {datetime.date.today()}.

Files area: {area}
"""
    number = intake.file_story(slug, root, f"First run: {text}"[:120], body, gh)
    if not number:
        print(f"Not filed: {text}")
        failed = True
        continue
    stories[number] = {"body": body}
    # file_story queues Status alone, and a drain skips a card with no Size.
    job = {"cfg": cfg, "issues": [{"number": number, "fields": {"priority": "P1", "size": "S", "workType": "Story"}}]}
    batch.with_queue(lambda queue: (None, queue + [job]))
    print(f"Filed #{number}: {text}")
batch.report(batch.send(cfg, batch.run_gh), sys.stdout, sys.stderr)  # a held send stays queued for the replay job
sys.exit(1 if failed else 0)
PY
}

finish() {  # on every exit: deletes the HOME first, so one that stays is a gap too, then files the gaps
  local code=$1
  pkill -f "$WORK/" 2>/dev/null  # a drain still running in the new HOME
  rm -rf "$WORK"
  if [ -e "$WORK" ]; then
    gap scripts/first_run_check.sh "the empty HOME could not be deleted"
    echo "It is still at $WORK"
  else
    echo "Deleted the empty HOME: $H"
  fi
  if [ "$GAPS" -gt 0 ]; then
    [ "$code" -ne 0 ] || code=1
    file_gaps "${FOUND[@]}" || { echo "first_run_check: not every gap was filed" >&2; code=2; }
  fi
  echo "RESULT: $GAPS gap(s)"
  exit "$code"
}
trap 'finish $?' EXIT
trap 'exit 2' INT TERM
mkdir -p "$H/Developer/Repos" "$WORK/bin" "$WORK/tmp" || die "the new HOME could not be made"
# The drain's macOS notifications are kept in a file, so the check puts nothing on the owner's screen.
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/notifications.log"\n' "$WORK" > "$WORK/bin/osascript"
chmod +x "$WORK/bin/osascript"

# Every command of the new user runs with an empty environment: no OliverCode, Claude or git setting of this machine reaches it.
# The system git config is left out because its keychain helper would open a dialog in a HOME with no keychain.
newuser() {
  env -i HOME="$H" PATH="$WORK/bin:$PATH" TMPDIR="$WORK/tmp" USER="${USER:-newuser}" LANG=en_US.UTF-8 TERM=dumb \
    GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GH_TOKEN="$TOKEN" "$@"
}

# listing save|compare: every entry under this user's ~/.claude and ~/.olivercode. Live sessions and a running drain write
# there too, so compare fails on a change to a file install writes, on a new path named for this run, and on a file that
# gained a mention of this run. Session records quote this check's own output, so their content is not searched.
listing() {
  python3 -I - "$1" "$HOME" "$WORK/before.json" "$(basename "$WORK")" "$NAME" <<'PY'
import json, os, re, sys
mode, home, saved, marker, sandbox = sys.argv[1:]
INSTALL = re.compile(r"\.claude/(CLAUDE\.md|VOICE\.md|DESIGN\.md|\.olivercode-install\.json|settings\.json[^/]*|skills(/.*)?)$")
RECORDS = re.compile(r"\.claude/(projects|sessions|session-env|shell-snapshots|file-history|telemetry|history\.jsonl)(/|$)")
needles = [marker.encode(), f"/{sandbox}".encode(), f'"{sandbox}"'.encode()]

def mentions(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return 0
    return sum(data.count(n) for n in needles)

now = {}
for top in (".claude", ".olivercode"):
    for folder, dirs, files in os.walk(os.path.join(home, top)):
        for name in dirs + files:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, home)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if os.path.islink(path):
                now[rel] = ["link", os.readlink(path), 0]
            elif os.path.isdir(path):
                now[rel] = ["dir", "", 0]
            else:
                seen = 0 if RECORDS.match(rel) else mentions(path)
                now[rel] = ["file", f"{st.st_size} {st.st_mtime_ns}", seen]
if mode == "save":
    with open(saved, "w") as handle:
        json.dump(now, handle)
    print(f"Listed {len(now)} entries under ~/.claude and ~/.olivercode before the run.")
    sys.exit(0)
with open(saved) as handle:
    before = json.load(handle)
changed = sorted(p for p in set(before) | set(now) if before.get(p, [None, None])[:2] != now.get(p, [None, None])[:2])
bad = []
for p in changed:
    if INSTALL.match(p):
        bad.append(f"{p} is a file install writes, and it changed")
    elif p not in before and (marker in p or sandbox in p):
        bad.append(f"{p} is new and named for this run")
    elif p in now and now[p][2] > before.get(p, [0, 0, 0])[2]:
        bad.append(f"{p} gained a mention of this run")
print(f"Listed {len(now)} entries after the run. {len(changed)} changed, outside session records: "
      + (", ".join(p for p in changed if not RECORDS.match(p)) or "none"))
for line in bad:
    print(f"GAP: outside the new HOME, ~/{line.replace(marker, 'oc-first-run.*')}")  # the same text on each run
PY
}

# The new user's existing repo and board: plain issues, GitHub's own default columns, no Size and no Priority.
sandbox() {
  if ! newuser gh api "repos/$SLUG" >/dev/null 2>&1; then
    newuser gh repo create "$SLUG" --private --add-readme --description "Sandbox for OliverCode's first-run check" || return 1
  fi
  local titles title have number urls
  # shortcut: an issue a drain left open keeps its card and comments, reset those when a run first parks one.
  have="$(newuser gh api "repos/$SLUG/issues?state=open&per_page=100" --jq '.[].title')" || return 1
  titles=("Add a greeting to the README" "The app is slow sometimes" "Dark mode?")
  for title in "${titles[@]}"; do
    grep -qxF "$title" <<<"$have" || newuser gh api "repos/$SLUG/issues" -f title="$title" --silent || return 1
  done
  number="$(newuser gh project list --owner "$OWNER" --limit 100 --format json --jq ".projects[] | select(.title == \"$NAME\") | .number")" || return 1
  if [ -z "$number" ]; then
    number="$(newuser gh project create --owner "$OWNER" --title "$NAME" --format json --jq .number)" || return 1
    newuser gh project link "$number" --owner "$OWNER" --repo "$SLUG" || return 1
  fi
  have="$(newuser gh project item-list "$number" --owner "$OWNER" --format json --jq '.items[].content.url')" || return 1
  urls="$(newuser gh api "repos/$SLUG/issues?state=open&per_page=100" --jq '.[].html_url')" || return 1
  for title in $urls; do
    grep -qxF "$title" <<<"$have" || newuser gh project item-add "$number" --owner "$OWNER" --url "$title" >/dev/null || return 1
  done
}

listing save || die "the before listing failed"

OC="$H/Developer/Repos/OliverCode"
echo "=== clone $BRANCH into the new HOME ==="
newuser git clone -q -b "$BRANCH" "$OC_URL" "$OC" || die "the clone of $BRANCH failed"
newuser git -C "$OC" log -1 --format='cloned %h %s'

echo "=== python3 scripts/olivercode install ==="
(cd "$OC" && newuser python3 scripts/olivercode install) > "$WORK/install.log" 2>&1
code=$?
cat "$WORK/install.log"
INSTALL_PY=scripts/lib/cmd_install.py
DRAIN_PY=scripts/lib/cmd_drain.py
[ "$code" -eq 0 ] || gap "$INSTALL_PY" "install exited $code"
# The steps only a new user can take, each as `pattern=step`. The pattern is searched in install's output.
for pair in 'gh auth login=sign in to GitHub (gh auth login)' \
            'refresh -s project=give gh the project scope (gh auth refresh -s project)' \
            'sign(ed)? in.*claude|claude.*sign(ed)? in=sign in to Claude Code (claude)' \
            'user\.(name|email)=set the git name and email (git config --global user.name)' \
            'autoMode=add the autoMode rules' \
            'backlog-setup=set up each board (olivercode backlog-setup DIR --apply)' \
            'new (terminal|shell)=open a new terminal for the olivercode command'; do
  grep -qiE -- "${pair%%=*}" "$WORK/install.log" || gap "$INSTALL_PY" "install never names this step: ${pair#*=}"
done

echo "=== the sandbox repo $SLUG ==="
newuser gh auth setup-git || die "gh could not set up git in the new HOME"  # what `gh auth login` does for a new user
sandbox || die "the sandbox repo or its board could not be made"
APP="$H/Developer/Repos/$NAME"
newuser git clone -q "https://github.com/$SLUG.git" "$APP" || die "the sandbox clone failed"
CLI="$H/.local/bin/olivercode"
[ -x "$CLI" ] || { gap "$INSTALL_PY" "install left no olivercode command in ~/.local/bin"; exit 1; }

echo "=== olivercode backlog-setup --apply ==="
newuser "$CLI" backlog-setup "$APP" --apply 2>&1 | tee "$WORK/setup.log"
code=${PIPESTATUS[0]}
[ "$code" -eq 0 ] || gap scripts/lib/backlog_setup.py "backlog-setup exited $code"

echo "=== olivercode drain ==="
newuser "$CLI" drain "$APP" 2>&1
code=$?
[ "$code" -eq 0 ] || gap "$DRAIN_PY" "drain exited $code"
# shortcut: no time limit on the wait, add one when a plain issue is seen to start a builder that hangs.
[ "$code" -ne 0 ] || newuser "$CLI" watch "$APP" --until-exit 2>&1 | tee "$WORK/watch.log"
while pgrep -f "$WORK/" >/dev/null; do sleep 1; done  # the drain writes its log and notification after the run-end row `watch` stops on
LOG="$H/.olivercode/logs/drain-$NAME.log"
echo "--- drain log ---"
cat "$LOG" 2>/dev/null || gap "$DRAIN_PY" "drain wrote no log"
echo "--- notifications ---"
cat "$WORK/notifications.log" 2>/dev/null
grep -q "^Drain done:" "$LOG" 2>/dev/null || gap "$DRAIN_PY" "the drain log has no 'Drain done' line"
grep -q "Traceback" "$LOG" 2>/dev/null && gap "$DRAIN_PY" "the drain log holds a Python traceback"
numbers="$(newuser gh api "repos/$SLUG/issues?state=open&per_page=100" --jq '.[].number')" || die "the sandbox issues could not be read"
for n in $numbers; do
  grep -qE "^((Skipped|Story) )?#$n(:| )" "$LOG" 2>/dev/null || gap "$DRAIN_PY" "the drain log says nothing about open issue #$n"
  grep -qE "#$n([^0-9]|$)" "$WORK/watch.log" "$WORK/notifications.log" 2>/dev/null ||
    gap "$DRAIN_PY, scripts/lib/cmd_status.py" "neither \`olivercode watch\` nor the notification says why open issue #$n was not built"
done

echo "=== nothing outside the new HOME ==="
listing compare > "$WORK/compare.log" || die "the after listing failed"
while IFS= read -r line; do  # one gap for each path that leaked
  case "$line" in
    "GAP: "*) gap "$INSTALL_PY" "${line#GAP: }" ;;
    *) echo "$line" ;;
  esac
done < "$WORK/compare.log"
exit 0  # finish makes it 1 when there is a gap
