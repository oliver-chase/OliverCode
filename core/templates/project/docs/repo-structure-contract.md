# Repo Structure Contract

Status: Active

## Canonical Contract Sources

1. `OliverCode/core/contracts/PROJECT_STRUCTURE_STANDARD.md`

## Profile

This repo uses the GitHub Project backlog profile. Its backlog is the GitHub Project named
in `docs/backlog-config.json`, read and written by the `backlog-management` skill.

## Required Structure

1. Root docs:
- `README.md`
- `CLAUDE.md`
- `docs/repo-structure-contract.md`
2. Backlog:
- `docs/backlog-config.json` — the `backlog-management` skill's config for this repo's Project

## Backlog and Evidence Paths

1. Active backlog source: the GitHub Project named in `docs/backlog-config.json`
2. Story catalog source: the GitHub Project's issue list
3. Acceptance test matrix source: `N/A (each issue carries AC/test evidence directly)`

## Branch Lifecycle Contract

1. `development`: unstarted and in-progress story housing.
2. `staging`: completed work ready for QA validation.
3. `main`: production-ready promotions only.
4. Source-of-truth link: `OliverCode/shared/workflow-standards.md`.
5. Change-one/change-all:
- If this lifecycle changes in a project repo, update this template and re-sync managed repos in the same governance cycle.

## Enforcement

1. `npm run qa:hygiene`
