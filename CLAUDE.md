# OliverCode Agent Rules

This file loads in every session on this machine, from any directory, via the
`~/.claude/CLAUDE.md` symlink. **Your working directory is usually NOT OliverCode**, so every
path below is written to resolve from wherever you are:

- `$OC/...` means a path inside the OliverCode repo. Resolve `$OC` once, when you first need
  it, and verify it — an uninstalled or moved symlink resolves to `.`, which would silently
  point at the wrong repo:
  ```bash
  OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
  [ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed at ~/.claude/CLAUDE.md — see its docs/ADOPTING.md"
  ```
  No hardcoded vault or home paths.
- Bare paths (`scripts/validate.sh`, `docs/`) mean the repo you are currently working in.
  Each fleet repo ships its own. They are not OliverCode's.

## Voice
Plain full sentences and real words. Lead with the answer. Then give the context a reader needs to
act on it: what you verified, what you found, what is still unknown. Never cut words if the cut costs
meaning. Text a person reads as written (a skill's questions, options and messages, any document you
draft) goes out word for word as the skill gives it.

## Before you change structure or move a skill
- Structural change to a repo: read `$OC/docs/FRAMEWORK_BOUNDARY.md` first.
- Installing, creating, or moving ANY skill or agent file (in OliverCode, `~/.claude/`, or any
  repo): read `$OC/docs/SKILLS-PLACEMENT.md` first — one home per layer, ledger write in the
  same session.

## Development Practice
Always-on while working, not on request. Full sequence — gap analysis, spec, priority,
build/verify/commit loop, separate QA pass, simplify —
`$OC/core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md`. The rules below are the ones you
apply constantly. That contract is the order they run in.
- Something broken/failing/slow? Run the `diagnosing-bugs` skill loop — never patch on a guess.
- Multi-commit build session ending? Run the `deep-review` skill (single review agent,
  simplify, remove-don't-archive cleanup, live re-verify, tracker update) before closing.
- Simplify as you go: after any nontrivial change, ask what the diff makes redundant
  (`/simplify`, `/code-review` before commit).
- Comment the reason, not the mechanism: say what defect the code prevents or why it is shaped
  this way. Keep a comment only if the code could not say it. Never hand-maintain a volatile
  number (test counts, coverage, timings) in prose. State the command instead. Dated
  measurements go in the backlog tracker once, with their date.
- Ablate before trusting a test: remove the guard, verify it goes red, restore. A test that
  stays green without the code it protects reports confidence it has not earned.
- Folder structure stays clean and minimal — no new top-level dirs without a contract reason
  (`$OC/core/contracts/PROJECT_STRUCTURE_STANDARD.md`).
- Writing a doc, note, email or comment: work out what the reader will do with it and say that
  first. Use the specific facts you have. Keep the words plain. Review the draft after you write
  it, not while you compose it. For a README or repo doc, use the `writing-documentation` skill.
  One concept has one home. Docs sync in the same commit as the change.
- Prefer deterministic scripts over LLM calls, and short pointers over restated rules.
- Fixing gate or lint violations in a file: read the full violation list once, fix every
  violation in one pass, then re-verify once. Never fix one violation, re-run the checker,
  fix the next one it finds, and repeat — that turns an N-violation fix into an N-round
  loop, each round re-paying the checker's full output cost.
- Re-read a file before you edit it when anything else could have changed it. Another session
  in a shared tree, a hook or a generator can do that. Read a file before editing it, every first
  touch. Grep for callers before changing a function signature. Research before you edit, not
  after. An edit made blind gets retried once the read finally happens, which pays for the file
  twice.

## Pre-Commit
Run the current repo's own canonical validation before committing, never OliverCode's.
Usually `scripts/validate.sh`. Where that file does not exist, the repo runs validation
through its own npm script instead (`validate`, or `check`). Verify which from that repo's
CLAUDE.md or package.json rather than assuming the filename — an agent that assumes, finds
nothing, and moves on has skipped validation without noticing.
Follow: CODE→DOCS→AUDIT→QA→GATE→COMMIT→PUSH.

## Enforcement
`.githooks/pre-commit` is the only mechanically-enforced layer (thirteen gates here, eleven in a
repo that adopts the framework -- `$OC/docs/GOVERNANCE.md` has the per-repo table).
It is installed per repo via `core.hooksPath`. If that config is unset or points at a missing
directory, **git runs no hooks at all and says nothing** — the gates fail open. `$OC/scripts/olivercode health`
is what detects that. `$OC/scripts/olivercode sync-hooks` fixes it.

Everything else in this file and in `CONTRIBUTING.md` is instruction text — see CONTRIBUTING.md's
"Enforcement Reality" section before assuming a written rule is unbreakable.

## OliverCode's own surface (only when working IN OliverCode)
- `bash scripts/validate.sh` — gates, doc/code consistency, reference integrity, tests
- `python3 scripts/audit-staleness.py` — flags fleet repos past 30 unreviewed commits
- `python3 scripts/find-spec.py SPEC-N` — resolves a bare backlog ID (`SPEC-21`, `B20`)
  fleet-wide in one command. Every repo numbers its own backlog independently, so the
  same ID can name unrelated work in two different files — grep-and-read-both is the
  wrong instinct, run this instead.
- `scripts/qa/full-qa-pass.sh --target <repo>` / `scripts/qa/run-on-repo.sh` — QA sweep
- Layout: `core/` (contracts, personas, templates, workflows), `skills/` (flat, one dir per
  skill), `shared/` (manifest, policies), `scripts/` (launcher + gates), `docs/`
- Enforcement config: `local/repo-profiles.json` (gitignored, real fleet) or
  `shared/repo-profiles.example.json` (tracked placeholder), `shared/task-policies/`,
  `scripts/orchestration-gatekeeper.py`
