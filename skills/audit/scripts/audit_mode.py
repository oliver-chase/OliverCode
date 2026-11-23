#!/usr/bin/env python3
"""The audit mode, full or gated, stored as `auditMode` in olivercode.local.json.

Usage:
    audit_mode.py next [--report-only] [--fix]  # prints `action: skip|approve|run` (gated adds `reminder:`)
    audit_mode.py set full|gated         # stores the mode
    audit_mode.py                        # prints `mode: full|gated|unset`
The audit runs `next` once its report and issues are filed. `skip` ends the audit at the report, which is the default
when the mode is unset, `approve` asks once before the to-done phase and `run` starts it. `--fix` is "audit and fix".
Tests: python3 -m unittest test_audit_mode
"""

import sys

from _fleet import load_local, save_local

MODES = ("full", "gated")
REMINDER = "Full automation fixes everything with no prompt; switch with `python3 scripts/audit_mode.py set full`."


def get_mode():
    """"full", "gated" or None when no valid mode is stored."""
    value = load_local().get("auditMode")
    return value if value in MODES else None


def set_mode(mode):
    if mode not in MODES:
        raise ValueError(f"mode must be full or gated, got {mode!r}")
    save_local({"auditMode": mode})


def next_step(mode, report_only=False, fix=False):
    """(action, reminder) after the report: skip, approve or run. An unset mode stops at the report unless fix is set."""
    if report_only:
        return "skip", None
    if fix or mode == "full":
        return "run", None
    return ("approve", REMINDER) if mode == "gated" else ("skip", None)


def main(argv):
    if not argv:
        print(f"mode: {get_mode() or 'unset'}")
        return 0
    if argv[0] == "set" and len(argv) == 2 and argv[1] in MODES:
        set_mode(argv[1])
        print(f"mode: {argv[1]}")
        return 0
    if argv[0] == "next" and set(argv[1:]) <= {"--report-only", "--fix"}:
        action, reminder = next_step(get_mode(), "--report-only" in argv, "--fix" in argv)
        print(f"action: {action}")
        if reminder:
            print(f"reminder: {reminder}")
        return 0
    print(__doc__.split("Usage:")[1].split("The audit runs")[0].strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
