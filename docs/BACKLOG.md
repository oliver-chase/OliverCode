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
  subsystem removed in `8486cb8`; it survived orphaned, tested only by itself, and was
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

Reviewed through: `4c418ab` (2026-07-27, full-file audit + activation/fork/necessity passes)

### Open items

Resolved entries are deleted, not archived — `git log` holds them, and a tracker that keeps
its own history stops being a list of what to do next.

**B10 — comment prose is unaudited at scale (MED, done).**
Every mechanical rule is gated: block length fails the build, density is reported
against a per-repo guideline, references and orphans are checked. None of that can
see whether a comment READS well, and a random sample of eight blocks found two
defects no gate could have caught — a FLOW-3 header describing a JWT refresh while
sitting above a dropdown helper 55 lines from the function it documents, and a
four-clause run-on in the CSV parser. Both were under the cap, both named real IDs,
both described real behaviour.

Sampling rate so far is ~1877 medium blocks in the fleet, 8 read. Two defects in
eight is not a rate to extrapolate from, but it is enough to say the gates are not
sufficient.

The pass, in priority order:

1. **Comment-to-code correspondence — DONE.** Built into the comment gate and synced
   to all five repos: an `@param` not in the signature below it, and a stated return
   value where the function returns none. Fires on the FLOW-3 defect re-introduced
   into the real file, zero hits fleet-wide otherwise. It closes the mechanizable
   half of this class; a comment that describes the wrong function WITHOUT claiming
   a return or a param is still only findable by reading.
2. **Read every block over 8 lines, per repo, newest-first — STARTED.** Judge against
   WRITING_PROCESS: does each paragraph do one job, does the last sentence add
   anything, is any sentence carrying four clauses. Newest-first because recent blocks
   are agent-written and that is where the density came from.

   Thirty-three blocks read and rewritten so far: four in this repo, thirteen in the
   studio repo, sixteen in the growth repo. What recurred was not prose quality but
   structure — an opening announcing the subject, a closing restating it, and a
   listing duplicating functions or read sites that already document themselves. Two
   were substantive: one header contradicted itself about which search providers run,
   and one carried a hand-maintained list of its own six callers.

   **The bloat is not evenly spread, and that changes how to size the rest.** Eleven
   blocks across the crawler and the notes app were read and every one left alone — a
   live domain-sale incident with its rejected alternative, an SSRF boundary, two
   guard false positives and the regression that narrowing introduced, a parity
   harness that says what it deliberately does not couple to, and a test that states
   plainly which path it leaves unverified. All earn their length. The defect
   concentrates in agent-written script headers, where a filename banner, a numbered
   restatement of the function below, and an env/output table attach to almost every
   file. Audit those first; do not assume a long block in a library is worth cutting.

   That sample was drawn twice. The first pass ran while the scanner was hiding
   comments, so it was re-run after the fail-open fix: the block rankings were
   identical, which is what makes the conclusion safe to keep. Density figures
   recorded before that fix are understated and should not be compared against
   anything measured after it.

   The crawler's `// ─── Title ───` banner is its convention, on 46 of 48 src files,
   and names the CONCEPT rather than the filename. Left as is — stripping it from a
   few files buys nothing and costs consistency. Not a finding; do not re-litigate.

   **Closed 2026-07-29.** Re-measured after the docstring/template/fail-open fixes:
   every block the gate flags fleet-wide has now been read. Two more real defects
   surfaced in the last pass — `sync.js` named three Touch-1 templates that do not
   exist anywhere in the codebase, and a test header indexed seven tests in a file
   that had grown to eleven — both the same shape as the two found in the original
   sample, a second copy drifting from the first. Every other flagged block earns
   its length and was left alone.

   OSG's density (25.1%) and crawl's (25.9%, under its own configured 28) are the
   honest content of those repos, not evenly-spread bloat with a cuttable core: sdr/
   measures 25.3%, everything else in OSG measures 22.7% — too close to carve a
   differential override out of, and inventing one anyway would repeat the exact
   mistake this backlog already caught once (crawl's `maxDensity: 40`, set from a
   figure that could never fire). Density is reported, never gates the build, and
   is not itself a task.
3. **Sample the short ones — deliberately not pursued.** Blocks under 8 lines are
   mostly fine, number in the thousands, and nothing gates them; the two rounds of
   long-block sampling found defects at a rate too low to justify the token cost of
   extending the same method downward. If a defect class specific to short blocks
   turns up by other means, reopen with that evidence, not a blind sample.

Re-measured after the docstring fix, which is what this entry asked for before sizing
what was left: 759 blocks over 8 lines across the fleet — 271 in the events app, 220 in
the growth repo, 91 in the studio app, 84 in the notes-and-chat app, 54 in the crawler,
30 here, 9 in the notes app. The two repos the earlier rounds never reached were sampled
at their largest script headers, and every one was left alone: each states a decision
with the failure behind it, which is the shape the standard asks for and the opposite of
the filename-banner boilerplate the defect concentrated in.

Not a gate, and should not become one. A checker that judged prose would either be
a keyword list — the failure `How Great Writers Think` names directly — or an LLM
call per comment on every commit, which fails the token-efficiency rule.

**B11 — the decision ledger (HIGH -> resolved for the fleet, one repo still owes rows).**
`CODE_INTENT_STANDARD` §3 requires a `docs/DECISIONS.md` in every consuming repo and §4
requires a gate that fails when an id has no row, a row names deleted code, or a row is
referenced by nothing. All seven repos now carry the ledger and the gate, and the gate runs
on commit rather than only from the validation target (see B13).

Getting there found three defects in the gate itself, each ablation-verified:

- **A ledger row the gate cannot read.** Every check reads the ledger through one id
  pattern, so a row outside that pattern is invisible to all of them — the id in the source
  never resolves as recorded, and the row outlives the code it describes. This repo's own
  ledger carried `FALSIFIABILITY-1`, two segments where §2 requires three, from the day it
  was written. Renamed, and the gate now fails on any unreadable row.
- **A user story is not a decision record.** `US-TSK-118` and `US-SDR-202` match
  `AREA-TOPIC-N` exactly. Harmless while the gate ran from a validation target; with the
  gate in the hook, every story reference in a comment blocked a commit. Excluded by AREA
  rather than by id, so a new story needs no config edit, and by first segment rather than
  prefix, so `USER-FACING-1` is still a decision.
- **Rows written where a reader would otherwise undo the decision.** The studio app cited
  106 ids against an empty ledger; eight rows now cover the load-bearing ones and the
  baseline stands at 98. Not a backfill — a row per id would manufacture a hundred
  restatements, which is the defect this framework exists to prevent.

What is still open is only the studio app's remaining 98 baselined ids, and they are debt
by design: the baseline ratchets down, never up, and a row gets written when someone has a
reason to write it.

**B12 — the staleness audit flagged every repo, so it informed nothing (MED, done).**
`scripts/audit-staleness.py` reported all seven registered repos as stale. It now
separates the two failures it was conflating: STALE means a MARKED repo has drifted
past the threshold and is the only thing that sets the exit code; UNMARKED and MARKER
BROKEN are setup gaps, reported apart. Reads as two genuinely stale repos, four never
marked, and one whose marker names a sha its rewritten history no longer holds.

The broken marker is repaired. Neither the sha it named nor the batch's start survives the
studio app's rewritten history, so it is now pointed at the last surviving commit whose work
the review record actually describes — deliberately not that day's last commit, since
pointing past the reviewed work would manufacture coverage nobody performed.

What the audit reports now is honest and worth acting on: two STALE repos (this one at 76
commits since its last review, the notes-and-chat app at 47) and four never marked.

**B13 — the comment and decision gates now run on commit (MED, done).**
Both checkers ran only from each repo's validation target and appeared in no
`.githooks/pre-commit` anywhere, so a commit that skipped validation landed over-cap
comments and unrecorded decision ids silently. Both are now gates, in the template, in this
repo's hook, and in all six fleet hooks including the two declared variants.

**The staged-files-versus-whole-repo question was decided by measuring rather than
arguing.** A whole-repo scan is 0.13s on the largest repo here, so the objection this entry
was written around — that it would be slow enough to push people onto `--no-verify` — was
simply false. Whole-repo it is: a staged-only scan passes a file whose over-cap block sits
in a hunk the commit did not touch, and every repo is under the cap today, so scanning
everything costs nothing and keeps it that way.

Counts moved: template 6 to 8, this repo 8 to 10, the studio app's variant 7 to 9. The
coverage table in `docs/GOVERNANCE.md` and every doc pointing at it were updated in the
same commit, which is what `consistency_check.py` requires. The path difference between
this repo's hook and the template is declared in `hook_drift_check.py`: an adopted repo
gets the checkers at `scripts/`, and this repo is where they are authored.

It caught real work within the hour. The studio app had a 36-line nav-latency header whose
three decisions each carried a measurement — nothing to cut, which is exactly the case
`DECISIONS.md` exists for, so the reasoning moved there under `NAV-LATENCY-1` in full.

**B9 — the hook-variant tax compounds (LOW, watch).**
Two fleet repos declare `hookVariant`, so every template gate change needs a hand-merge into
both. That is B3's designed trade-off working correctly, but hand-merging is how a security
fix reaches five repos and misses two. If a third variant appears, switch to the
template-composition option recorded under B3 — a base hook plus declared per-repo gates —
rather than accumulating manual merges.

**B14 — root `QUALITY_BASELINE.md` is mostly restatement (LOW, spec only).**
A full-file duplication pass (2026-09-09) found its process-order, doc-voice, and
redaction lines each restating a rule owned elsewhere (`DEVELOPMENT_LIFECYCLE_STANDARD.md`
+ `EXECUTION_CONTRACT.md`, `docs/DOCUMENTATION_STANDARD.md`, `PUBLIC_PRIVATE_REPO_STANDARD.md`
respectively) — trimmed to pointers in the same pass. What is left after that trim: a
`docs/GOVERNANCE.md` pointer and a "Template Driven Design" section that itself overlaps
`FRAMEWORK_BASELINE.md`'s "Template Directory Architecture" and
`project-standardization-lifecycle.md`'s "Source of Truth" list. The file is also not in
`FRAMEWORK_BASELINE.md`'s "Support" required-file list or `docs/FEATURE_MAP.md`'s Governance
table — only `README.md`'s doc table links it. Candidate to fold its remaining real content
into `FRAMEWORK_BASELINE.md` or `docs/GOVERNANCE.md` and retire the file. Not done here:
retiring a file `README.md`'s table and `consistency_check.py` both reference needs its own
change set, not a drive-by.

**B15 — secret-probe snippet duplicated verbatim in three docs (LOW, judgment call, spec only).**
`README.md` ("Prove the hooks work"), `docs/ADOPTING.md` (Step 7), and `docs/NEW_MACHINE.md`
(step 5) each inline the same `printf 'K="sk-%s"...' | git commit` probe. Possibly
deliberate — `docs/DOCUMENTATION_STANDARD.md`'s own README rule wants a runnable example with
no hop to another file, and each of these three is a self-contained walkthrough for a
different reader (contributor, forker, restorer). Owner call, not a clear defect: keep three
copies for self-containment, or extract to a new probe script under `scripts/qa/` and have
each doc invoke it by name.

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

- 2026-07-27 [audit] Defect fixes + orphan removal, `82145bb`.
- 2026-07-27 [audit] Legacy-reference strip, doc consolidation, specs written, `032b8e2`.
- 2026-07-27 [audit] Path map / baseline rules to one home, `b22cf41`.
- 2026-07-27 [audit] FEATURE_MAP made a real index, `ef99e61`.
- 2026-07-27 [audit] Product paths out of the location contract, lib imports unified, `c1d46b3`.
- 2026-07-27 [audit] Owner decisions: keepalive into scope, `vault-content-parsing` moved to
  the vault, `model-routing` kept as a declared exception. A6/A8 resolved, `7c50960`.
- 2026-07-27 [audit] A1-A5 built: reference integrity, consistency checker, enforcement tests,
  CI gating, `4d0689e`.
- 2026-07-27 [activation] Global CLAUDE.md made path-independent; fleet hooksPath converged;
  5 repo CLAUDE.md pointer blocks repaired; hook-install fail-open closed, `72340e5`.
- 2026-07-27 [fork] Stranger-clone blockers fixed; `docs/ADOPTING.md` + `olivercode-adoption`
  skill added, `d71a663`. Reference gate taught to scan untracked files, `39449a4`.
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
- 2026-07-27 [fork] `olivercode init`, real `--root`, unknown args rejected, `5225bcd`.
- 2026-07-27 [fork] Fork-usability gate built and mutation-tested, `13d6b58`; extended to walk
  the adoption path itself, `ec1ba55`.
- 2026-07-27 [fork] CI-only gates moved onto the local path; Actions pause recorded as policy,
  `c16e0fa`.
- 2026-07-27 [docs] `olivercode install` added; ARCHITECTURE rewritten; INSTALL.md folded into
  README; "what you get and what enforces it" contract added, `b404f5f`.
- 2026-07-27 [necessity] Completion gate stopped asserting a rule nobody runs; QA worktree
  double-count fixed (it was hiding real findings); Gate 8 message made actionable, `4c418ab`.
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
- 2026-07-27 [docs] Readability rules added to the documentation standard — the README had
  drifted into 4-6 line prose walls the standard did not forbid. New section: three
  sentences per paragraph max, never more than two consecutive prose paragraphs without a
  code block or list, the squint test (headers + bold lead-ins + code must carry the whole
  story), one-sentence paragraphs encouraged for the sentence that matters. README
  rewritten to comply: same content and outline, short paragraphs, enumerations converted
  to annotated lists, the fail-open consequences pulled into a scannable list.
- 2026-07-27 [review] Sequential code-review pass over the session's work (one pass, per
  the standing no-fan-out rule). Two confirmed defects, both fixed and pinned by test:
  a waiver written without a timezone crashed the whole health run (min() over mixed
  offset-naive/aware datetimes raises TypeError — reproduced live, then normalized to
  match the expiry loop), and the fleet-leak gate scanned an extension list that missed
  the extensionless hooks and .yml workflows, so a repo name in either would ship to
  every fork unexamined (now scans all tracked text files, binaries skipped by content
  sniff). Open backlog after this pass: B2 (CI billing, external trigger) and the
  hook-variant watch item only.
- 2026-07-27 [audit] Dot-file audit: junk `prompts/` dir removed (held one .DS_Store);
  `.gitignore` comment claimed a skills subdirectory of the Claude OS layer that does not
  exist — corrected; `.env.example`, `.claude/`, `runtime/`, and the memory/state ignores
  verified correct. Comment-longevity rule added to the Code Intent Standard (§4b: past
  tense is stable, present tense drifts; the why stays, perishable specifics go) and
  applied here, in the template hook, and across the fleet's recent comment additions —
  dated decision-IDs stripped in the crawler repo (git blame is the provenance), live-queue
  tallies rewritten as at-the-time evidence in the events repo. Dated batch and incident
  records keep their dates: there the date is the record.

- 2026-07-28 [gate] Comment budget now measures Python docstrings, which were entirely
  invisible while only `#` counted — two 40-line narrative module docstrings had passed.
  Triple quotes pair across the line, because trimming makes a lone closing `"""` identical
  to an opener and reading it as one swallowed the rest of the file; only a region opening
  at a docstring position counts as prose, which leaves triple-quoted SQL as code. Template
  literals are tracked for the same reason: `/*` inside one opened a block that never
  closed. Four blocks fixed here (`3e84cb1`), thirteen in the studio repo, whose own
  commit is `5716d0a` -- named as belonging there, because a bare hash in this file
  reads as a commit in this repo and a reader who checks it finds nothing.
  The gate had no tests anywhere; it now has nineteen, each ablated. Three of them were
  vacuous when first written — they asserted the phrase "over 20 lines", which is a
  substring of the PASS line "no comment block over 20 lines", so they passed on success.
- 2026-07-28 [gate] `docs/DECISIONS.md` added, and `check_decision_ledger` added with it:
  §3 required the ledger and §4 required it to be gated, and this repo had neither. IDs
  inside quoted strings are skipped — a fixture carries one as payload data. The contract
  now names this as the reference implementation it had only described.
