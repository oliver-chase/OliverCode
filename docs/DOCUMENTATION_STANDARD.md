# Documentation Standard

Status: Mandatory
Enforcement: fail-closed via `.githooks/pre-commit` governance gates

Single authority for how OliverCode documentation is written, structured, and kept in
sync. (Consolidates the former current-state, README-writing, and feature-doc standards.)

## Requirement

Any behavior or contract change in `scripts/`, `skills/`, `core/personas/`, `shared/`, or
`core/contracts/` must update current-state documentation in the same change set:
- update `docs/FEATURE_MAP.md`
- update the human entrypoint docs affected

This is the one home for the doc-sync rule — `CONTRIBUTING.md`, `CLAUDE.md`, and
`docs/FEATURE_MAP.md` point here rather than restate it.

## Canonical Locations

- process authority: `CONTRIBUTING.md`
- baseline framework contract: `core/contracts/FRAMEWORK_BASELINE.md`
- gate policy: `docs/governance.md`
- capability map: `docs/FEATURE_MAP.md`
- launcher contract: `docs/OLIVERCODE_LAUNCHER.md`

## Documentation Rules

1. Current-state docs only. No speculative or stale capability claims in active authority docs.
2. One capability, one authority doc. Secondary docs point rather than restate.
3. If a change removes or merges scripts/docs/skills, update the human entrypoint docs in the same commit.
4. Generated reports and caches belong in ignored runtime-state locations, not tracked docs.
5. Commands are documented only if they are part of the active supported surface.

## Current-State Wording

Docs describe the system as it IS now — no history, no removal notes.
- Never use: "was previously", "was vendored", "has been removed", "used to be", "no longer", "prior to", "originally".
- If something was removed, it simply doesn't appear. If externally installed, say "Install:" — not "It was previously here."
- Git commit history (`git log`) is version history; no separate CHANGELOG file is required or maintained.

## Required Document Structures

### Root `README.md`
Must include, in any order: a scope/purpose statement, a Quick Start with runnable
commands, a Where Things Live table (directory -> what lives here -> what never goes here
-> benefit), and a Key Docs index. Section header wording may evolve; the four contents
above may not be dropped.

### `CONTRIBUTING.md`
`## Mandatory Rules` · `## Enforcement Reality` · `## Required Workflow` · `## Documentation Sync Requirement` · `## Source-of-Truth Documents` · `## Review Standard`

## Tone Contract (all authority docs)

- Evidence-first, neutral, directive wording. Describe constraints and failure modes explicitly.
- No hype language (`amazing`, `revolutionary`, `magic`).
- No second-person marketing voice, over-promissory phrasing, or multi-exclamation emphasis.
- No speculative claims.

## Required Gates

```bash
.githooks/pre-commit
```

Fail-closed. Eight gates in OliverCode: secrets, icons/emoji, PII, deleted-repo refs,
workflow push-auth, contract integrity, planning-doc governance, token policy. A repo that
adopts the framework gets six of them — `docs/governance.md` holds the coverage table.
