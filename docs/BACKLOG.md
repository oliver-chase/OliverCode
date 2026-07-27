# BACKLOG — OliverCode

Forward-looking framework improvements only. Historical audit worklogs live outside this
repo (they are operator-specific session records, not framework material — per this
framework's own removal rule: history/status docs are not active authority).

Status values: OPEN, IN-PROGRESS, FIXED, WONT-FIX (with reason).
Severity: HIGH (gate silently broken / wrong result), MEDIUM (wrong on real inputs or
misleading), LOW (polish, drift).

---

## Design decisions (stable rationale — referenced from code and docs by ID)

These IDs are cited from `.gitignore`, `scripts/validate.sh`, contract JSON `_note` fields,
and several docs. They are settled decisions, not open items.

- **G1 — Example-config + local-overlay pattern.** Tracked files ship placeholder-only
  registries (`shared/*.example.json`, placeholder `shared/repo-map.json` etc.); the real
  fleet lives in gitignored `local/` copies. Loaders try the local overlay first and fall
  back to the tracked example with a WARN. Personal data never enters tracked files.
- **D2 — No repo-specific enforcement in the framework.** `validate.sh --target-repo <root>`
  execs the target's own `scripts/validate-repo.sh` if present, else skips cleanly.
  Delegated suites (e.g. SDR) resolve via a profile flag (`"suites": ["sdr"]`), never a
  hardcoded repo name.
- **ACT-3 — Skill precedence gap (known, unmitigatable at mechanism level).** A generic
  skill and a repo-specific approval-gated skill can both match the same task, and nothing
  biases selection toward the gated one before a repo file is touched. Mitigation: a named,
  explicit directive in the repo's own `CLAUDE.md`. See `docs/skills-placement.md`.

---

## Open items

None open. The A-series below is the record of what was built and why; new specs go here,
written context-free so a future agent with no session memory can execute them.

### A1-A5 — resolved 2026-07-27 (built, verified, wired in)

Kept here as the record of what the gates are and why, since each one exists to stop a
failure class this repo actually hit. All five are live in `bash scripts/validate.sh`.

- **A1 — reference integrity.** `scripts/link-check.sh` saw 9 markdown links while the real
  cross-references were hundreds of backtick repo paths; every stale path the audit found
  lived in that blind spot. Now a second pass (`scripts/lib/reference_check.py`) resolves
  backtick-quoted paths whose first segment is a tracked top-level directory: 303 refs
  checked. Exemptions are explicit and commented -- downstream-relative contract paths,
  gitignored local layers, placeholder tokens, template files, and the anti-pattern examples
  in `FILE_LOCATION_STANDARD.md` (whose paths must NOT resolve).
- **A2 — skills index parity.** INDEX rows vs `skills/*/SKILL.md` directories, both
  directions, plus frontmatter `name:` vs directory name (the launcher lists by frontmatter,
  humans read the table; they drifted apart silently before).
- **A3 — gate-count claims.** The hook is the source of truth; any tracked doc claiming a
  different "N gates" fails. `QUALITY_BASELINE.md` had drifted to 6 against a hook with 8.
- **A4 — CI gating.** `check-bloat.sh --strict` now fails the build; full-qa-pass stays
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

### A7 — model-routing remains a declared scope exception (LOW)

`skills/model-routing/` is built on `LLM_PROVIDER_ORDER` and cheapest-vs-capable provider
tiers, while `CONTRIBUTING.md` mandatory rule 1 names Anthropic the sole model provider and
forbids multi-provider framing without an implementation behind it. Kept deliberately
(owner decision, 2026-07-27) as a pattern contract rather than a claim about this
framework's runtime. Do not re-raise as drift; if it is ever removed, tear down
`~/.claude/skills/model-routing` in the same session or `olivercode health` reports a broken
symlink.

---

## Live tracker — current state for the next agent

### Where things stand (2026-07-27)

- Full read-every-file audit of all tracked files completed and executed: defect fixes,
  legacy-reference strip, doc consolidation, and both owner decisions applied.
- Removed: the conflicting `install-enforcement.sh`/`pre-commit-gate.sh` hook installer, a
  no-op QA phase, orphaned docs/configs, four micro-workflows folded into canonical homes.
- Doc duplication collapsed: trigger routing, testing baseline, backlog procedure, gate
  table, branch lifecycle, quality baseline, and the skills catalog each have one home.
- Every file under `core/templates/project/` is now declared in the bootstrap manifest —
  `templatedFiles` for the unconditional ones, `conditionalFiles` for the keepalive set,
  which syncs only where a repo's `keepalive` profile block enables it.
- A1-A5 built and wired into `validate.sh`: reference integrity now checks 303 backtick repo
  paths on top of 9 markdown links, doc/code consistency is mechanical, and the enforcement
  surfaces have 46 tests where they had none. Nothing is open.
- The framework now fails closed on the two classes that produced this audit's findings:
  a reference naming a path that isn't there, and a doc asserting what the code contradicts.

### Coverage

Reviewed through: `16a1849` (2026-07-27, full-file audit)

### Deliberately kept (validated decisions — do not redo)

- `core/templates/project/pre-commit` intentionally differs from `.githooks/pre-commit`:
  the OliverCode copy adds Gate 6 (contract integrity) and Gate 8 (token policy); the
  template carries the anon-key meta-tag allowlist. Both are correct; do not converge them.
- `scripts/qa/check-code-quality.sh` is TypeScript-leaning and several of its sections are
  low-yield on this repo. It earns its place on the Next.js fleet repos, which are its real
  target. Not a cleanup candidate here.
- `core/contracts/AGENT_SYSTEM_MANIFEST.json` looks like a duplicate of
  `AGENT_SHARED_STRUCTURE.md` but is the tracked half of the G1 example/overlay pair and has
  a real `local/` counterpart. Keep both.
- `skills/model-routing/` — see A7.
- The keepalive surface — in scope by owner decision, not an orphan.

### Activity log (append here, newest last)

- 2026-07-27 [audit] Defect fixes + orphan removal, commit `ed1e4d1`.
- 2026-07-27 [audit] Legacy-reference strip, doc consolidation, specs written, `e773ff1`.
- 2026-07-27 [audit] Path map / baseline rules to one home, `67bc6ff`.
- 2026-07-27 [audit] FEATURE_MAP made a real index, `8e19b17`.
- 2026-07-27 [audit] Product paths out of the location contract, lib imports unified, `9c87a91`.
- 2026-07-27 [audit] Owner decisions applied: keepalive brought into scope via
  `conditionalFiles`; `vault-content-parsing` moved to the vault's `.olivercode/user-skills/`
  with its symlink repointed and the ledger updated; `model-routing` kept as a declared
  exception. A6 and A8 resolved, A7 reduced to a keep-note.
- 2026-07-27 [audit] A1-A5 built: reference-integrity pass, doc/code consistency checker,
  46 enforcement-surface tests, CI gating on strict bloat. Backlog now empty.
