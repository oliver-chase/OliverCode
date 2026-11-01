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

The commit sequence, the gate list, doc voice, and public-repo redaction are each owned
elsewhere — `core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` + `core/contracts/EXECUTION_CONTRACT.md`,
`docs/GOVERNANCE.md`, `docs/VOICE.md`, `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md`
respectively — and are not restated here.
