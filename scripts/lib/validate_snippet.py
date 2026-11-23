"""Keep the validation-queue block in a repo's own scripts/validate.sh (#548).

The block lives once, in core/templates/project/scripts/validate-queue.snippet.sh, and the template validate.sh holds the
same text. A repo that already has its own validate.sh (the manifest copies the template in presence mode) gets the block
inserted, so a script such as land.sh that calls validate.sh directly still takes a queue slot.
"""

from __future__ import annotations

import re
from pathlib import Path

SNIPPET = Path("core/templates/project/scripts/validate-queue.snippet.sh")
MARKER = b"# managed:validate-queue"
_CD = re.compile(rb'^cd "\$REPO_ROOT"[ \t]*(?:#.*)?\r?\n?$')
_SET = re.compile(rb"^set[ \t]+-[A-Za-z]+(?:[ \t]+pipefail)?[ \t]*(?:#.*)?\r?\n?$")

ADDED, PRESENT, ABSENT, SKIPPED = "added", "present", "absent", "skipped"
NO_ANCHOR = 'it has no `cd "$REPO_ROOT"` line and no `set -euo pipefail` line to insert after'


def ensure_queue_snippet(oc_root: Path, repo: Path, dry_run: bool = False) -> tuple[str, str]:
    """Insert the queue block into repo/scripts/validate.sh when it lacks it, and return (status, detail).

    Status is `added`, `present` (the marker is already there), `absent` (no validate.sh, left alone) or `skipped`
    (detail says why). The block goes after the `cd "$REPO_ROOT"` line, else after the `set -euo pipefail` line. Every
    other byte stays, the file keeps its mode, and a second run changes nothing."""
    script = repo / "scripts" / "validate.sh"
    if not script.is_file():
        return ABSENT, "no scripts/validate.sh"
    snippet_path = oc_root / SNIPPET
    if not snippet_path.is_file():
        return SKIPPED, f"{SNIPPET} is missing from this OliverCode checkout"
    data = script.read_bytes()
    if MARKER in data:
        return PRESENT, ""
    block = snippet_path.read_bytes()
    if not block.endswith(b"\n"):
        block += b"\n"
    lines = data.splitlines(keepends=True)
    for anchor in (_CD, _SET):
        at = next((i for i, line in enumerate(lines) if anchor.match(line)), None)
        if at is not None:
            break
    else:
        return SKIPPED, NO_ANCHOR
    head = lines[at] if lines[at].endswith(b"\n") else lines[at] + b"\n"
    tail = lines[at + 1:]
    after = b"\n" if tail and tail[0].strip() else b""
    if not dry_run:
        script.write_bytes(b"".join(lines[:at]) + head + b"\n" + block + after + b"".join(tail))
    return ADDED, ""


def report(name: str, status: str, detail: str, dry_run: bool = False) -> str | None:
    """The one line sync-hooks and bootstrap print about a repo, or None when nothing changed and nothing is wrong."""
    if status == ADDED:
        return f"  [OK] {name}: scripts/validate.sh {'would take' if dry_run else 'now takes'} a validation queue slot"
    if status == SKIPPED:
        return f"  [WARN] {name}: scripts/validate.sh left alone, {detail}"
    return None
