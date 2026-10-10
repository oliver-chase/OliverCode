"""Detect silent drift between the three pre-commit hooks.

OliverCode's own hook, the public template, and the private template each implement
the same gates. Nothing compared them, and they had drifted:

  Icons/Emoji  OliverCode printed a NO_ICONS_STANDARD.md path missing "Project Repos/"
  PII          OliverCode printed a FILE_LOCATION_STANDARD.md path missing BOTH
               "Project Repos/" and "core/" -- two errors in one pointer
  Gate 4       structurally different loops doing the same thing

Both broken pointers were in the message a developer sees at the moment they are
blocked, which is exactly when they go looking for the standard. Neither was
reachable by the reference checker: they live inside shell string literals and carry
a `<vault-root>` placeholder, so the backtick-path scan skips them by design.

This compares gate bodies across the hooks and fails on any difference that is not
explicitly declared below. The declaration is the point -- a difference someone chose
is fine; a difference nobody noticed is the bug.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

HOOKS = {
    "olivercode": Path(".githooks/pre-commit"),
    "template": Path("core/templates/project/pre-commit"),
    "template-private": Path("core/templates/project/pre-commit-private"),
}

GATE_BANNER = re.compile(r"# ─── (Gate \d+: [^─]+?)\s*─+\n")
# Trailing "[pre-commit] All ... gates passed." / bare exit 0 that closes the script.
EPILOGUE = re.compile(r'\s*(echo "\[pre-commit\] All .*gates passed\."|exit 0\s*$)')

# Differences that are deliberate. Each needs a reason: an undocumented entry here
# would recreate the exact blind spot this module exists to close.
DECLARED_DIFFERENCES = {
    "Secrets": (
        "The template carries a per-line allowlist for the Supabase anon-key meta tag "
        "(public by design, ships in client HTML). OliverCode has no such HTML and does "
        "not need the exemption."
    ),
    "Workflow push auth safety": (
        "Not a real difference: the template has no Gate 6 banner, so the planning-doc "
        "block that follows this gate is absorbed into it by the parser. OliverCode's "
        "copy has Gate 6 and Gate 8 after it. Structural artifact, not drift."
    ),
    "Writing clarity (asd-ste100)": (
        "Not a real difference: the private template ends with a Repo-local gates block "
        "after this gate, and the parser absorbs it into this gate. The gate itself matches "
        "in all three hooks. Structural artifact, not drift."
    ),
    "Backlog hygiene": (
        "Path only. An adopted repo receives the checker at scripts/; OliverCode is where "
        "that file is authored, under core/templates/project/scripts/, and keeping a second "
        "copy at scripts/ to make the two hooks read alike would mean maintaining the gate "
        "twice."
    ),
}


def _gate_bodies(path: Path) -> dict[str, str]:
    """Map gate title -> normalized body (comments, blank lines, banners stripped)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parts = GATE_BANNER.split(text)
    bodies: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        title = parts[i].split(":", 1)[1].strip()
        lines = []
        for line in parts[i + 1].splitlines():
            # The last gate in a file would otherwise absorb the script epilogue
            # ("All N gates passed" + exit 0), making an identical gate look drifted.
            if EPILOGUE.match(line):
                break
            if line.strip() and not line.lstrip().startswith("#") and "Gate " not in line:
                lines.append(line.rstrip())
        body = "\n".join(lines)
        bodies[title] = hashlib.sha1(body.encode()).hexdigest()
    return bodies


def check_hook_drift(repo_root: Path) -> list[str]:
    parsed = {name: _gate_bodies(repo_root / rel) for name, rel in HOOKS.items()}
    present = {n: b for n, b in parsed.items() if b}
    if len(present) < 2:
        return []  # a fork may not ship every variant; nothing to compare

    by_gate: dict[str, dict[str, str]] = {}
    for hook, gates in present.items():
        for title, digest in gates.items():
            by_gate.setdefault(title, {})[hook] = digest

    failures: list[str] = []
    for title, impls in sorted(by_gate.items()):
        if len(impls) < 2 or len(set(impls.values())) == 1:
            continue
        if title in DECLARED_DIFFERENCES:
            continue
        where = ", ".join(sorted(impls))
        failures.append(
            f"  [HOOK DRIFT] gate '{title}' differs between {where} and the difference is "
            f"not declared. Converge them, or add an entry with a reason to "
            f"DECLARED_DIFFERENCES in scripts/lib/hook_drift_check.py."
        )
    return failures


def check_all(repo_root: Path) -> list[str]:
    return check_hook_drift(repo_root)
