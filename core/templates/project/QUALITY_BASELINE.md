# Quality Baseline Standard

This repository uses **shared, strict-managed quality files**.

Canonical source-of-truth (outside project docs):
- `<vault-root>/Oliver/Project Repos/OliverCode/shared/templates/project/.github/workflows/qa-hygiene.yml`
- `<vault-root>/Oliver/Project Repos/OliverCode/shared/templates/project/.github/workflows/governance-secrets-gate.yml`
- `<vault-root>/Oliver/Project Repos/OliverCode/shared/templates/project/.github/workflows/dependency-review.yml`
- `<vault-root>/Oliver/Project Repos/OliverCode/shared/templates/project/.github/CODEOWNERS`
- `<vault-root>/Oliver/Project Repos/OliverCode/shared/templates/project/.github/pull_request_template.md`
- `<vault-root>/Oliver/Project Repos/OliverCode/core/templates/project/QUALITY_BASELINE.md`
- `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/FRAMEWORK_BASELINE.md`

## Rule

If one managed quality file changes in any project, the canonical file in `OliverCode` must be changed first and then synced to all projects. Runtime-minimal baseline lock is mandatory across managed repos; local divergence is not the default path.

## Sync Command

```bash
.githooks/pre-commit
```

## Audit Command

```bash
.githooks/pre-commit
```

Pre-commit gates must pass before merging quality/workflow policy edits.

## Lock Enforcement

Managed repos must keep these shared enforcement surfaces wired exactly as shipped:
- `QUALITY_BASELINE.md` from the shared template
- `.githooks/pre-commit` and `.githooks/pre-commit-private` from shared templates
- `git config core.hooksPath .githooks`
- workflow/template assets rendered from `shared/project-bootstrap-manifest.json`

After changing any baseline surface, run sync then audit before merge.
