# OliverCode Feature Map

Status: Active
Purpose: canonical index of every capability this framework ships, and the one doc that owns
each. If a capability exists and is not listed here, this map is wrong.

## Governance and Quality

| Surface | Source of Truth | Enforcement |
|---|---|---|
| Contribution workflow | `CONTRIBUTING.md` | `.githooks/pre-commit` |
| Framework baseline lock | `core/contracts/FRAMEWORK_BASELINE.md` | `.githooks/pre-commit` Gate 6 (contract integrity) |
| Governance policy and the gate list | `docs/governance.md` | `.githooks/pre-commit` |
| Execution order (CODE -> ... -> PUSH) and the WRITE MODE completion gate | `core/contracts/EXECUTION_CONTRACT.md` | `scripts/orchestration-gatekeeper.py --evidence-file` (on demand) |
| Token policy | `docs/TOKEN_POLICY.md` | `.githooks/pre-commit` Gate 8 |
| Documentation standard | `docs/DOCUMENTATION_STANDARD.md` | Manual (no active validator) |
| Skill placement | `docs/skills-placement.md` | `scripts/olivercode health` (symlink + drift check) |
| Doc/code consistency (skills index parity, gate-count claims) | `scripts/lib/consistency_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Internal reference integrity (markdown links + backtick repo paths) | `scripts/link-check.sh`, `scripts/lib/reference_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Framework tests | `tests/` | `bash scripts/validate.sh` (WARN-skips if `tests/` absent) |
| Public CI | `.github/workflows/framework-ci.yml` | health + validate.sh + `check-bloat.sh --strict` gate the build; full-qa-pass runs advisory |

## Runtime and Launcher

| Surface | Source of Truth | Verification |
|---|---|---|
| Terminal launcher — `health`, `update`, `sync-hooks`, `skills` | `docs/OLIVERCODE_LAUNCHER.md`, `scripts/olivercode` | `scripts/olivercode --help` |

Claude Code is this framework's sole runtime and Anthropic its sole model provider — there is
no multi-provider routing, multi-runtime adapter system, or launcher beyond `scripts/olivercode`.

## Scripts

| Script | What it does |
|---|---|
| `scripts/validate.sh` | Unified validation entrypoint: pre-commit gates, doc/code consistency, reference integrity, tests, gatekeeper modes |
| `scripts/lib/consistency_check.py` | Skills INDEX-vs-directory parity, frontmatter name match, gate-count claims across docs |
| `scripts/lib/reference_check.py` | Backtick repo-path resolution (the half a markdown link checker cannot see) |
| `scripts/orchestration-gatekeeper.py` | WRITE MODE evidence validation; `--check-token-policy` is Gate 8 |
| `scripts/apply-token-policy.py` | Filters a path list through a repo's `ignore_globs` |
| `scripts/audit-staleness.py` | Flags fleet repos past the review threshold, read from each repo's "Reviewed through" marker |
| `scripts/link-check.sh` | Internal reference integrity: markdown links plus backtick repo paths |
| `scripts/qa/full-qa-pass.sh` | Runs the three QA checkers: code quality, docs cohesion, bloat |
| `scripts/qa/run-on-repo.sh` | Runs full-qa-pass against the invoking repo, tees to `.qa-results/` |
| `scripts/run-governance-target.sh` | CI entrypoint that points the QA stack at a downstream repo |

## Shared Framework Assets

| Inventory | Scope |
|---|---|
| `core/contracts/` | baseline contracts shipped from OliverCode |
| `core/personas/oliver/` | the one orchestration persona |
| `core/workflows/` | repeatable cross-repo procedures |
| `core/templates/project/` | the single template home stamped into new repos |
| `skills/` | engineering-method and framework-tooling skills; `skills/INDEX.md` is the catalog |
| `shared/project-bootstrap-manifest.json` | managed-file list and strictness for downstream repos |
| `shared/workflow-standards.md` | trigger routing, branch lifecycle, testing baseline |
| `shared/repo-map.json` | cross-project repo registry |
| `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder) | per-repo validation commands and evidence requirements |
| `shared/task-policies/` | task-type policies and result schema |
| `docs/KEEPALIVE_STANDARD.md` | Supabase/Cloudflare keepalive contract; its four template files sync via the manifest's `conditionalFiles`, gated on each repo's `keepalive` profile block |

## Non-Drift Rule

A capability change is incomplete until this map and `docs/DOCUMENTATION_STANDARD.md` are
updated in the same change set.

## Enforcement Surfaces Rule

Only list a script/gate here if it exists and runs (verify with `ls`/`grep` before adding a
row). The active enforcement surfaces are `.githooks/pre-commit` and, for downstream repos,
whatever `scripts/validate-repo.sh` they declare. Everything else is manually verified.
