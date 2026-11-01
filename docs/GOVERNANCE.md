# Workspace Governance

This document defines the current locked governance baseline for OliverCode.

## Unified Validation Entrypoint

`bash scripts/validate.sh` runs all active gates from repo root:
- `bash scripts/validate.sh` — pre-commit gates, doc/code consistency, reference integrity, tests
- `bash scripts/validate.sh --evidence <file>` — pre-commit + orchestration gatekeeper. `scripts/orchestration-gatekeeper.py` validates WRITE MODE evidence against repo profiles (`shared/repo-profiles.json`, tracked real fleet) and `shared/task-policies/`.
- `bash scripts/validate.sh --gatekeeper-only <file>` — gatekeeper only
- `bash scripts/validate.sh --check-consistency` — doc/code consistency only

The gatekeeper's `--check-token-policy` mode is already wired into the commit hook (Gate 8);
`--evidence <file>` runs the fuller check on demand, for WRITE MODE completion verification.

Fail-closed: any failed gate blocks the commit. There is no bypass mode.
(OliverCode ships `.github/workflows/framework-ci.yml` — health, validate.sh,
`check-bloat.sh --strict`, and the fork-usability check as gating steps on push/PR.

**The workflow is deliberately paused on the origin repo** while GitHub Actions billing is
blocked. That is policy, not drift: `githubActionsPolicy` in
`shared/project-bootstrap-manifest.json` is the canonical record, and the same pause applies
to managed repos. Do not re-enable it as a "fix" — it spends the owner's billing.

While it is paused, the local commands ARE the enforcement, which is why the fork-usability
and strict-bloat checks also run from `scripts/qa/full-qa-pass.sh` rather than living only in
CI. Enable the workflow in your own fork, where your billing applies. A separate
governance CI workflow template for downstream repos exists at
`core/templates/project/.github/workflows/olivercode-governance.yml`.)

`bash scripts/validate.sh` also reports fleet hook state on every run (advisory, never
fatal). Hook enforcement fails open, so a repo with an unset or broken `core.hooksPath` is
silently ungoverned. Surfacing it here puts the signal where agents already look rather than
in a weekly log. A repo that must diverge from the template declares `hookVariant` in its
profile -- see `shared/repo-profiles.json`.

`validate.sh` also fails closed on **unfalsifiable checks** — a gate or script that
cannot fail, whatever the input. See `GATE-FALSIFIABILITY-1` in `docs/DECISIONS.md` for the
defects that shape covered and why none was visible from the output. Detector:
`scripts/lib/falsifiability_check.py`.

It also fails closed on **hook drift**. OliverCode's hook, the public template and the
private template run the same gates, and each gate's body lives once in `core/hooks/gates/`.
`scripts/build-hooks.py` assembles the three hooks from one ordered gate list, and
`validate.sh` fails when a committed hook differs from the build.

Beyond the commit hook, `validate.sh` fails closed on two more classes that used to drift
silently: doc/code consistency (`scripts/lib/consistency_check.py` — skills index parity,
gate-count claims) and internal reference integrity (`scripts/link-check.sh` — markdown links
plus backtick repo paths).

It also fails closed on **skill efficiency** for this repo's own `skills/`
(`scripts/lib/skill_efficiency_check.py`, `GATE-SKILL-EFFICIENCY-1` in `docs/DECISIONS.md`).
A `SKILL.md` over the word cap with no `references/` split, a paragraph restated across
skills or inside one, and any of the six named MCP-call anti-patterns each fail the run.
`core/contracts/SKILL_EFFICIENCY_STANDARD.md` holds the rules and the module holds the
thresholds.

## Gate Classes

**Gate coverage is not uniform across repos, and the difference matters.** OliverCode runs
eleven gates on itself. A repo your fleet adopts runs nine, because two of the eleven
check things that only exist in the framework repo. A repo deployed with the private variant
runs four. This table is the one home for that. Anywhere else that names a count points here.

| Gate | What it blocks | OliverCode | Adopted repo | Private variant |
|------|---------------|:---:|:---:|:---:|
| Secrets | API keys, tokens, JWTs, private keys in staged files | 1 | 1 | 1 |
| Icons/Emoji | Unicode emoji and icon characters | 2 | 2 | 2 |
| PII | Host paths, email addresses, personal data | 3 | 3 | — |
| Deleted repo refs | References to removed repos — an opt-in extension point. `DELETED_REPO_PATTERNS` in the hook is empty by default and the gate reports *skipped*, not passed, until you add names | 4 | 4 | — |
| Workflow push auth | Staged `.github/workflows/` files without a workflow-scoped credential (checked via `gh api user -i`, not the remote URL scheme) | 5 | 5 | — |
| Contract integrity | Hardcoded `/workspace/` container paths in staged code. `OLIVERCODE_DEPENDENCY.md` declaring paths that don't exist | 6 | — | — |
| Planning doc governance | Contract violations in staged planning docs. Conditional: runs only where `scripts/check-planning-doc-governance.py` exists, and reports *skipped* where it does not | 7 | 6 | — |
| Token policy | Invalid token-policy declarations in repo profiles | 8 | — | — |
| Backlog hygiene | A `docs/BACKLOG.md` (or root `BACKLOG.md`) heading marked DONE instead of removed. Conditional: runs where `scripts/check-backlog-hygiene.mjs` exists and node is installed, and reports *skipped* where either is missing, or where no backlog file exists | 9 | 7 | — |
| Archived content | A staged path under a directory named `Archive`, `legacy`, `deprecated`, `outdated`, `backup`, or `old`, or a file suffixed `.bak`, `-old`, `-backup`, `-deprecated`, `-superseded`. Current-state-only, fleet-wide: git is the archive, so a superseded file is deleted or replaced, never parked | 10 | 8 | 3 |
| Writing clarity (asd-ste100) | Warns, never blocks: a staged `SKILL.md`, `CLAUDE.md` or `references/*.md` with strict-mode ASD-STE100 findings (semicolons, phrasal verbs, marketing adjectives, nominalization, long sentences, synonym rotation). Long sentences are measured after `core/templates/project/ste-lint-joined.py` (installed beside each hook) joins hard-wrapped lines, so wrapping a paragraph cannot hide one. Conditional: runs where `ste-lint.py` (a personal vendor install, `npx skills add danyuchn/asd-ste100-skill`) and `python3` are both found, and reports *skipped* where either is missing | 11 | 9 | 4 |
| **Total** | | **11** | **9** | **4** |

Numbers are the gate's position in that hook's run order, so the same gate can carry a
different number in different hooks — planning-doc governance is Gate 7 in OliverCode and
Gate 6 in an adopted repo. Read the column, not the number.

The last two rows are OliverCode-only by design, not by oversight. **Contract integrity** validates
`OLIVERCODE_DEPENDENCY.md` and the framework's own container-path rules. **Token policy**
validates `repo-profiles.json`, which only the framework repo holds. Neither has anything to
check in a product repo, so neither ships in the template.

Which hook a repo receives:

| Source | Deployed to | Selected by |
|---|---|---|
| `core/templates/project/pre-commit` | every fleet repo | the default for `olivercode sync-hooks` |
| `core/templates/project/pre-commit-private` | every repo in `privateRepos` in `olivercode.local.json`, plus any fleet repo whose profile sets `"private": true` | each declares itself, so `sync-hooks` maintains it like any other target |
| a repo's own hook | that repo | the profile declares `hookVariant: "<reason>"`, which makes `sync-hooks` skip it and `health` report WARN instead of FAIL |

The private variant drops the PII gate deliberately: a private repo holds personal data by design, so a gate
that blocks host paths and email addresses would block every legitimate commit in it. It is
deployed as a file literally named `pre-commit` — git auto-invokes that name and no other.
A repo adds its own blocking checks in a `pre-commit.local` file beside the hook (`GATE-LOCAL-1`). The private hook runs it after Gate 4. `sync-hooks` does not manage it.
Fleet repos also receive `pre-commit-private` alongside their live hook as an inert reference
copy. Git never runs it.

`hookVariant` carries a real cost, set out with the incident that proved it in
`_hookVariant_note` in `shared/repo-profiles.json`. `scripts/build-hooks.py` generates
OliverCode's own hook and the two templates and never a variant repo's hook. When a third
repo declares a variant, give `build-hooks.py` an entry for each variant repo, the template's
gate list plus that repo's own gates, so its hook is generated too.

## Locked Baseline Rules

- Active authority lives only in current-state docs and executable surfaces.
- Roadmaps/migrations/status-history are not active authority — see
  `core/contracts/FRAMEWORK_BASELINE.md` "Removal Rules".
- Project-specific automation and new-vs-merged docs — see `CONTRIBUTING.md`
  "Mandatory Rules" (2 and 5).
- The governance runner must stay small enough to understand in one read.

## Cross-Project Standardization

OliverCode is the source baseline for downstream repos.
The reusable baseline lives in:
- `core/contracts/FRAMEWORK_BASELINE.md`
- `core/templates/project/QUALITY_BASELINE.md`
- `shared/project-bootstrap-manifest.json`

Enforcement for downstream repos is handled by their own `.githooks/pre-commit` and their declared `canonicalValidationCommand` (in the registry's `repo-profiles.json`, private under `REGISTRY-PRIVATE-1`).

