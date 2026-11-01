# BACKLOG — OliverCode

Decision rationale and institutional memory only. Open work lives in the OliverCode GitHub
Project — see "Live tracker" below. Historical audit worklogs live outside this repo (they
are operator-specific session records, not framework material — per this framework's own
removal rule: history/status docs are not active authority).

---

## Design decisions (stable rationale — referenced from code and docs by ID)

These IDs are cited from `.gitignore`, `scripts/validate.sh`, contract JSON `_note` fields,
and several docs. They are settled decisions, not open items.

- **G1 — Superseded: example-config + local-overlay pattern retired.** Tracked files used
  to ship placeholder-only registries (`shared/*.example.json`) with the real fleet in
  gitignored `local/` copies, falling back to the placeholder with a WARN. Retired per the
  owner's own call: there was no stranger to protect, so the split was pure maintenance
  weight for a property nobody needed. The four registries listed in `ARCHITECTURE.md`'s
  "The Two Layers" are now tracked directly with real data. `local/` no longer exists.
- **D2 — No repo-specific enforcement in the framework.** `validate.sh --target-repo <root>`
  execs the target's own `scripts/validate-repo.sh` if present, else skips cleanly.
  Delegated suites are a CONVENTION with no implementation: a profile may carry
  `"suites": ["sdr"]` and one repo does, but nothing reads it. The JS resolver that did
  (`findSuiteRepo` in a `repo-profiles.mjs` mirror) existed only for the bots-gateway
  subsystem removed in `8486cb8`. It survived orphaned, tested only by itself, and was
  deleted 2026-07-27. If delegated suites are ever built, resolve via the flag rather than a
  hardcoded repo name — that part of the decision stands.
- **ACT-3 — Skill precedence gap (known, unmitigatable at mechanism level).** A generic
  skill and a repo-specific approval-gated skill can both match the same task, and nothing
  biases selection toward the gated one before a repo file is touched. Mitigation: a named,
  explicit directive in the repo's own `CLAUDE.md`. See `docs/SKILLS-PLACEMENT.md`.

---

## Resolved — the A-series

What was built and why. Kept because each entry records the failure class the gate exists to
stop. Deleting it invites rebuilding the same thing. Currently-open work lives under the live
tracker's "Open items" below.

### A1-A5 — resolved 2026-07-27 (built, verified, wired in)

Kept here as the record of what the gates are and why, since each one exists to stop a
failure class this repo actually hit. All five are live in `bash scripts/validate.sh`.

- **A1 — reference integrity.** `scripts/link-check.sh` saw 9 markdown links while the real
  cross-references were hundreds of backtick repo paths. Every stale path the audit found
  lived in that blind spot. Now a second pass (`scripts/lib/reference_check.py`) resolves
  backtick-quoted paths whose first segment is a tracked top-level directory: 303 refs
  checked. Exemptions are explicit and commented -- downstream-relative contract paths,
  gitignored runtime/memory layers, placeholder tokens, template files, and the anti-pattern
  examples in `FILE_LOCATION_STANDARD.md` (whose paths must NOT resolve).
- **A2 — skills index parity.** INDEX rows vs `skills/*/SKILL.md` directories, both
  directions, plus frontmatter `name:` vs directory name (the launcher lists by frontmatter,
  humans read the table. They drifted apart silently before).
- **A3 — gate-count claims.** The hook is the source of truth. Any tracked doc claiming a
  different "N gates" fails. `QUALITY_BASELINE.md` had drifted to 6 against a hook with 8.
- **A4 — CI gating.** `check-bloat.sh --strict` now fails the build. full-qa-pass stays
  advisory (its other phases are heuristic and would false-positive as a gate).
- **A5 — enforcement-surface tests.** 46 tests: 28 over `validate_evidence()` (one block and
  one pass case per required-evidence field, in both the missing and malformed shape) and 18
  over the pre-commit gates, each building a throwaway git repo and running the real hook
  against a staged fixture. Mutation-checked: neutering Gate 2 turns the suite red, so the
  cases are not vacuous. Gates 5 and 7 are environment- and presence-dependent, so they are
  asserted only at the level that is deterministic offline.

A2 and A3 are collapsed into one checker (`scripts/lib/consistency_check.py`) rather than
two scripts, per `FRAMEWORK_BASELINE.md`'s rule that a validator duplicating another's
failure class gets merged. Both are the same class: a doc asserting what the code contradicts.

### A7 — model-routing (resolved)

The `model-routing` skill is removed. Nothing in the framework depends on it.

---

## Live tracker — current state for the next agent

Open work lives in the OliverCode GitHub Project (`gh project view 15 --owner oliver-chase`),
named in `docs/backlog-config.json` — the same backlog-management pattern this framework
requires of every repo it governs (`core/contracts/PROJECT_STRUCTURE_STANDARD.md`). Resolved
items are closed there with an evidence comment, not kept in this file: `git log` and the
closed-issue history hold that record, and a tracker that keeps its own history stops being a
list of what to do next.

### Coverage

Reviewed through: `224b954` (2026-10-31, deep-review of the voice, skill-deletion and doc-rename commits `d9f2ef9`, `9085920`, `90f1276` and `224b954`. Other sessions' commits between `c996e58` and `224b954` were not part of this review)

---

### Deliberately kept / decided (do not redo)

- **The voice has one home here and a copy in each self-contained suite.** `docs/VOICE.md` is the source. `ecommerce-system` and `automated-content-flow` ship their own `docs/VOICE.md` so they run without OliverCode, and `olivercode health` fails when a copy drifts. `CLAUDE.md` imports the fixed path `~/.claude/VOICE.md` because a relative import from the symlinked `~/.claude/CLAUDE.md` has no documented base directory. Keep both.
- `core/templates/project/pre-commit` intentionally differs from `.githooks/pre-commit`: the
  OliverCode copy adds Gate 6 (contract integrity) and Gate 8 (token policy). The template
  carries the anon-key meta-tag allowlist. Both correct. Do not converge them.
- `core/contracts/AGENT_SYSTEM_MANIFEST.json` looks like a duplicate of
  `docs/FRAMEWORK-BOUNDARY.md`'s path map but is the machine-readable mirror of it (tracked,
  real values, since G1's retirement). Keep both.
- The keepalive surface — in scope by owner decision, synced via the manifest's
  `conditionalFiles`, not an orphan.
- **The WRITE MODE evidence gate is opt-in, not a completion requirement.** The machinery
  works and is tested, but no evidence record has ever existed in this fleet and every commit
  predates one. `EXECUTION_CONTRACT.md` now describes it accurately. Do not re-assert it as a
  universal precondition — a contract every commit violates teaches that written rules are
  optional.
- **`olivercode add-repo` — WONT-FIX.** Registering a fleet still means hand-editing
  `shared/repo-profiles.json` once per repo. A command for that would be ~60 LOC plus tests
  plus docs to save a one-time edit, and satisfies none of `FRAMEWORK_BASELINE.md`'s four
  admission criteria. The real sharp edge was Gate 8 failing with an unactionable message.
  That is fixed. Revisit only if fleet size makes the edit genuinely repetitive.
- The governance CI pathway (`scripts/run-governance-target.sh` +
  `core/templates/project/.github/workflows/olivercode-governance.yml`) is absent from every
  fleet repo today. That is the billing pause, not dead code — it is a working path the moment
  CI returns. Keep.
