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

1. `.githooks/pre-commit` -- 6 gates: secrets, emoji, PII, deleted repo refs, bootstrap structure, contract integrity
2. Follow EXECUTION_CONTRACT: CODE -> DOCS -> AUDIT -> QA -> GATE -> COMMIT -> PUSH
3. Doc standard: forward-only, current state -- never "previously/was removed/has been"
4. PUBLIC_REPO_PRIVACY: no project names, host paths, or personal data in public content

## Template Driven Design

All project repos derive their quality baseline from this repo's `core/templates/project/` directory. To update a quality standard across all projects:

1. Edit the canonical file here
2. Sync to downstream repos via the bootstrap manifest and their repo-specific bootstrap process

## Historical Note

Previous versions of this document referenced `scripts/run-governance-gates.sh`, `scripts/sync-project-hygiene.sh`, and `scripts/audit-project-hygiene.sh`. These scripts were never implemented. The active enforcement is the pre-commit hook at `.githooks/pre-commit`. Cross-project sync is handled through the shared template directory and repo-specific bootstrap manifests in `shared/project-bootstrap-manifest.json`.
