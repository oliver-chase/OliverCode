"""A standing push approval the owner recorded lets a blocked OliverCode push go through (#738).

The owner's words live in one decision record (`olivercode decisions record --decision standing-push-olivercode ... --by owner`).
When the safety system blocks such a push, `olivercode push-blocked` reads that record and names the one rule to allow, so nobody asks again. With no record the push stays blocked and the owner queue holds one line that asks once. The command changes no
settings file: adding the rule to `~/.claude/settings.json` stays with the installer's autoMode story and the owner.
"""

from __future__ import annotations

from pathlib import Path

from lib import cmd_owner, relay

DECISION = "standing-push-olivercode"
OC_ROOT = Path(__file__).resolve().parent.parent.parent
RULE = (f"In {OC_ROOT}, pushing validated commits to main with `git push origin HEAD:main`, "
        "which the pre-push gate has already checked")
ASK = "Standing approval: may OliverCode updates be pushed from this machine without asking each time? Record the answer with `olivercode decisions record`"
USAGE = "Usage: olivercode push-blocked --session SID"


def approval() -> dict | None:
    """The owner's complete, verified record for the standing push, or None when there is none. A record that names someone else as its author does not count."""
    try:
        rec = relay.verify(DECISION)
    except ValueError:
        return None
    if rec.get("by") != "owner" or not str(rec.get("words", "")).strip() or rec["choice"].lower() in ("no", "deny", "decline"):
        return None
    return rec


def ask_once(session: str) -> dict:
    """The one open owner-queue line that asks for the approval. A second call returns the line already open."""
    for item in cmd_owner.items():
        if item["status"] == "open" and item["step"] == ASK:
            return item
    return cmd_owner.add(session, ASK)


def handle_block(session: str) -> tuple[bool, str]:
    """(allowed, message) for a push the safety system blocked."""
    rec = approval()
    if rec:
        return True, (f"Standing approval on record, owner's words: {rec['words']!r}.\nAllow this one rule: {RULE}.\n"
                      "Do not ask the owner again. Add the rule through the installer's autoMode story, never by editing ~/.claude/settings.json.")
    item = ask_once(session)
    return False, f"No approval is recorded, so the push stays blocked. Owner queue #{item['id']} asks once: {ASK}."


def command_push_blocked(argv: list[str], out=print) -> int:
    if len(argv) != 2 or argv[0] != "--session" or not argv[1].strip():
        out(USAGE)
        return 1
    allowed, message = handle_block(argv[1])
    out(message)
    return 0 if allowed else 1
