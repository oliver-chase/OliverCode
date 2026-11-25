"""Risk-proportional gate selection for ordinary builder rounds.

The release/landing path still runs every gate. This module only selects the
smallest deterministic gate set for a round, based on its changed paths.
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath


def round_gates(files: list[str]) -> list[str]:
    """Return ordered round gates. Precommit always runs; code tests run only for code changes."""
    order = ["precommit", "fleet", "bloat", "quality", "refs", "docs", "limits", "bypass", "smoke", "hookstate"]
    if not files:
        return order  # An unavailable/empty diff must fail safe to the full set, not silently skip tests.
    gates = ["precommit"]
    paths = [PurePosixPath(name) for name in files if name and not name.startswith("/")]
    if not paths:
        return order
    names = [p.as_posix() for p in paths]
    code = any(p.suffix in {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"} for p in paths)
    docs = any(name.startswith(("docs/", "README", "CHANGELOG")) for name in names)
    validation = any(
        name.startswith((".githooks/", "core/hooks/", ".github/workflows/"))
        or name in {"scripts/validate.sh", "scripts/build-hooks.py", "scripts/lib/validate_gates.py",
                    "scripts/lib/validation_scope.py", "scripts/lib/queue_bypass.py"}
        for name in names
    )
    fleet = any(name.startswith(("core/templates/project/", "shared/")) or
                name.endswith(("repo-profiles.json", "repo-profiles.yaml")) for name in names)
    limits = any(name.endswith("LIMITS.json") or name.endswith("LIMITS.md") for name in names)
    structural = any(name in {"pyproject.toml", "package.json", "package-lock.json", "uv.lock"} for name in names)
    # These paths govern work ownership, persistence, concurrency, recovery, or the validation
    # contract itself. A smoke-only round is not sufficient evidence for changes here.
    critical = any(
        name.startswith(("scripts/lib/claims", "scripts/lib/dispatch", "scripts/lib/agent_loop",
                         "scripts/lib/cmd_dispatch", "scripts/lib/cmd_drain", "scripts/lib/cmd_land",
                         "scripts/lib/validate_queue", "scripts/lib/validation_scope"))
        or name in {"scripts/validate.sh", "scripts/lib/validate_gates.py"}
        or name.startswith(("scripts/hooks/", ".githooks/", "core/hooks/"))
        for name in names
    )

    if critical:
        return order  # State/ownership/recovery/validation changes retain the full gate set.

    if code:
        gates.extend(["smoke", "quality"])
    if docs:
        gates.extend(["docs", "refs"])
    if validation:
        gates.extend(["bypass", "hookstate"])
    if fleet:
        gates.append("fleet")
    if limits:
        gates.append("limits")
    if structural:
        gates.extend(["bloat", "quality"])
    # Preserve the canonical full-gate order and avoid duplicates.
    order = ["precommit", "fleet", "bloat", "quality", "refs", "docs", "limits", "bypass", "smoke", "hookstate"]
    selected = set(gates)
    return [name for name in order if name in selected]


if __name__ == "__main__":
    for gate in round_gates(sys.argv[1:]):
        print(gate)
