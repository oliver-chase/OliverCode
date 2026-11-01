# OliverCode Feature Map

Status: Active
Purpose: canonical index of every capability this framework ships, and the one doc that owns
each. If a capability exists and is not listed here, this map is wrong.

Scope, so the claim above is checkable rather than aspirational: every user-invocable script
under `scripts/` appears by name. Pure internal helpers (`scripts/lib/repo_profiles.py`,
`scripts/lib/token_policy.py`, `scripts/lib/local_config.py` — data loaders with no entry point) do not, and skills are
catalogued once in `skills/INDEX.md` rather than duplicated here. `scripts/lib/`'s gate
modules ARE listed, because each is a distinct enforcement capability.
`bash scripts/validate.sh` fails if a user-invocable script is missing from this file.

## Governance and Quality

| Surface | Source of Truth | Enforcement |
|---|---|---|
| Contribution workflow | `CONTRIBUTING.md` | `.githooks/pre-commit` |
| Framework baseline lock | `core/contracts/FRAMEWORK_BASELINE.md` | `.githooks/pre-commit` Gate 6 (contract integrity) |
| Governance policy and the gate list | `docs/GOVERNANCE.md` | `.githooks/pre-commit` |
| Execution order (CODE -> ... -> PUSH) and the WRITE MODE completion gate | `core/contracts/EXECUTION_CONTRACT.md` | `scripts/orchestration-gatekeeper.py --evidence-file` (on demand) |
| Token policy | `docs/TOKEN-POLICY.md` | `.githooks/pre-commit` Gate 8 |
| Public / local / private-overlay split every adopted repo must keep | `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md` | `.githooks/pre-commit` Gates 1 and 3 block the leak. The split itself is agent-applied at adoption |
| Documentation standard (locked README outline, naming, About) | `docs/DOCUMENTATION-STANDARD.md` | `validate.sh` covers references/consistency/index. `olivercode health` checks the GitHub About. How the words sound lives in `docs/VOICE.md` |
| Fork onboarding / adoption | `docs/ADOPTING.md` + the `olivercode-adoption` skill | `bash scripts/validate.sh` on a clean clone |
| Third-party tools the posture assumes (none shipped, none required) | `docs/EXTERNAL-TOOLING.md` | Manual (nothing here depends on them) |
| Skill placement | `docs/SKILLS-PLACEMENT.md` | `scripts/olivercode health` (symlink + drift check) |
| Doc/code consistency (skills index parity, gate-count claims, hook gate integrity) | `scripts/lib/consistency_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Unfalsifiable checks (a gate that cannot fail) | `scripts/lib/falsifiability_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Hook drift (the three pre-commit hooks implementing the same gate differently) | `scripts/lib/hook_drift_check.py` | `bash scripts/validate.sh` (fail-closed). An undeclared difference fails. A deliberate one is declared with a reason |
| Cross-doc content duplication (the same rule restated near-verbatim in two tracked docs) | `scripts/lib/duplication_check.py` | `bash scripts/validate.sh` (fail-closed). A shared 15+ word passage fails unless it matches a declared canonical phrase |
| Gate coverage per repo type (OliverCode, an adopted repo, the private variant) | `docs/GOVERNANCE.md` coverage table | `scripts/lib/consistency_check.py` via `bash scripts/validate.sh` (fail-closed) |
| Internal reference integrity (markdown links + backtick repo paths) | `scripts/link-check.sh`, `scripts/lib/reference_check.py` | `bash scripts/validate.sh` (fail-closed) |
| Framework tests | `tests/` | `bash scripts/validate.sh` (WARN-skips if `tests/` absent) |
| Public CI | `.github/workflows/framework-ci.yml` | Ships health + validate.sh + `check-bloat.sh --strict` + fork-usability as gating steps. Paused on the origin repo — see `docs/GOVERNANCE.md`'s "Unified Validation Entrypoint" for why. Enable it in your own fork. |

## Runtime and Launcher

| Surface | Source of Truth | Verification |
|---|---|---|
| Terminal launcher — `bootstrap`, `discover`, `install`, `health`, `update`, `sync-hooks`, `audit-fleet`, `push-fleet`, `skills` | `docs/OLIVERCODE-LAUNCHER.md`, `scripts/olivercode` | `scripts/olivercode --help` |
| Local scheduler — unattended `audit-fleet`/`push-fleet` via `launchd`, mirroring a fleet product repo's own proven pattern | `scripts/local-scheduler/README.md`, `scripts/local-scheduler/install.sh`, `scripts/local-scheduler/tick.py`, `scripts/local-scheduler/uninstall.sh` | `bash scripts/local-scheduler/install.sh`, then `launchctl list \| grep olivercode` |

Claude Code is this framework's sole runtime and Anthropic its sole model provider — there is
no multi-provider routing, multi-runtime adapter system, or launcher beyond `scripts/olivercode`.

## Scripts

| Script | What it does |
|---|---|
| `scripts/validate.sh` | Unified validation entrypoint: pre-commit gates, doc/code consistency, reference integrity, tests, gatekeeper modes |
| `scripts/lib/consistency_check.py` | Skills INDEX-vs-directory parity, frontmatter name match, gate-count claims across docs, and hook gate-integrity (a removed gate is caught) |
| `scripts/lib/reference_check.py` | Backtick repo-path resolution (the half a markdown link checker cannot see) |
| `scripts/lib/health_checks.py` | Governance-waiver expiry (an exception with no reason or a lapsed date fails health) and the GitHub About check (WARN-degrades offline). Launcher re-exports both |
| `scripts/lib/skills_catalog.py` | SKILL.md frontmatter parsing behind `olivercode skills`. Launcher re-exports |
| `scripts/lib/falsifiability_check.py` | Detects checks that CANNOT fail — dead counters, scripts reporting failure with no nonzero exit. Built after a run of defects here shared that one shape (`GATE-FALSIFIABILITY-1`) |
| `scripts/lib/duplication_check.py` | Detects the same rule restated near-verbatim across two tracked docs with no cross-reference — a sliding-window substring match, declared-marker exceptions for deliberate reuse |
| `scripts/orchestration-gatekeeper.py` | WRITE MODE evidence validation. `--check-token-policy` is Gate 8 |
| `scripts/audit-staleness.py` | Flags fleet repos past the review threshold, read from each repo's "Reviewed through" marker |
| `scripts/find-spec.py` | Resolves a bare backlog ID (`SPEC-21`) fleet-wide across every `*BACKLOG*.md` in the private repos and profiled fleet repos. A `SPEC-N` miss points at the GitHub Project where a retired backlog's entries may now live |
| `scripts/link-check.sh` | Internal reference integrity: markdown links plus backtick repo paths |
| `scripts/qa/check-code-quality.sh` | Oversized files, per-module test coverage, Python syntax. TypeScript-leaning, aimed at the fleet repos |
| `scripts/qa/check-bloat.sh` | Archive dirs, docs-to-code ratio, self-marked-historical files. `--strict` exits nonzero |
| `scripts/qa/check-fork-usable.sh` | Proves a fresh clone's commands run without crashing AND that the documented adoption path produces a fleet whose gates actually block, in a sandbox with a virgin HOME |
| `scripts/qa/probe-secret-gate.sh` | Writes a fake secret into the current repo, commits, and confirms Gate 1 blocks it. The one home for the probe `docs/ADOPTING.md`, `docs/NEW-MACHINE.md`, and `olivercode-adoption` all invoke by name |
| `scripts/qa/check-scenarios.sh` | The exhaustive complement to the fork check: sandboxed setup/walkthrough scenarios (existing ~/.claude, scattered fleet, --root, discover, bootstrap, hookVariant, backout, idempotency, update, no-commit probe). Run after changing the launcher, hooks, or `docs/ADOPTING.md` |
| `scripts/qa/full-qa-pass.sh` | Code quality, docs cohesion, bloat — plus fork usability when run against OliverCode itself |
| `scripts/run-governance-target.sh` | CI entrypoint that points the QA stack at a downstream repo |
| `scripts/hooks/early-stop-guard.py` | Claude Code `Stop` hook (`EARLY-STOP-1`). What it does: `core/contracts/EXECUTION_CONTRACT.md` "Session Hooks" |
| `scripts/hooks/session_check.py` | Claude Code `SessionStart` hook. What it does: `core/contracts/EXECUTION_CONTRACT.md` "Session Hooks" |
| `scripts/hooks/commit_guard.py` | Claude Code `PreToolUse` hook on Bash. What it does: `core/contracts/EXECUTION_CONTRACT.md` "Session Hooks" |
| `scripts/lib/claude_settings.py` | Merges OliverCode's three hook entries into `~/.claude/settings.json` and leaves every other key alone. `olivercode install` writes them and `olivercode health` checks them |
| `scripts/lib/repo_gates.py` | Whether git will run a repo's commit gates. Shared by the session check and the commit guard |

## Shared Framework Assets

| Inventory | Scope |
|---|---|
| `core/contracts/` | baseline contracts shipped from OliverCode |
| `core/workflows/` | repeatable cross-repo procedures |
| `core/templates/project/` | the single template home stamped into new repos |
| `skills/` | engineering-method and framework-tooling skills. `skills/INDEX.md` is the catalog |
| `shared/project-bootstrap-manifest.json` | managed-file list and strictness for downstream repos |
| `shared/workflow-standards.md` | trigger routing, branch lifecycle, testing baseline |
| `shared/repo-map.json` | cross-project repo registry |
| `shared/repo-profiles.json` (tracked, real fleet) | per-repo validation commands and evidence requirements |
| `shared/task-policies/` | task-type policies and result schema |
| `docs/KEEPALIVE-STANDARD.md` | Supabase/Cloudflare keepalive contract. Its four template files sync via the manifest's `conditionalFiles`, gated on each repo's `keepalive` profile block |

## Non-Drift Rule

A capability change is incomplete until this map is updated in the same change set.

## Enforcement Surfaces Rule

Only list a script/gate here if it exists and runs (verify with `ls`/`grep` before adding a
row). The active enforcement surfaces are `.githooks/pre-commit` and, for downstream repos,
whatever `scripts/validate-repo.sh` they declare (`scripts/validate.sh --target-repo` execs it
if present, per `D2` in `docs/DECISIONS.md`). Everything else is manually verified.
