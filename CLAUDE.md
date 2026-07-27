# OliverCode Agent Rules

> Before making structural changes, read `docs/FRAMEWORK_BOUNDARY.md`. Pre-commit: `.githooks/pre-commit` validates secrets, emoji, PII, deleted refs, bootstrap, contracts.
> Before installing/creating/moving ANY skill or agent file (here, `~/.claude/`, or any repo): `docs/skills-placement.md` — one home per layer, ledger write in the same session.

Orchestration framework for AI agent teams: core/ (contracts, features, personas, workflows), skills/ (all tracked skills, one flat directory — see docs/skills-placement.md), shared/ (templates, policies), scripts/ (validation gates), docs/.

## Voice
Compressed, high-signal. No filler. Caveman mode (`caveman` plugin, full intensity) active by
default from the first response, every session — not trigger-based, don't wait for "less
tokens" or "be brief" to turn it on. Off only on explicit "stop caveman." Code/commits/PRs/
security warnings written normal, per the plugin's own rules.

## Development Practice
Always-on while working, not on request:
- Something broken/failing/slow? Run the `diagnosing-bugs` skill loop — never patch on a guess.
- Multi-commit build session ending? Run the `deep-review` skill (single review agent,
  simplify, remove-don't-archive cleanup, live re-verify, tracker update) before closing.
  Coverage cadence: `python3 scripts/audit-staleness.py` flags repos past 30 unreviewed
  commits; `scripts/qa/check-bloat.sh` (full-qa-pass Phase 3) keeps legacy from re-growing.
- Simplify as you go: after any nontrivial change, ask what the diff makes redundant (`/simplify`, `/code-review` before commit).
- Folder structure in project repos stays clean and minimal — no new top-level dirs without a contract reason (`core/contracts/PROJECT_STRUCTURE_STANDARD.md`).
- Documentation robust but manageable: one concept one home, pointers elsewhere (sync trigger/scope: `docs/DOCUMENTATION_STANDARD.md` "Requirement").
- Token efficiency is a design constraint: prefer deterministic scripts over LLM calls, short pointers over restated rules.

## Pre-Commit
`bash scripts/validate.sh` before commit. Follow: CODE→DOCS→AUDIT→QA→GATE→COMMIT→PUSH.

## QA
- Full: `scripts/qa/full-qa-pass.sh --target <repo>`
- Auto: `scripts/qa/run-on-repo.sh`

## Enforcement
See `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder), `shared/task-policies/`, `scripts/orchestration-gatekeeper.py`.
Hard vs soft rules: `.githooks/pre-commit` (8 gates, incl. token policy) is the only
mechanically-enforced layer. Everything else in this file and `CONTRIBUTING.md` is
instruction text — see CONTRIBUTING.md's "Enforcement Reality" section before assuming
a written rule is unbreakable.
