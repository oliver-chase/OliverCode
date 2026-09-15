#!/bin/bash
# Unloads and removes the launchd agent. State/logs under
# ~/Library/Application Support/olivercode-scheduler are left in place --
# delete that folder by hand if you want a truly clean slate.
set -uo pipefail

PLIST_LABEL="com.olivercode.local-scheduler"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

if [ -f "$PLIST_PATH" ]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "Uninstalled ($PLIST_PATH removed)."
else
  echo "Not installed (no $PLIST_PATH)."
fi
