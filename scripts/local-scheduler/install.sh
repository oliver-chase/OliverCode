#!/bin/bash
# ─── OliverCode local scheduler — install ────────────────────────────────────
#
# One command: `bash scripts/local-scheduler/install.sh` from inside this
# checkout. See tick.py's header for why launchd runs python directly.
#
# Registers a launchd agent running tick.py every 15 minutes, plus once on
# load (also covers "the Mac just woke up"). tick.py decides what is due --
# push-fleet and audit-fleet each run on their own interval, checked against
# marker files, not fixed launchd schedules. A second scheduling mechanism
# (a crontab entry, say) running the same jobs would have no lock against this
# one, so this is the only scheduler.
#
# Every path below resolves fresh at install time -- nothing hardcoded to one
# machine.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLIST_LABEL="com.olivercode.local-scheduler"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
STATE_DIR="$HOME/Library/Application Support/olivercode-scheduler"

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: 'python3' not found on PATH." >&2
  exit 1
fi

mkdir -p "$STATE_DIR/logs"
chmod +x "$SCRIPT_DIR"/*.py "$SCRIPT_DIR"/*.sh

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SCRIPT_DIR/tick.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$OC_ROOT</string>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$STATE_DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$STATE_DIR/logs/launchd.err.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
PLIST

# Idempotent: unload first (ignore "not loaded" error), then load fresh --
# safe to re-run this script any time.
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"

echo ""
echo "Installed. tick.py will run every 15 minutes, plus immediately now."
echo "push-fleet and audit-fleet each run on their own interval inside it --"
echo "see tick.py's JOBS list for the exact cadence."
echo ""
echo "Repo:   $OC_ROOT"
echo "Python: $PYTHON_BIN"
echo "Plist:  $PLIST_PATH"
echo "Logs:   $STATE_DIR/logs/scheduler.log (combined), plus one file per job"
echo ""
echo "Check it's running:  launchctl list | grep olivercode"
echo "Watch it live:       tail -f \"$STATE_DIR/logs/scheduler.log\""
echo "Force a tick now:    \"$PYTHON_BIN\" \"$SCRIPT_DIR/tick.py\""
echo "Uninstall:           bash \"$SCRIPT_DIR/uninstall.sh\""
