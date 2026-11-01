# Workflow Standards

Workflow routing and standards.

## Authoritative References

- Shared structure contract and canonical path map: `docs/FRAMEWORK-BOUNDARY.md`
- Project structure and hygiene baseline: `core/contracts/PROJECT_STRUCTURE_STANDARD.md`

## Trigger Routing

Use these trigger terms as workflow selectors. This list is the complete one for procedures
and scripts. `core/workflows/README.md` points here. `CLAUDE.md`'s Development practice
section owns the skill triggers (broken/failing/slow, multi-commit session ending, review).

- `backlog`, `story lifecycle` -> `core/workflows/story-lifecycle-sop.md`
- `project standardization` -> `core/workflows/project-standardization-lifecycle.md`
- `qa`, `full qa` -> `scripts/qa/full-qa-pass.sh` (deterministic checkers)

If a trigger term conflicts with active repo docs, surface the conflict before continuing.

## Repo Location

All product repos live under `<fleet-root>/`.

## Orchestration Rules

- Claude Code runtime state (`~/.claude`) is operational data, not framework source.
- Keep shared standards in one place (`OliverCode/shared/*`).
- Keep shared skills in one place (`OliverCode/skills/*`).
- Do not duplicate product workflow docs into runtime folders.
- Do not duplicate shared SOP/workflow files into project repos. Reference canonical shared workflows instead.
- Treat live machine layout as source of truth over stale cached paths.

## Testing Baseline

Testing applies to all code work:

- Add or update tests for every behavior change. Treat a stale or missing impacted test
  update as a failure, not a follow-up.
- Check downstream and adjacent tests for impact and update all of them.
- Strengthen weak coverage around changed paths, edge cases, and regressions.
- Implementation is not complete without test alignment, and a test-suite-only change still
  needs its own QA pass.

## Branches

Repos work on `main`. A repo that needs a development or staging branch names it, and what
moves through it, in its own `CLAUDE.md`.

## Cross-Repo Quality Baseline

One home: `QUALITY_BASELINE.md` (what the managed files are and the change-canonical-first
rule) and `core/workflows/project-standardization-lifecycle.md` (how sync and drift audit
actually run).
