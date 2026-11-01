# Project structure and hygiene standard

Status: Active
Effective Date: 2026-05-01
Scope: All project repositories under `<fleet-root>/*`. Excludes
OliverCode's own root for Epic/Commit Hygiene and Required Base Paths — the same carve-out
`PUBLIC_PRIVATE_REPO_STANDARD.md` states and explains, since OliverCode is a framework, not a
product repo with epics. The GitHub Project backlog model below applies to OliverCode too:
its open work lives in the `OliverCode` GitHub Project, named in its own `docs/backlog-config.json`.
`docs/DECISIONS.md` holds decision rationale, and `docs/BACKLOG.md` holds only the live
tracker.

## Purpose

Define the hygiene rules every repo's backlog, commits, and tests follow, regardless of
which backlog paradigm the repo uses, so every agent follows the same read/write flow.

Every repo's backlog lives in a GitHub Project named by a `backlog-config.json` the repo's
own `CLAUDE.md` points to — `skills/backlog/SKILL.md` governs it. No repo keeps a
file-based story registry under .github.

## Core invariants

1. Every repo has exactly one active backlog source.
2. Each repo must keep `docs/repo-structure-contract.md` current.

## Epic and commit hygiene

1. Every commit maps to exactly one owning epic.
2. Commit message format: `<type>(epic-<name>): <summary>`.
3. Commit body must include `Tickets:` and `Scope:` lines.
4. Mixed-epic work must be split into separate commits.

## Test hygiene

1. Every behavior change updates or adds automated tests in the correct lane (contract, regression, visual, integration).
2. Every story needs at least one negative-path assertion.
3. `Verified: true` is blocked unless fresh evidence is present in git.
4. Archived (not removed) features must retain non-regression tests for data/telemetry paths.

## Secret hygiene

Where a secret, credential, or runtime artifact goes is `core/contracts/FILE_LOCATION_STANDARD.md`'s rule, not restated here. `.env.local` is the local holding area during rotation, and tracked examples show variable names and placeholders only.

## Discoverability

1. Each repo's GitHub Project is the one place to list open stories, epics, and unassigned entries — the `backlog` skill's sweep covers this.
2. Keep archive indexes for deferred functionality with clear re-enable instructions.

## Shared quality baseline hygiene

1. Managed files must stay byte-identical across all repos where they are marked strict in `shared/project-bootstrap-manifest.json`.
2. What the managed files are, and the change-canonical-first rule: `QUALITY_BASELINE.md`.

## Required base paths (all repos)

1. `README.md`
2. `CLAUDE.md` — the only agent-rules file. Claude Code is this framework's sole runtime, so there's no separate AGENTS.md to keep in sync
3. `docs/repo-structure-contract.md`
4. A `backlog-config.json` file under `docs/` — names the repo's GitHub Project

## Agent read order

1. `README.md`
2. `CLAUDE.md`
3. `docs/repo-structure-contract.md`
4. The repo's GitHub Project (named in its `backlog-config.json`, under `docs/`)

## Enforcement

1. `npm run qa:hygiene` in each repo.
2. Contract drift in `docs/repo-structure-contract.md` is a blocker.
3. Pre-push: epic assignment explicit and correct, commit scope is one epic, tests added/updated with the relevant suite passing, docs/backlog metadata synchronized, and secret/privacy scans passing.
