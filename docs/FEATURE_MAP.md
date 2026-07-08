# OliverCode Feature Map

Status: Active
Purpose: canonical index for the reduced OliverCode framework baseline and its source-of-truth documents.

## Governance and Quality

| Surface | Source of Truth | Enforcement |
|---|---|---|
| Contribution workflow | `CONTRIBUTING.md` | `.githooks/pre-commit` |
| Framework baseline lock | `core/contracts/FRAMEWORK_BASELINE.md` | `.githooks/pre-commit` (contract integrity gate) |
| Governance policy | `docs/governance.md` | `.githooks/pre-commit` |
| Documentation standard | `docs/DOCUMENTATION_STANDARD.md` | Manual (no active validator) |

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

## Historical Note

Previous versions of this map listed phantom validators (validate-framework-baseline.sh, validate-feature-coverage.sh, validate-doc-governance.sh, validate-provider-readiness-contract.sh, check_agent_file_parity.py) in the enforcement and verification columns. These scripts were never implemented. The active enforcement is the pre-commit hook. All other surfaces are manually verified or refer to the runtime launcher.
