# Contributing to OliverCode

This file is the contribution entry point for OliverCode framework changes.

## Locked Framework Rule

OliverCode is the baseline framework for all downstream project repos. Every change must
keep the framework small, current, and reusable. Every tracked file must justify itself as
exactly one of:

- **run** — launcher and orchestration entrypoints (`scripts/olivercode`)
- **verify** — gates that prove the framework works (`scripts/validate.sh`, `.githooks/`, `tests/`)
- **ship** — contracts and templates downstream repos inherit (`core/`, `shared/`)
- **support** — current-state docs explaining the active surface (`docs/`, root docs)

If a file does none of those, delete it, merge it, or move it to the repo that owns it.
`core/contracts/FRAMEWORK_BASELINE.md` "Purpose" is the contract; this is where you apply it.

## Mandatory Rules

1. Claude Code is OliverCode's sole runtime and Anthropic its sole model provider — do not reintroduce multi-runtime or multi-provider framing without a real implementation behind it.
2. Keep project-specific runtime logic in the owning project repo.
3. Documentation sync is required in the same change set — see `docs/DOCUMENTATION_STANDARD.md` "Always current — the sync rule" for what triggers it and what to update.
4. Run `bash scripts/validate.sh` before every commit.
5. New docs should replace or merge older docs instead of creating parallel authority.
6. No roadmap, migration, or status markdown is active authority unless explicitly promoted into current-state docs — see `core/contracts/FRAMEWORK_BASELINE.md` "Removal Rules".

## Enforcement Reality

Not every rule in this file is machine-checked. Know which is which before assuming a rule
is unbreakable:

**Hard-enforced (`.githooks/pre-commit`, fires on every `git commit`, cannot be skipped
without `--no-verify`):** secrets, emoji/icons, PII, deleted-repo references, workflow
push-auth, contract integrity (incl. `OLIVERCODE_DEPENDENCY.md` path existence), planning-doc
governance (if present), token policy (Gate 8).

**Soft — instruction only, relies on the agent actually following it, same reliability class
as any other unenforced convention:** "read `docs/FRAMEWORK_BOUNDARY.md` before structural
changes," the skills-placement ledger-write requirement, the CODE→DOCS→AUDIT→QA→GATE→
COMMIT→PUSH ordering, and running the QA scripts at all (`full-qa-pass.sh`/`run-on-repo.sh`
are never auto-triggered). These are real rules worth following, but nothing blocks a commit
that skips them. Don't assume "it's written in CLAUDE.md" means "it's enforced" — check
whether it's a hook or a sentence.

## Required Workflow

The sequence is `core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` (gap analysis through
commit, the human-facing loop) plus `core/contracts/EXECUTION_CONTRACT.md` (the gate and
evidence mechanics the loop ends in) — one home each, not restated here.

## Documentation Sync Requirement

See `docs/DOCUMENTATION_STANDARD.md` "Always current — the sync rule" — one home for the trigger paths and
what to update. Enforced by manual review (no active automated validator).

## Source-of-Truth Documents

Canonical current-state authority: `core/contracts/FRAMEWORK_BASELINE.md` "Support" (the
full list) and "Ship" (reusable contract/template surfaces). One home; not restated here.

## Review Standard

Required review evidence before commit:
- `bash scripts/validate.sh` gates pass
- launcher help surface still matches docs
- setup command registry still matches docs
- removed files have no surviving canonical references
- git diff contains only intended current-state changes

## Required Commands

```bash
bash scripts/validate.sh
scripts/olivercode --help
```

## Safe Push Rules

- Commit only after governance gates pass and staged files are reviewed.
- Do not stage secrets, `.env*`, runtime state, private vault content, caches, or generated local reports.
- After push, verify `git status --short --branch` is clean and record the pushed short SHA.
