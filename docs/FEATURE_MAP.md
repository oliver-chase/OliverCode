# OliverCode Feature Map

Status: Active
Purpose: canonical index for the reduced OliverCode framework baseline and its source-of-truth documents.

## Governance and Quality

| Surface | Source of Truth | Enforcement |
|---|---|---|
| Contribution workflow | `CONTRIBUTING.md` | `.githooks/pre-commit` (8 gates) |
| Framework baseline lock | `core/contracts/FRAMEWORK_BASELINE.md` | `.githooks/pre-commit` Gate 6 (contract integrity) |
| Governance policy | `docs/governance.md` | `.githooks/pre-commit` |
| Token policy | `docs/TOKEN_POLICY.md` | `.githooks/pre-commit` Gate 8 |
| Documentation standard | `docs/DOCUMENTATION_STANDARD.md` | Manual (no active validator) |
| Framework smoke tests | `tests/` | `bash scripts/validate.sh` (WARN-skips if `tests/` absent) |
| Public CI | `.github/workflows/framework-ci.yml` | Runs health + validate.sh + link-check.sh + full-qa-pass.sh on push/PR |

## Runtime and Verification Baseline

| Surface | Source of Truth | Verification |
|---|---|---|
| Setup and orchestration runtime | `docs/OLIVERCODE_LAUNCHER.md` (the only launcher this repo ships: `scripts/olivercode` — `health`, `update`, `sync-hooks`, `skills`) | `scripts/olivercode --help` |

Claude Code is this framework's sole runtime and Anthropic its sole model provider — there is no multi-provider routing, multi-runtime adapter system, or separate "runtime launcher" beyond `scripts/olivercode`.

## Launcher Surface

| Surface | Source of Truth | Verification |
|---|---|---|
| Lightweight terminal launcher | `docs/OLIVERCODE_LAUNCHER.md`, `scripts/olivercode` | `scripts/olivercode --help` |

## Shared Framework Assets

| Inventory | Scope |
|---|---|
| `core/contracts/` | baseline contracts shipped from OliverCode |
| `core/templates/project/QUALITY_BASELINE.md` | downstream project quality template |
| `shared/project-bootstrap-manifest.json` | shared bootstrap manifest for downstream repos |
| `shared/repo-map.json` | cross-project repo registry |
| `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder) | per-repo validation commands and evidence requirements |
| `shared/task-policies/` | task-type policies, result schema, evidence template |

## Non-Drift Rule

A capability change is incomplete until this map and `docs/DOCUMENTATION_STANDARD.md` are updated in the same change set.

## Enforcement Surfaces Rule

Only list a script/gate here if it exists and runs (verify with `ls`/`grep` before adding a
row). The active enforcement surfaces are `.githooks/pre-commit` (8 gates) and, for
downstream repos, whatever `scripts/validate-repo.sh` they declare. Everything else is
manually verified.
