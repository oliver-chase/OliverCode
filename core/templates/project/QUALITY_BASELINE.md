# Quality Baseline Standard

This repository uses **shared, strict-managed quality files**.

Canonical source-of-truth (outside project docs):
- `OliverCode/core/templates/project/.github/workflows/qa-hygiene.yml`
- `OliverCode/core/templates/project/.github/workflows/governance-secrets-gate.yml`
- `OliverCode/core/templates/project/.github/workflows/dependency-review.yml`
- `OliverCode/core/templates/project/.github/CODEOWNERS`
- `OliverCode/core/templates/project/.github/pull_request_template.md`
- `OliverCode/core/templates/project/QUALITY_BASELINE.md`
- `OliverCode/core/contracts/FRAMEWORK_BASELINE.md`

## Rule

If one managed quality file changes in any project, the canonical file in `OliverCode` must be changed first and then synced to all projects. Runtime-minimal baseline lock is mandatory across managed repos. Local divergence is not the default path.

## Sync Command

Run from OliverCode to deploy the current managed files and hooks to this repo:

```bash
scripts/olivercode sync-hooks
```

## Audit Command

Run from OliverCode to check this repo's hook state against the shipped template:

```bash
scripts/olivercode health
```

Pre-commit gates (`.githooks/pre-commit`) must also pass before merging quality/workflow
policy edits.

## Lock Enforcement

Managed repos must keep these shared enforcement surfaces wired exactly as shipped:
- `QUALITY_BASELINE.md` from the shared template
- `.githooks/pre-commit` and `.githooks/pre-commit-private` from shared templates
- `git config core.hooksPath .githooks`
- workflow/template assets rendered from `shared/project-bootstrap-manifest.json`

After changing any baseline surface, run sync then audit before merge.

## Documentation

Every README and document in this repo follows the framework's documentation standard —
the locked README outline, voice, CAPS-KEBAB file naming, complete doc table, open-only
backlog, same-commit sync, and a filled-in GitHub About. The standard is
`docs/DOCUMENTATION_STANDARD.md` in the framework checkout. The `writing-documentation`
skill applies it. Ask an agent for a README here and that is the shape it produces.
