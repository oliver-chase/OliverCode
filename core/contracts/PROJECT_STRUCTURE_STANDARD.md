# Project Structure Standard

Status: Active
Effective Date: 2026-05-01
Scope: All project repositories under `<vault-root>/Oliver/Project Repos/*`

## Purpose

Define one locked folder/file contract for backlog, epics, user stories, and lifecycle evidence so every agent follows the same read/write flow.

## Core Invariants

1. Every repo has exactly one active backlog source.
2. Story registry and story artifacts are separate from the active backlog.
3. Story IDs are immutable and updated in place.
4. `_index.md` is the only allowed story index filename.
5. `backlog.md` is retired as an active planning filename.
6. Each repo must keep `docs/repo-structure-contract.md` current.

## Required Base Paths (All Repos)

1. `README.md`
2. `CLAUDE.md` — the only agent-rules file; Claude Code is this framework's sole runtime, so there's no separate AGENTS.md to keep in sync
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
5. Index files: registry navigation and lifecycle visibility; they must not become the active backlog queue.

## Path Map

Each managed repo declares its own canonical backlog/story/index/evidence paths in its
`docs/repo-structure-contract.md`, following one of the Allowed Repo Profiles below. Use
those declared locations exactly; do not create parallel backlog systems, and do not
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

1. Run the repo's structure gate (`npm run check:structure` or `npm run check-stories`, depending on profile).
2. `npm run qa:hygiene` in each repo.
3. Cross-repo structure drift is audited manually against `shared/project-structure-rules.json` and the managed-file list in `shared/project-bootstrap-manifest.json`.
4. Contract drift in `docs/repo-structure-contract.md` is a blocker.
