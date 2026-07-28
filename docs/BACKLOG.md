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
  explicit directive in the repo's own `CLAUDE.md`. See `docs/SKILLS-PLACEMENT.md`.

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

**B6 — RESOLVED 2026-07-27.** `sync-hooks` run; three fleet repos took the corrected
template (their own validation suites ran inside the hook and passed), the two declared
variants were skipped as designed, and the hook change was committed and pushed in each repo.
`health` reports HEALTHY with zero failures. Original entry:

**B6 (was) — fleet-side.** The public hook template's gate
banners were corrected from `Gate N/5` (with a contradictory `Gate 6/6` at the end) to a
consistent `Gate N/6`. Deployed fleet hooks now differ from the template by that banner text,
so `health` reports three of the registered fleet repos as diverging. **The difference is
printed text only — no gate's behaviour changed**, verified by diffing the template against a
deployed copy. Whoever owns the fleet clears it with one `scripts/olivercode sync-hooks`. Not
done here: other agents are working in those repos and this session's scope is OliverCode.

**B8 — RESOLVED 2026-07-27.** Real fleet repo names had leaked into tracked files through
prose: BACKLOG entries naming the repos that needed a re-sync, and one real name used as a
test fixture. The registries were generic from the start, so the three-layer design held
where it was designed to and failed where nobody was looking. Neither the reference gate nor
the PII gate could see it, because both match paths and email addresses and a bare repo name
is neither. `check_no_fleet_names_in_tracked_files` now derives the names to search for from
the operator's own gitignored profile, so there is no hardcoded list of what to hide, which
would itself be the leak. Names that collide with the repo's own vocabulary, and placeholder
names from the tracked example, are excluded — the first cut fired 86 times on a profile
named `core` and would have been switched off.

**B7 — RESOLVED 2026-07-27.** Every repo-map field now has a consumer. `governanceProfile:
"incubating"` makes `audit-staleness.py` report a past-threshold repo as advisory instead of
failing the run (an unknown value warns, so a typo cannot silently exempt a repo).
`approvedStrictVariances` joined the expiry sweep alongside the maintainability variances,
and every waiver or variance now REQUIRES a written reason — `health` fails on a reasonless
entry, because an exception nobody can later judge can never be safely retired.
`audit-staleness.py` also honors a profile's explicit `path`, so a scattered fleet is
auditable. Schema documented in `shared/repo-map.json`'s `_note`.

**B5 — RESOLVED 2026-07-27.** The perl guard was hand-merged into
the variant hook of the repo that declares one (both `pre-commit` and `pre-commit-private`), leaving
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
**B6 — the hook-variant tax is now recurring (LOW, watch).**
Two repos in the reference fleet declare `hookVariant`, so every template
gate change needs a hand-merge into both — done twice today already (the perl guard, then
Gate 4). That is B3's designed trade-off working correctly, but the cost compounds. If a
third variant appears, switch to the template-composition option recorded under B3 (a base
hook plus declared per-repo gates) rather than accumulating manual merges; hand-merging is
how a security fix reaches five repos and misses two.

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
(the one carrying a repo-specific governance path): declaring it
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
- 2026-07-27 [fork] Fresh-agent adoption run on a sandboxed machine (throwaway HOME, three
  non-sibling repos, pre-existing `~/.claude`). It succeeded end to end, and found that the
  headline **8-gate claim was false for every adopted repo** (they get 6; contract integrity
  and token policy are framework-only) in six documents. Coverage table added to
  `docs/GOVERNANCE.md` as its one home; `consistency_check.py` extended to resolve each claim
  to the hook it is about, check every hook variant's internal numbering, and verify that
  table — the old checker skipped `core/templates/` on purpose, and its claim pattern required
  the number to sit directly beside the noun, so the count in README's own headline (which had
  "pre-commit" in between) was never even matched. It passed throughout. Also: template banner numbering fixed,
  `check-fork-usable.sh` was using `cp` on a symlinked directory and had therefore never
  tested the project-level adoption skill, ADOPTING's register/enforce steps were in the wrong
  order (`sync-hooks` ran before the fleet file existed), health now counts skips separately
  from passes, and waiver expiry in `repo-map.json` is enforced instead of decorative.
- 2026-07-27 [fork] `olivercode init`, real `--root`, unknown args rejected, `9e672f5`.
- 2026-07-27 [fork] Fork-usability gate built and mutation-tested, `5220316`; extended to walk
  the adoption path itself, `659eba8`.
- 2026-07-27 [fork] CI-only gates moved onto the local path; Actions pause recorded as policy,
  `386395c`.
- 2026-07-27 [docs] `olivercode install` added; ARCHITECTURE rewritten; INSTALL.md folded into
  README; "what you get and what enforces it" contract added, `63d5b3c`.
- 2026-07-27 [necessity] Completion gate stopped asserting a rule nobody runs; QA worktree
  double-count fixed (it was hiding real findings); Gate 8 message made actionable, `e267385`.
- 2026-07-27 [voice] README rebuilt to the V.Two README contract (six sections, narrative, no
  tables, second person) with a complete linked index of every document, so nothing became
  unreachable when the old tables came out. Reference content relocated rather than deleted:
  external tooling to `docs/EXTERNAL-TOOLING.md`, directory layout already in ARCHITECTURE.
  `docs/DOCUMENTATION_STANDARD.md` previously mandated the old section list, which the rewrite
  would have silently violated; it now defers to the V.Two contract and pins where each piece
  of required content lives. GitHub About description and topics set (both were empty).
- 2026-07-27 [audit] Fleet-name leak closed (B8). `docs/FEATURE_MAP.md` had a malformed row
  that pointed "unfalsifiable checks" at the hook-drift module and left an orphan two-column
  row in a three-column table.
- 2026-07-27 [audit] Open items closed: B6 (fleet hooks converged, committed in each repo),
  B7 (repo-map fields wired: incubating profile consumed by audit-staleness, strict variances
  in the expiry sweep, reasons required), B2 attempted (CI re-enabled; next push is the live
  billing test). 12-scenario sandbox matrix built and shipped as
  `scripts/qa/check-scenarios.sh` — 46 assertions across fresh-machine, existing-setup,
  scattered-fleet, --root, discover, bootstrap, hookVariant, backout, idempotency, update,
  no-commit-probe, and zero-config cases, all green. One matrix finding: a nonexistent
  `--root` hard-errors (fail-closed), which is stronger than the doc's skip-warning implied.
- 2026-07-27 [audit] B2 tested live: workflow enabled, push triggered a run, GitHub refused
  to start the job ("recent account payments have failed or your spending limit needs to be
  increased") — zero minutes consumed. Workflow re-disabled to keep pushes green-quiet. B2
  stays open on the same external condition; re-enable is one command
  (`gh workflow enable "OliverCode Framework CI"`) once billing is restored.
- 2026-07-27 [docs] Documentation standard locked in as a self-contained contract
  (`docs/DOCUMENTATION_STANDARD.md`): problem-driven README outline, voice, formatting,
  CAPS-KEBAB doc naming, complete doc table, open-only backlog policy, same-commit sync,
  GitHub About required. New `writing-documentation` skill applies it anywhere, including
  forks. README rewritten as the exemplar. Four docs renamed to the convention
  (GOVERNANCE, TROUBLESHOOTING, SKILLS-PLACEMENT, EXTERNAL-TOOLING), every reference swept.
  `health` now checks the About (WARN-degrades offline). Template QUALITY_BASELINE and the
  global CLAUDE.md point at the standard, so stamped repos and every session inherit it.
- 2026-07-27 [audit] Post-merge audit of the Code Intent Standard: three references to a
  specific sibling repo generalized out (tracked files stay generic; the operator barred
  that repo as a reference point), and its §5 reconciled with the documentation standard's
  Status slot — volatile counts now stated as the command that proves them, quoted only as
  dated measurements. README Status rewritten to comply. Leak gate hardened: fleet names
  now also derive from sibling git repos on disk, so an UNREGISTERED project's name in a
  tracked file fails the build — the profiles-only gate had missed exactly that. Pinned by
  mutation test.
- 2026-07-27 [simplify] The three deferred judgment calls executed. Launcher trimmed 1085
  to 903 lines by extracting `lib/health_checks.py` (waiver expiry, GitHub About) and
  `lib/skills_catalog.py` (frontmatter parsing) — launcher re-exports, tests unchanged,
  matrix 46/46. The fork-usable/scenario-matrix overlap is now DECLARED in both headers
  with its reason (fast CI gate vs exhaustive complement) instead of reading as
  accidental duplication. All five fleet READMEs converted to command-style Status per
  Code Intent §5 — the proving command is authoritative, no hand-maintained counts left.
