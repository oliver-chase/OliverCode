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
  Delegated suites are a CONVENTION with no implementation: a profile may carry
  `"suites": ["sdr"]` and one repo does, but nothing reads it. The JS resolver that did
  (`findSuiteRepo` in a `repo-profiles.mjs` mirror) existed only for the bots-gateway
  subsystem removed in `94dbec7`; it survived orphaned, tested only by itself, and was
  deleted 2026-07-27. If delegated suites are ever built, resolve via the flag rather than a
  hardcoded repo name — that part of the decision stands.
- **ACT-3 — Skill precedence gap (known, unmitigatable at mechanism level).** A generic
  skill and a repo-specific approval-gated skill can both match the same task, and nothing
  biases selection toward the gated one before a repo file is touched. Mitigation: a named,
  explicit directive in the repo's own `CLAUDE.md`. See `docs/skills-placement.md`.

---

## Resolved — the A-series

What was built and why. Kept because each entry records the failure class the gate exists to
stop; deleting it invites rebuilding the same thing. Currently-open work lives under the live
tracker's "Open items" below.

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

A full read-every-file audit ran over all tracked files, then three follow-on passes:
activation (does this actually work outside OliverCode), fork usability (does a stranger get
a working framework), and a necessity audit (is everything here earning its place).

- **Audit + cleanup.** Removed the conflicting `install-enforcement.sh`/`pre-commit-gate.sh`
  hook installer, a no-op QA phase, orphaned docs/configs, and four micro-workflows folded
  into canonical homes. Duplicated authority collapsed to one home each: trigger routing,
  testing baseline, backlog procedure, gate table, branch lifecycle, quality baseline,
  skills catalog, and the orchestration path map.
- **The framework now fails closed** on the two classes that produced the audit's findings:
  a reference naming a path that isn't there (`scripts/lib/reference_check.py`, 322 backtick
  paths on top of 9 markdown links) and a doc asserting what the code contradicts
  (`scripts/lib/consistency_check.py`).
- **Activation was loading but not resolving.** The rules reached every session, but 8 of the
  global `CLAUDE.md`'s pointers dangled outside OliverCode — including both blocking "read
  this first" directives. That file is now path-independent: `$OC` resolves from the symlink
  and is checked; a bare path explicitly means the current repo.
- **Hook enforcement fails open, and the detector shared the bug.** `health` reported `[OK]`
  for a repo whose hooks directory did not exist. Fixed, with regression tests per state.
- **A fork works with no configuration**, and it is gated rather than hoped:
  `scripts/qa/check-fork-usable.sh` (Phase 4 of `full-qa-pass.sh`) builds a pristine sandbox
  with a throwaway HOME, then walks the documented adoption path against two throwaway repos
  and asserts a staged secret is actually blocked.
- **Onboarding is four commands** — `clone`, `install`, `init`, `sync-hooks` — with the
  judgment steps driven by the `olivercode-adoption` skill. `docs/ADOPTING.md` is the path.

Nothing is open that blocks a fork. The two items below are operator-side.

### Coverage

Reviewed through: `e267385` (2026-07-27, full-file audit + activation/fork/necessity passes)

### Open items

**B5 — RESOLVED 2026-07-27.** The perl guard was hand-merged into
oliver-strategic-growth's variant hook (both `pre-commit` and `pre-commit-private`), leaving
its repo-specific governance path intact. Verified against that exact hook: an emoji is still
blocked with perl present, and with perl off PATH the commit is now blocked instead of
allowed. Committed there as a single two-file change; the other agent's work in that repo was
untouched. The standing lesson is on the `hookVariant` field itself — a declared variant stops
receiving template fixes, so re-check it by hand whenever the template's gates change.

**B5-note — superseded:**
It declares `hookVariant: sdr-planning-governance`, so `sync-hooks` correctly leaves it alone
— and it therefore did NOT receive the perl guard that closed the emoji-gate fail-open. Its
Gate 2 still passes silently on a machine without perl. This is the designed trade-off of B3,
not a bug in it, but it needs a hand-merge: port the perl guard into that repo's
`.githooks/pre-commit` (and its private variant if present) without disturbing its
repo-specific governance path. Any future template gate change needs the same treatment.

**B4 — RESOLVED 2026-07-27.** `sync-hooks` run with the fleet's hook files clean; five targets
synced, the declared variant skipped, `health` 12/12 HEALTHY. The perl guard reached all five
public repos plus the vault's private variant.
**B2 — re-enable CI when GitHub Actions billing is restored (LOW, trigger).**
`.github/workflows/framework-ci.yml` is `disabled_manually` while billing is blocked (see
`githubActionsPolicy` in `shared/project-bootstrap-manifest.json`). It ships ready and gates
health, validate.sh, strict bloat, and fork usability. When billing returns:
`gh workflow enable "OliverCode Framework CI"`. This stays a recorded trigger rather than
becoming machinery — detecting "is billing restored" would need network calls from a health
check that must work offline, which costs more than it saves. Until then the local commands
are the enforcement, which is why those checks also run from `full-qa-pass.sh`.

**B1 — RESOLVED 2026-07-27.** Hook state is now reported by `bash scripts/validate.sh` on
every run, advisory and never fatal. CLAUDE.md already tells agents to run that before every
commit, so the signal lands where they look instead of in a weekly log nobody read. The cron
job stays as the unattended backstop. Deliberately not wired to a notification channel: host
scheduler and alerting are private-overlay territory per `docs/FRAMEWORK_BOUNDARY.md`, and the
framework should not own the operator's alert path.

**B3 — RESOLVED 2026-07-27.** A repo profile may declare `hookVariant: "<reason>"`. `health`
then reports its hook divergence as WARN instead of FAIL, and `sync-hooks` SKIPS the repo
instead of overwriting a considered customization. Undeclared divergence still FAILs, and a
declaration never excuses a missing, unexecutable, or unconfigured hook — those are the
fail-open cases and remain fatal. Verified against the real divergent fleet repo
(`oliver-strategic-growth`, which carries a repo-specific governance path): declaring it
returns the fleet to HEALTHY, `sync-hooks` leaves it untouched, and breaking its `hooksPath`
still fails. Documented in `shared/repo-profiles.example.json`.

### Deliberately kept / decided (do not redo)

- `core/templates/project/pre-commit` intentionally differs from `.githooks/pre-commit`: the
  OliverCode copy adds Gate 6 (contract integrity) and Gate 8 (token policy); the template
  carries the anon-key meta-tag allowlist. Both correct; do not converge them.
- `core/contracts/AGENT_SYSTEM_MANIFEST.json` looks like a duplicate of
  `AGENT_SHARED_STRUCTURE.md` but is the tracked half of the G1 example/overlay pair and has a
  real `local/` counterpart. Keep both.
- `skills/model-routing/` — see A7 above.
- The keepalive surface — in scope by owner decision, synced via the manifest's
  `conditionalFiles`, not an orphan.
- **The WRITE MODE evidence gate is opt-in, not a completion requirement.** The machinery
  works and is tested, but no evidence record has ever existed in this fleet and every commit
  predates one. `EXECUTION_CONTRACT.md` now describes it accurately. Do not re-assert it as a
  universal precondition — a contract every commit violates teaches that written rules are
  optional.
- **`olivercode add-repo` — WONT-FIX.** Registering a fleet still means hand-editing
  `local/repo-profiles.json` once per repo. A command for that would be ~60 LOC plus tests
  plus docs to save a one-time edit, and satisfies none of `FRAMEWORK_BASELINE.md`'s four
  admission criteria. The real sharp edge was Gate 8 failing with an unactionable message;
  that is fixed. Revisit only if fleet size makes the edit genuinely repetitive.
- The governance CI pathway (`scripts/run-governance-target.sh` +
  `core/templates/project/.github/workflows/olivercode-governance.yml`) is absent from every
  fleet repo today. That is the billing pause, not dead code — it is a working path the moment
  CI returns. Keep.

### Activity log (append here, newest last)

- 2026-07-27 [audit] Defect fixes + orphan removal, `ed1e4d1`.
- 2026-07-27 [audit] Legacy-reference strip, doc consolidation, specs written, `e773ff1`.
- 2026-07-27 [audit] Path map / baseline rules to one home, `67bc6ff`.
- 2026-07-27 [audit] FEATURE_MAP made a real index, `8e19b17`.
- 2026-07-27 [audit] Product paths out of the location contract, lib imports unified, `9c87a91`.
- 2026-07-27 [audit] Owner decisions: keepalive into scope, `vault-content-parsing` moved to
  the vault, `model-routing` kept as a declared exception. A6/A8 resolved, `16a1849`.
- 2026-07-27 [audit] A1-A5 built: reference integrity, consistency checker, enforcement tests,
  CI gating, `8db0cf3`.
- 2026-07-27 [activation] Global CLAUDE.md made path-independent; fleet hooksPath converged;
  5 repo CLAUDE.md pointer blocks repaired; hook-install fail-open closed, `fc5aa7e`.
- 2026-07-27 [fork] Stranger-clone blockers fixed; `docs/ADOPTING.md` + `olivercode-adoption`
  skill added, `dc1c4bb`. Reference gate taught to scan untracked files, `0ccf2f6`.
- 2026-07-27 [fork] `olivercode init`, real `--root`, unknown args rejected, `9e672f5`.
- 2026-07-27 [fork] Fork-usability gate built and mutation-tested, `5220316`; extended to walk
  the adoption path itself, `659eba8`.
- 2026-07-27 [fork] CI-only gates moved onto the local path; Actions pause recorded as policy,
  `386395c`.
- 2026-07-27 [docs] `olivercode install` added; ARCHITECTURE rewritten; INSTALL.md folded into
  README; "what you get and what enforces it" contract added, `63d5b3c`.
- 2026-07-27 [necessity] Completion gate stopped asserting a rule nobody runs; QA worktree
  double-count fixed (it was hiding real findings); Gate 8 message made actionable, `e267385`.
