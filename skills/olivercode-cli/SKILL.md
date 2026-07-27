---
name: olivercode-cli
description: "Use when modifying the OliverCode CLI launcher: command structure, help output, update reliability, self-locating path resolution, and launch-path validation. Load before any CLI change."
---

# OliverCode CLI Design

Canonical contract: `docs/OLIVERCODE_LAUNCHER.md`. Read that first — this skill adds design rationale and pitfalls on top of it.

## Current Surface

Two thin, delegating launchers, both self-locating from `__file__`/script path — no hardcoded vault/home paths, no external runtime dependency:

- **`runtime/control-plane/olivercode`** (bash shim) — resolves its own repo root two levels up, then `exec python3 "$OC_ROOT/scripts/olivercode" "$@"`.
- **`scripts/olivercode`** (the actual Python CLI) — resolves `OC_ROOT` from its own file location, two levels up.

Both run identically from cron, a container, or any working directory — nothing is hardcoded.

Four commands:
- `olivercode health` — checks `runtime/control-plane/OLIVERCODE_DEPENDENCY.md`'s declared paths resolve, checks core entrypoints exist, checks placement drift (SYS-2). Prints HEALTHY/DEGRADED with a pass/fail count.
- `olivercode update` — `git -C <OC_ROOT> pull`, then runs `sync-hooks` (below) so a pull always converges hooks too.
- `olivercode sync-hooks` — converges the pre-commit hook + `core.hooksPath` across every fleet repo and the vault (SYS-3). Also runs automatically at the end of `update`.
- `olivercode skills [--grep TERM]` — lists OliverCode's own orchestration skills under `skills/`, reading name/description directly from each `SKILL.md`'s frontmatter (never from `skills/INDEX.md`'s prose tables, which are for human browsing and can drift). `--grep` filters case-insensitively on name or description. Scoped to this repo only.

`--help`, `-h`, `help`, and no-args all print the same usage block and exit 0. Any other command prints an error + usage and exits 1.

The launcher invokes nothing outside this repo. Treat multi-environment routing as new design work.

## Core Principles

1. **Keep the command surface narrow.** One supported syntax per capability. Unknown commands print usage and fail non-zero.
2. **No claims without verification.** Any launcher change is incomplete until exercised end-to-end from a clean shell.
3. **Self-locating, always.** Every path derives from `__file__`/script location. Never hardcode a vault, home, or container path in a command handler.
4. **Fail fast with the concrete missing path.** If a dependency path or entrypoint is missing, print exactly what's missing and return non-zero — don't hide it behind a generic error.

## Known Fail Modes

### Health check reports a missing entrypoint or dependency path
- **Cause:** `runtime/control-plane/OLIVERCODE_DEPENDENCY.md` declares a repo-relative path that doesn't exist, or one of the three core entrypoint checks (`scripts/olivercode`, `runtime/control-plane/olivercode`, `docs/FRAMEWORK_BOUNDARY.md`) is missing.
- **Fix:** either restore the missing path or remove its declaration from `OLIVERCODE_DEPENDENCY.md` if it's genuinely no longer needed.

### `update` fails
- **Cause:** `git -C <OC_ROOT> pull` hit a conflict, detached HEAD, or no remote tracking branch.
- **Fix:** resolve the git state directly; the command has no retry/fallback logic by design (fail fast, not hidden).

### Help surface drift
- **Fix:** re-verify the alias set stated above (`--help`, `-h`, `help`, no-args) still all resolve to the same usage block with exit 0 — this is the fact most likely to silently break in a refactor.

## Verification Checklist

1. `python3 -m py_compile scripts/olivercode`
2. Run with no args — confirm usage/help prints cleanly, exit 0
3. Run invalid command — confirm error + usage, exit non-zero
4. `python3 scripts/olivercode health` — confirm HEALTHY on a clean checkout
5. Confirm `runtime/control-plane/olivercode` shim still delegates correctly (bash shim → same Python CLI)
6. Verify help aliases: bare, `--help`, `-h`, `help` all exit 0
7. `python3 scripts/olivercode skills` — confirm the count matches `find skills -name SKILL.md | wc -l` (everything under `skills/` is real, tracked content); `skills --grep <term>` — confirm it filters, `skills --grep` (no term) errors instead of matching everything
