# Contributing to OliverCode

This file is the contribution entry point for OliverCode framework changes.

## Locked Framework Rule

OliverCode is the baseline framework for all downstream project repos.
Every change must keep the framework small, current, and reusable.

Each tracked file must justify itself as one of:
- run
- verify
- ship
- support

If it does none of those, delete it, merge it, or move it out of core.

## Mandatory Rules

1. Claude Code is OliverCode's sole runtime and Anthropic its sole model provider — do not reintroduce multi-runtime or multi-provider framing without a real implementation behind it.
2. Keep project-specific runtime logic in the owning project repo.
3. Keep documentation synchronized with code/config changes in the same change set.
4. Run `bash scripts/validate.sh` before every commit.
5. Behavior/config changes must update `docs/FEATURE_MAP.md` and `docs/DOCUMENTATION_STANDARD.md`.
6. New docs should replace or merge older docs instead of creating parallel authority.
7. No roadmap, migration, or status markdown is active authority unless explicitly promoted into current-state docs.

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

1. Make the code/config change.
2. Update affected docs/contracts in the same change set.
3. Run `bash scripts/validate.sh`.
4. Commit only when the gates pass.

## Documentation Sync Requirement

When these paths change, documentation updates are required in the same change set:
- `scripts/`
- `skills/`
- `core/personas/`
- `shared/`
- `core/contracts/`

Enforced by manual review (no active automated validator).

## Source-of-Truth Documents

Canonical current-state authority lives in:
- `core/contracts/FRAMEWORK_BASELINE.md`
- `README.md`
- `docs/governance.md`
- `docs/FEATURE_MAP.md`
- `docs/DOCUMENTATION_STANDARD.md`
- `docs/OLIVERCODE_LAUNCHER.md`

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

## Baseline Contract

Authoritative baseline for all future framework/project standardization:
- `core/contracts/FRAMEWORK_BASELINE.md`
- `docs/governance.md`
- `docs/FEATURE_MAP.md`
- `core/templates/project/QUALITY_BASELINE.md`

## Safe Push Rules

- Commit only after governance gates pass and staged files are reviewed.
- Do not stage secrets, `.env*`, runtime state, private vault content, caches, or generated local reports.
- After push, verify `git status --short --branch` is clean and record the pushed short SHA.
