# Workflow Standards

Workflow routing and standards.

## Authoritative References

- Shared orchestration core: `core/contracts/SHARED_ORCHESTRATION.md`
- Shared manifest: `core/contracts/AGENT_SYSTEM_MANIFEST.json`
- Project hygiene baseline: `core/contracts/PROJECT_HYGIENE_STANDARD.md`
- Project structure baseline: `core/contracts/PROJECT_STRUCTURE_STANDARD.md`

## Trigger Routing

Use these trigger terms as workflow selectors:

- `backlog` -> `core/workflows/backlog-workflow.md`
- `story lifecycle` -> `core/workflows/story-lifecycle-sop.md`
- `testing` -> `core/workflows/testing-rules.md`
- `qa` -> `core/workflows/qa-process.md`
- `full qa` -> `core/workflows/full-qa-audit.md`
- `OliverCode sync` -> `core/workflows/olivercode-sync.md`
- `project standardization` -> `core/workflows/project-standardization-lifecycle.md`

If a trigger term conflicts with active repo docs, surface the conflict before continuing.

## Repo Location

All product repos live under `<vault-root>/Oliver/Project Repos/`.

## Orchestration Rules

- Keep `.claude`, `.codex`, and `.agents` runtime state separate.
- Keep shared standards in one place (`<vault-root>/Oliver/Project Repos/OliverCode/shared/*`).
- Keep shared skills in one place (`<vault-root>/Oliver/Project Repos/OliverCode/skills/*`).
- Do not duplicate product workflow docs into runtime folders.
- Do not duplicate shared SOP/workflow files into project repos; reference canonical shared workflows instead.
- Treat live machine layout as source of truth over stale cached paths.

## Testing Baseline

Testing applies to all code work. Follow `core/workflows/testing-rules.md`.

## Branch Lifecycle Standard (All Projects)

- `development`: unstarted and in-progress story housing.
- `staging`: completed work that is ready for QA validation.
- `main`: production-ready promotions only.
- This lifecycle is mandatory across all project repos under `<vault-root>/Oliver/Project Repos/`.
- Change-one/change-all rule: if any repo lifecycle wording changes, update this file and the managed template files in the same governance cycle.

## Cross-Repo Quality Baseline

- Canonical managed quality files live in `shared/templates/project`.
- Sync all mapped repos: sync templates from `shared/templates/project/` via the project bootstrap manifest.
- Audit strict-file drift: pre-commit gates check for file structure violations in staged files.
- Policy: a managed-file change in one repo is invalid unless the canonical template is updated and re-synced to all repos.
