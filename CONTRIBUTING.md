# Contributing to OliverCode

Contribution entry point for OliverCode framework changes.

## Locked framework rule

OliverCode is the baseline framework for all downstream project repos. Every change must
keep the framework small, current, and reusable. Every tracked file must justify itself as
exactly one of:

- **run** — launcher and orchestration entrypoints (`scripts/olivercode`)
- **verify** — gates that prove the framework works (`scripts/validate.sh`, `.githooks/`, `tests/`)
- **ship** — contracts and templates downstream repos inherit (`core/`, `shared/`)
- **support** — current-state docs explaining the active surface (`docs/`, root docs)

If a file does none of those, delete it, merge it, or move it to the repo that owns it.
`core/contracts/FRAMEWORK_BASELINE.md` "Purpose" is the contract. This is where you apply it.

## Mandatory rules

1. Claude Code is OliverCode's sole runtime and Anthropic its sole model provider — do not reintroduce multi-runtime or multi-provider framing without a real implementation behind it.
2. Keep project-specific runtime logic in the owning project repo.
3. Documentation sync is required in the same change set — see `docs/DOCUMENTATION-STANDARD.md` "Keeping documents current".
4. Run `bash scripts/validate.sh` before every commit.
5. A new doc replaces or merges with an older doc, so authority stays in one place.
6. No roadmap, migration, or status markdown is active authority unless explicitly promoted into current-state docs — see `core/contracts/FRAMEWORK_BASELINE.md` "Removal rules".

## Enforcement reality

Not every rule in this file is machine-checked. Know which is which before assuming a rule
is unbreakable:

**Hard-enforced:** the gates in `.githooks/pre-commit`, which fire on every `git commit`.
`docs/GOVERNANCE.md` lists them. Inside Claude Code, the commit guard also refuses a commit
that would skip them (`core/contracts/EXECUTION_CONTRACT.md` "Session Hooks").

**Soft — instruction only, relies on the agent actually following it, same reliability class
as any other unenforced convention:** "read `docs/FRAMEWORK-BOUNDARY.md` before structural
changes," the skills-placement ledger-write requirement, the CODE→DOCS→AUDIT→QA→GATE→
COMMIT→PUSH ordering, and running the QA scripts at all (`full-qa-pass.sh`
is never auto-triggered). These are real rules worth following, but nothing blocks a commit
that skips them. Don't assume "it's written in CLAUDE.md" means "it's enforced" — check
whether it's a hook or a sentence.

## Required workflow

The sequence is `core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` (gap analysis through
commit, the human-facing loop) plus `core/contracts/EXECUTION_CONTRACT.md` (the gate and
evidence mechanics the loop ends in) — one home each, not restated here.

## Source-of-truth documents

Canonical current-state authority: `core/contracts/FRAMEWORK_BASELINE.md` "Support" (the
full list) and "Ship" (reusable contract/template surfaces). One home, not restated here.

## Review standard

Required review evidence before commit:
- `bash scripts/validate.sh` gates pass
- launcher help surface still matches `docs/OLIVERCODE-LAUNCHER.md`
- removed files have no surviving canonical references
- git diff contains only intended current-state changes

## Required commands

```bash
bash scripts/validate.sh
scripts/olivercode --help
```

## Safe push rules

- Commit only after governance gates pass and staged files are reviewed.
- Do not stage secrets, `.env*`, runtime state, private repo content, caches, or generated local reports.
- After push, verify `git status --short --branch` is clean and record the pushed short SHA.
