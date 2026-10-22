# Project Structure and Hygiene Standard

Status: Active
Effective Date: 2026-05-01
Scope: All project repositories under `<vault-root>/Oliver/Project Repos/*`. Excludes
OliverCode's own root, the same carve-out `PUBLIC_PRIVATE_REPO_STANDARD.md` states and
explains. OliverCode's equivalent surfaces here are `docs/BACKLOG.md`, `docs/DECISIONS.md`,
and `core/workflows/`.

## Purpose

Define one locked folder/file contract for backlog, epics, user stories, and lifecycle
evidence, and the hygiene rules that govern how they get used, so every agent follows the
same read/write flow.

**Two backlog systems coexist in the fleet today, and this contract only governs one of
them.** A repo whose `CLAUDE.md` names a `backlog-config.json` uses the GitHub Project board
instead — `skills/backlog-management/SKILL.md` governs it, and nothing below applies there.
This file-based system governs every other repo. As of this decision, the GitHub Project
board is the default for a newly bootstrapped repo (`docs/DOCUMENTATION_STANDARD.md`'s
backlog policy states it); this contract stays in force, unchanged, for a repo that already
adopted it before that default was set.

## Core Invariants

1. Every repo has exactly one active backlog source.
2. Story registry and story artifacts are separate from the active backlog.
3. Story IDs are immutable and updated in place.
4. `_index.md` is the only allowed story index filename.
5. `backlog.md` is retired as an active planning filename.
6. Each repo must keep `docs/repo-structure-contract.md` current.
7. Every implementation change maps to an existing story or creates a new story first.
8. Every story includes `Epic`, `Status`, `Verified`, Acceptance Criteria, QA/Evidence, and a Test Plan (positive, negative, regression).
9. The same story ID filename must not exist in more than one artifact root.

## Required Base Paths (All Repos)

1. `README.md`
2. `CLAUDE.md` — the only agent-rules file. Claude Code is this framework's sole runtime, so there's no separate AGENTS.md to keep in sync
3. `docs/repo-structure-contract.md`
4. `.github/user-stories/README.md`
5. `.github/user-stories/_index.md`
6. `.github/user-stories/<project>/`

## Story Artifact Rules

1. Story files live under `.github/user-stories/<project>/` or a declared module artifact root.
2. Story filenames must use stable ticket IDs such as `US-*`, `SLD-*`, `SMK-*`.
3. Each story folder must include `_index.md`.
4. Root `.github/user-stories/` may contain only:
- `README.md`
- `_index.md`
- dated governance/audit files
- project folders

## Documentation Roles

1. Backlog doc: active queue (not archive).
2. Epics/story catalog doc: long-form story inventory and scope map.
3. Acceptance test matrix: AC-to-test evidence mapping.
4. Story files: execution-level acceptance criteria and evidence updates.
5. Index files: registry navigation and lifecycle visibility. They must not become the active backlog queue.
6. Module docs, backlog docs, and story files are updated in the same change when behavior/contracts change.
7. One canonical location per module/workstream — no duplicate story maps across docs.
8. Backlog root files must keep a current epic map and list unassigned-epic debt explicitly.
9. Public tracked docs use placeholders for service URLs, account emails, local usernames, device paths, and deployment identifiers unless the value is intentionally public product information.

## Epic and Commit Hygiene

1. Every commit maps to exactly one owning epic.
2. Commit message format: `<type>(epic-<name>): <summary>`.
3. Commit body must include `Tickets:` and `Scope:` lines.
4. Mixed-epic work must be split into separate commits.

## Test Hygiene

1. Every behavior change updates or adds automated tests in the correct lane (contract, regression, visual, integration).
2. Every story needs at least one negative-path assertion.
3. `Verified: true` is blocked unless fresh evidence is present in git.
4. Archived (not removed) features must retain non-regression tests for data/telemetry paths.

## Secret Hygiene

Where a secret, credential, or runtime artifact goes is `core/contracts/FILE_LOCATION_STANDARD.md`'s rule, not restated here. The story/backlog-specific addition: `.env.local` is the local holding area during rotation, and tracked examples show variable names and placeholders only.

## Discoverability

1. Provide one backlog root per module with quick commands for listing stories, epics, and unassigned entries.
2. Keep archive indexes for deferred functionality with clear re-enable instructions.
3. Define a single orchestration command named `qa:hygiene` in each repo's package scripts that runs all required story/epic/test hygiene gates for that repo.

## Shared Quality Baseline Hygiene

1. Managed files must stay byte-identical across all repos where they are marked strict in `shared/project-bootstrap-manifest.json`.
2. What the managed files are, and the change-canonical-first rule: `QUALITY_BASELINE.md`. How sync and drift audit run: `core/workflows/project-standardization-lifecycle.md`.

## Path Map

Each managed repo declares its own canonical backlog/story/index/evidence paths in its
`docs/repo-structure-contract.md`, following one of the Allowed Repo Profiles below. Use
those declared locations exactly. Do not create parallel backlog systems, and do not
hardcode per-repo paths here — the per-repo contract is the source of truth.

## Allowed Repo Profiles

### Profile A: Split Planning + Module Artifact Roots (split-root family)

1. Planning root:
- `.github/user-stories/<repo-name>/backlog/<module>/README.md`
2. Executable artifacts:
- `.github/<repo-name>/modules/<module>/*.md`
3. Contract file:
- `docs/repo-structure-contract.md` must explicitly state the split-root rule.

### Profile B: Docs-Backlog + Story Artifact Tree (docs-backlog family)

1. Active backlog file stays in docs (repo-defined path).
2. Story artifact root:
- `.github/user-stories/<project>/US-*.md`
3. Project story folder includes:
- `README.md`
- `_index.md`

## Agent Read Order

1. `README.md`
2. `CLAUDE.md`
3. `docs/repo-structure-contract.md`
4. active backlog file declared by the contract
5. `.github/user-stories/README.md`
6. `.github/user-stories/_index.md`
7. project story folder index and story files
8. acceptance test matrix file declared by the contract

## Story Path Flow

1. Intake or reprioritization updates the active backlog source only.
2. Execution updates the story artifact file (`US-*`) and keeps story ID stable.
3. Verification updates acceptance evidence (story file and matrix/execution doc when defined by profile).
4. Completion updates `_index.md` status and removes done items from active backlog queues.

## Enforcement

1. Run the repo's structure gate (`npm run check:structure` or `npm run check-stories`, depending on profile). It must fail when an artifact root validates zero stories where stories are expected, when a planning root contains executable story artifact files, or when a required index/contract file is missing.
2. `npm run qa:hygiene` in each repo.
3. Cross-repo structure drift: `core/workflows/project-standardization-lifecycle.md` ("Audit drift") has the procedure.
4. Contract drift in `docs/repo-structure-contract.md` is a blocker.
5. Pre-push: story linked with AC/evidence/test-plan complete, epic assignment explicit and correct, commit scope is one epic, tests added/updated with the relevant suite passing, docs/backlog/story metadata synchronized, and secret/privacy scans passing.
