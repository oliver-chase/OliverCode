# Quality Baseline Standard

This repository is the **canonical framework repo** -- it defines the quality standards that all OliverCode projects follow.

## Source of Truth

All managed quality files originate here and are synced to consuming projects:

- `core/templates/project/.github/workflows/qa-hygiene.yml`
- `core/templates/project/.github/workflows/governance-secrets-gate.yml`
- `core/templates/project/.github/workflows/dependency-review.yml`
- `core/templates/project/.github/CODEOWNERS`
- `core/templates/project/.github/pull_request_template.md`
- `core/templates/project/QUALITY_BASELINE.md`
- `.githooks/pre-commit` -- Pre-commit gate runner
- `core/templates/project/scripts/` -- Template governance scripts

## Rule

If a managed quality file changes in any project, the canonical file in **this repo** must be changed first and then synced to all projects. OliverCode is the single source of truth.

## Framework-Level Quality Gates

Before committing:

1. `.githooks/pre-commit` -- the gate runner; `docs/GOVERNANCE.md` is the one home for the gate list
2. Follow `core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` + `core/contracts/EXECUTION_CONTRACT.md`
3. Doc standard: `docs/DOCUMENTATION_STANDARD.md` -- forward-only, current state
4. Public-repo redaction: `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md`

## Template Driven Design

All project repos derive their quality baseline from this repo's `core/templates/project/` directory. To update a quality standard across all projects:

1. Edit the canonical file here
2. Sync to downstream repos via the bootstrap manifest and their repo-specific bootstrap process
