#!/usr/bin/env python3
"""Claude Code PostToolUse hook (Edit|Write|MultiEdit): a floor-tier design tell in an edited UI file is reported to the session.

Runs skills/audit/scripts/design_check.py on the edited file and adds at most MAX_FINDINGS floor-tier rows as context.
Reflex tells are left to the audit. The hook never blocks: on any error or timeout the edit stands, with a note on stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "skills" / "audit" / "scripts"))
import design_check  # noqa: E402

MAX_FINDINGS = 10


def report(path: str) -> str:
    rows = [r for r in design_check.check_file(path) if r[2] == "floor"][:MAX_FINDINGS]
    if not rows:
        return ""
    lines = "\n".join(f"{path}:{line}  {rule}: {what}" for line, rule, _, what in rows)
    return f"Floor design tells in the file just edited (docs/DESIGN.md, never allowed):\n{lines}"


def main() -> int:
    path = (json.load(sys.stdin).get("tool_input") or {}).get("file_path") or ""
    text = report(path) if path else ""
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 -- never block an edit
        print(f"design_hook: skipped ({exc})", file=sys.stderr)
        raise SystemExit(0)
