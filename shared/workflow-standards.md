# Workflow Standards

Workflow routing and standards.

## Authoritative References

- Shared structure contract and canonical path map: `core/contracts/AGENT_SHARED_STRUCTURE.md`
- Shared manifest (machine-readable mirror): `core/contracts/AGENT_SYSTEM_MANIFEST.json`
- Project hygiene baseline: `core/contracts/PROJECT_HYGIENE_STANDARD.md`
- Project structure baseline: `core/contracts/PROJECT_STRUCTURE_STANDARD.md`

## Trigger Routing

Use these trigger terms as workflow selectors. This list is the complete one; `core/workflows/README.md`
points here. `CLAUDE.md`'s Development Practice section carries a compressed copy of the
most-used rows (broken/failing/slow, multi-commit session ending) so they load every
session with no extra file read — that copy is deliberate, not drift; this table is where
a less-common trigger term resolves.

- `backlog`, `story lifecycle` -> `core/workflows/story-lifecycle-sop.md`
- `OliverCode sync` -> `core/workflows/olivercode-sync.md`
- `project standardization` -> `core/workflows/project-standardization-lifecycle.md`
- `broken`, `failing`, `slow` -> the `diagnosing-bugs` skill loop
- `qa`, `full qa` -> `scripts/qa/full-qa-pass.sh` (deterministic checkers), then the
  `functionality-audit` skill for whether the product actually works end to end
- `testing` -> the `tdd` skill
- `review` -> the `deep-review` skill (before closing a multi-commit session)

If a trigger term conflicts with active repo docs, surface the conflict before continuing.

## Repo Location

All product repos live under `<vault-root>/Oliver/Project Repos/`.

## Orchestration Rules

- Claude Code runtime state (`~/.claude`) is operational data, not framework source.
- Keep shared standards in one place (`<vault-root>/Oliver/Project Repos/OliverCode/shared/*`).
- Keep shared skills in one place (`<vault-root>/Oliver/Project Repos/OliverCode/skills/*`).
- Do not duplicate product workflow docs into runtime folders.
- Do not duplicate shared SOP/workflow files into project repos; reference canonical shared workflows instead.
- Treat live machine layout as source of truth over stale cached paths.

## Testing Baseline

Testing applies to all code work:

- Add or update tests for every behavior change; treat a stale or missing impacted test
  update as a failure, not a follow-up.
- Check downstream and adjacent tests for impact and update all of them.
- Strengthen weak coverage around changed paths, edge cases, and regressions.
- Implementation is not complete without test alignment, and a test-suite-only change still
  needs its own QA pass.

Method for building features test-first: the `tdd` skill.

## Branch Lifecycle Standard (All Projects)

- `development`: unstarted and in-progress story housing.
- `staging`: completed work that is ready for QA validation.
- `main`: production-ready promotions only.
- This lifecycle is mandatory across all project repos under `<vault-root>/Oliver/Project Repos/`.
- Change-one/change-all rule: if any repo lifecycle wording changes, update this file and the managed template files in the same governance cycle.

## Cross-Repo Quality Baseline

One home: `QUALITY_BASELINE.md` (what the managed files are and the change-canonical-first
rule) and `core/workflows/project-standardization-lifecycle.md` (how sync and drift audit
actually run).
