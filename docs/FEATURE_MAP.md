# OliverCode Feature Map

Status: Active
Purpose: canonical index of every capability this framework ships, and the one doc that owns
each. If a capability exists and is not listed here, this map is wrong.

Scope, so the claim above is checkable rather than aspirational: every user-invocable script
under `scripts/` appears by name. Pure internal helpers (`scripts/lib/repo_profiles.py`,
`scripts/lib/token_policy.py` — data loaders with no entry point) do not, and skills are
catalogued once in `skills/INDEX.md` rather than duplicated here. `scripts/lib/`'s gate
modules ARE listed, because each is a distinct enforcement capability.
`bash scripts/validate.sh` fails if a user-invocable script is missing from this file.

## Governance and Quality

| Surface | Source of Truth | Enforcement |
|---|---|---|
| Contribution workflow | `CONTRIBUTING.md` | `.githooks/pre-commit` |
| Framework baseline lock | `core/contracts/FRAMEWORK_BASELINE.md` | `.githooks/pre-commit` Gate 6 (contract integrity) |
| Governance policy and the gate list | `docs/governance.md` | `.githooks/pre-commit` |
| Execution order (CODE -> ... -> PUSH) and the WRITE MODE completion gate | `core/contracts/EXECUTION_CONTRACT.md` | `scripts/orchestration-gatekeeper.py --evidence-file` (on demand) |
| Token policy | `docs/TOKEN_POLICY.md` | `.githooks/pre-commit` Gate 8 |
| Documentation standard | `docs/DOCUMENTATION_STANDARD.md` | Manual (no active validator) |
| Fork onboarding / adoption | `docs/ADOPTING.md` + the `olivercode-adoption` skill | `bash scripts/validate.sh` on a clean clone |
| Third-party tools the posture assumes (none shipped, none required) | `docs/external-tooling.md` | Manual (nothing here depends on them) |
| Skill placement | `docs/skills-placement.md` | `scripts/olivercode health` (symlink + drift check) |
| Doc/code consistency (skills index parity, gate-count claims, hook gate integrity) | `scripts/lib/consistency_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Unfalsifiable checks (a gate that cannot fail) | `scripts/lib/falsifiability_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Hook drift (the three pre-commit hooks implementing the same gate differently) | `scripts/lib/hook_drift_check.py` | `bash scripts/validate.sh` (fail-closed). An undeclared difference fails; a deliberate one is declared with a reason |
| Gate coverage per repo type (8 in OliverCode, 6 in an adopted repo, 2 in the private variant) | `docs/governance.md` coverage table | `scripts/lib/consistency_check.py` via `bash scripts/validate.sh` (fail-closed) |
| Internal reference integrity (markdown links + backtick repo paths) | `scripts/link-check.sh`, `scripts/lib/reference_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Framework tests | `tests/` | `bash scripts/validate.sh` (WARN-skips if `tests/` absent) |
| Public CI | `.github/workflows/framework-ci.yml` | Ships health + validate.sh + `check-bloat.sh --strict` + fork-usability as gating steps. **Deliberately paused on the origin repo** while GitHub Actions billing is blocked — see `githubActionsPolicy` in `shared/project-bootstrap-manifest.json`, the canonical record. Enable it in your own fork. |

## Runtime and Launcher

| Surface | Source of Truth | Verification |
|---|---|---|
| Terminal launcher — `bootstrap`, `discover`, `install`, `init`, `health`, `update`, `sync-hooks`, `skills` | `docs/OLIVERCODE_LAUNCHER.md`, `scripts/olivercode` | `scripts/olivercode --help` |

Claude Code is this framework's sole runtime and Anthropic its sole model provider — there is
no multi-provider routing, multi-runtime adapter system, or launcher beyond `scripts/olivercode`.

## Scripts

| Script | What it does |
|---|---|
| `scripts/validate.sh` | Unified validation entrypoint: pre-commit gates, doc/code consistency, reference integrity, tests, gatekeeper modes |
| `scripts/lib/consistency_check.py` | Skills INDEX-vs-directory parity, frontmatter name match, gate-count claims across docs, and hook gate-integrity (a removed gate is caught) |
| `scripts/lib/reference_check.py` | Backtick repo-path resolution (the half a markdown link checker cannot see) |
| `scripts/lib/falsifiability_check.py` | Detects checks that CANNOT fail — dead counters, scripts reporting failure with no nonzero exit. Built after ten defects here shared that one shape |
| `scripts/orchestration-gatekeeper.py` | WRITE MODE evidence validation; `--check-token-policy` is Gate 8 |
| `scripts/apply-token-policy.py` | Filters a path list through a repo's `ignore_globs` |
| `scripts/audit-staleness.py` | Flags fleet repos past the review threshold, read from each repo's "Reviewed through" marker |
| `scripts/link-check.sh` | Internal reference integrity: markdown links plus backtick repo paths |
| `scripts/qa/check-code-quality.sh` | Oversized files, per-module test coverage, Python syntax; TypeScript-leaning, aimed at the fleet repos |
| `scripts/qa/check-docs-cohesion.sh` | Broken wiki-links and opt-in stale-domain references |
| `scripts/qa/check-bloat.sh` | Archive dirs, docs-to-code ratio, self-marked-historical files. `--strict` exits nonzero |
| `scripts/qa/check-fork-usable.sh` | Proves a stranger's clone works with no config AND that the documented adoption path produces a fleet whose gates actually block, in a sandbox with a virgin HOME |
| `scripts/qa/full-qa-pass.sh` | Code quality, docs cohesion, bloat — plus fork usability when run against OliverCode itself |
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
