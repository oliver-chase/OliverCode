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
  registries (`shared/*.example.json`, placeholder `shared/repo-map.json` etc.). The real
  fleet lives in gitignored `local/` copies. Loaders try the local overlay first and fall
  back to the tracked example with a WARN. Personal data never enters tracked files.
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
  gitignored local layers, placeholder tokens, template files, and the anti-pattern examples
  in `FILE_LOCATION_STANDARD.md` (whose paths must NOT resolve).
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

### Where things stand (2026-09-09)

The 2026-07-27 audit below is history, not current state — a full doc-dedup pass, a
governance self-assessment, and a code-level deep-review all ran since, closing the gap
between "last reviewed" and HEAD.

- **Doc duplication, twice.** A full manual read found the same rule restated across four
  doc pairs with no cross-reference (process sequence, trigger routing, story-ID rule,
  `QUALITY_BASELINE.md`'s near-total restatement) — all collapsed to one owner each (B10-B15
  is the earlier chapter. B14/B15 above are this one).
- **Duplication now has a mechanical gate**, not just a periodic manual read.
  `scripts/lib/duplication_check.py` (`GATE-DUPLICATION-1`) is wired into `validate.sh` and
  caught three more real duplicates its own first live run found (B16).
- **`audit-staleness.py` is now scheduled**, not just runnable — weekly cron alongside the
  already-scheduled `health` check (B17). Its own first live run is what flagged this repo
  stale and triggered the deep-review below.
- **Deep-review of `4c418ab..HEAD`** (93 commits): mechanical QA (`full-qa-pass.sh`) clean,
  one review agent read the code-risk surface. Six real findings, all fixed same-session —
  highest-cost first: an unscoped `git commit` in the secret-probe script that could sweep
  in unrelated staged work, a silent backup-clobber on a third install collision, the new
  duplication gate landing with zero tests (now six, ablation-proven), the test-coverage-map
  checker being silently inert for this repo's own Python layout (the reason the gap above
  went undetected), two CLI commands skipping the unknown-argument rejection every sibling
  command has, and a cosmetic double-invocation in `validate.sh`. A seventh, unprompted:
  `link-plugins` and `health`'s plugin-link check were both pointed at a vault path that
  moved 2026-08-31 — link-plugins was silently non-functional on this machine until fixed.
- **Coverage-map fix surfaced five more untested `scripts/lib/*.py` modules** (not part of
  this range, pre-existing) — specced, not built. See the live tracker below.

Nothing here blocks a fork. Everything found this session was fixed in the same session,
with a live-run or an ablation as evidence, not a claim.

### Coverage

Reviewed through: `c996e58` (2026-09-09, deep-review of `4c418ab..HEAD`)

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
   half of this class. A comment that describes the wrong function WITHOUT claiming
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
   file. Audit those first. Do not assume a long block in a library is worth cutting.

   That sample was drawn twice. The first pass ran while the scanner was hiding
   comments, so it was re-run after the fail-open fix: the block rankings were
   identical, which is what makes the conclusion safe to keep. Density figures
   recorded before that fix are understated and should not be compared against
   anything measured after it.

   The crawler's `// ─── Title ───` banner is its convention, on 46 of 48 src files,
   and names the CONCEPT rather than the filename. Left as is — stripping it from a
   few files buys nothing and costs consistency. Not a finding. Do not re-litigate.

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
   mostly fine, number in the thousands, and nothing gates them. The two rounds of
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
  `AREA-TOPIC-N` exactly. Harmless while the gate ran from a validation target. With the
  gate in the hook, every story reference in a comment blocked a commit. Excluded by AREA
  rather than by id, so a new story needs no config edit, and by first segment rather than
  prefix, so `USER-FACING-1` is still a decision.
- **Rows written where a reader would otherwise undo the decision.** The studio app cited
  106 ids against an empty ledger. Eight rows now cover the load-bearing ones and the
  baseline stands at 98. Not a backfill — a row per id would manufacture a hundred
  restatements, which is the defect this framework exists to prevent.

What is still open is only the studio app's remaining 98 baselined ids, and they are debt
by design: the baseline ratchets down, never up, and a row gets written when someone has a
reason to write it.

**B12 — the staleness audit flagged every repo, so it informed nothing (MED, done).**
`scripts/audit-staleness.py` reported all seven registered repos as stale. It now
separates the two failures it was conflating: STALE means a MARKED repo has drifted
past the threshold and is the only thing that sets the exit code. UNMARKED and MARKER
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

**B14 — root `QUALITY_BASELINE.md` was mostly restatement (LOW, done).**
A full-file duplication pass (2026-09-09) found its process-order, doc-voice, and redaction
lines each restating a rule owned elsewhere. First trimmed to pointers. On the owner's
"do backlog" pass, resolved further: the "Framework-Level Quality Gates" and "Template Driven
Design" sections were cut outright — the first was pure pointers by then, the second
duplicated the file's own "Source of Truth" + "Rule" sections sitting directly above it.
The file was NOT retired, despite the original finding suggesting it: the hygiene contract's
(since merged into `core/contracts/PROJECT_STRUCTURE_STANDARD.md`'s "Shared Quality Baseline
Hygiene" section) "Required shared quality baseline hygiene" section names this file
specifically as the owner of "what the managed files are, and the change-canonical-first
rule" — a real inbound citation the first pass missed by not reading that contract closely
enough. What's left is exactly the content that citation names: title, Source of Truth list,
Rule.

**B15 — secret-probe snippet duplicated verbatim (LOW, done).**
Grepping for the actual snippet (`leak-probe.txt`) on the "do backlog" pass found it in
three files, not the four the audit claimed — `README.md` never inlined it, only described
the rehearsal in prose and pointed at `docs/ADOPTING.md`. The three real copies
(`docs/ADOPTING.md` Step 7, `docs/NEW_MACHINE.md` step 5,
`skills/olivercode-adoption/SKILL.md` step 7) are now one script,
`scripts/qa/probe-secret-gate.sh`, invoked by name from all three. Verified live against this
repo: writes the fake secret, commit is blocked, cleans up, exits 0.

**B16 — no mechanical duplication gate. Doc-vs-doc drift only caught by a full manual
read (HIGH, done).** The owner asked what would make this framework's governance
actually better. The honest answer included "duplication regrows even after an audit,
and nothing mechanical watches for it" — verified true within the same session (B14/B15
were fresh regrowth in a repo dedup-audited weeks earlier). Built
`scripts/lib/duplication_check.py` (`GATE-DUPLICATION-1` in `docs/DECISIONS.md`): slides
a 15-word window across every tracked markdown file, fails on any window shared by two
files unless it matches a declared canonical-reuse marker. Wired into
`bash scripts/validate.sh` as its own step. First live run found three real undeclared
duplicates the manual read had missed (hook-enforcement-fails-open restated in
`ARCHITECTURE.md` + `docs/ADOPTING.md`, boundary-tests-over-volume restated in
`CODE_INTENT_STANDARD.md` + `DEVELOPMENT_LIFECYCLE_STANDARD.md`, structure-drift-audit
restated in `PROJECT_STRUCTURE_STANDARD.md` + `project-standardization-lifecycle.md`) —
all three fixed in the same session, each collapsed to one owner + a pointer. Ablated:
neutering a declared marker makes the gate re-detect the real duplicate it was masking.
Restoring it returns to clean. `bash scripts/validate.sh` green after.

**B17 — `audit-staleness.py` existed but nothing ran it (HIGH, done).** `olivercode
health` was already cron'd weekly (Mondays 9am, `~/.oliver_runtime/logs/health.log`) —
the staleness checker was not, so a repo's review coverage could silently rot with
nobody watching, the same failure class B12 already named once. Added
`5 9 * * 1 python3 ".../OliverCode/scripts/audit-staleness.py" >>
"~/.oliver_runtime/logs/audit-staleness.log" 2>&1` to the crontab, right after the
existing health line — verified the diff touched exactly that one line, nothing else in
a crontab shared with unrelated SDR automation. Live-run before scheduling: real signal,
not hypothetical — it flagged OliverCode ITSELF as STALE (92 commits since the last
`deep-review`, `4c418ab`). Not resolved here. That's a separate `deep-review` pass, not a
governance-tooling fix, and is the owner's call on when to run it.

**B18 — deep-review of `4c418ab..HEAD`, six real findings, all fixed (done).** Triggered
by `audit-staleness.py`'s first live run flagging this repo itself STALE. Mechanical QA
(`full-qa-pass.sh`) ran clean first. One review agent then read the code-risk surface
(`scripts/olivercode`, the new lib modules, `validate.sh`, the new QA/test files). Fixed in
cost-of-being-wrong order:

- `scripts/qa/probe-secret-gate.sh`'s `git commit -m probe` had no pathspec, so it would
  commit the *entire staged index*, not just the probe file — a real silent-data-loss shape
  for a script meant to run in a live working repo. Fixed: `git commit -m probe -- leak-probe.txt`.
  Verified live: still blocks correctly, and a modified-but-unrelated file in the working tree
  is left untouched.
- `scripts/olivercode`'s `install` backup chain (`BACKUP-COLLISION-1`) silently overwrote the
  second backup on a third real-file collision at the same path — `Path.rename` clobbers its
  destination on POSIX, and the fallback only had two names. Fixed: count suffixes until a
  free name is found. Not observed live, found in review.
- `scripts/lib/duplication_check.py` shipped with zero tests, unlike every sibling gate this
  session added — the exact falsifiability gap this repo's own history keeps naming. Added
  `tests/test_duplication_check.py`, six cases. Ablated twice: broke `check_all` to always
  return clean (2 tests correctly went red), and reused the same neuter-a-marker ablation
  already proven by hand when the gate was built, now automated.
- `scripts/qa/check-code-quality.sh`'s Test Coverage Map (`COVERAGE-MAP-1`) globbed
  `lib/*/` — one directory per module — which silently matches nothing against this repo's
  flat `scripts/lib/*.py` layout, so it always reported clean regardless of truth. This is
  why the gap above shipped invisibly through "mechanical QA ran clean." Fixed: a parallel
  pass matching each test file's actual `importlib` load string, not filename substring
  (tried first, produced false positives — tests here are named by behavior, not by module).
- `scripts/olivercode`'s `skills` and `link-plugins` commands skipped the unknown-argument
  rejection every other command has (`_reject_extra`). Fixed both. Live-verified `--typo`
  now errors on each while valid usage (`--grep`, `--dry-run`) still works.
- `validate.sh`'s `run_comment_budget()` ran a comment-budget check plus an unrelated
  decision-ledger check under one function name, and double-invoked `check-decisions.mjs`
  on the failure path. Split into
  `run_comment_budget` + `run_decision_ledger`, single output capture. Ablated: removed a
  real ledger row, confirmed the exact FAIL line surfaces correctly, restored.

**Unprompted, found while verifying `link-plugins` live:** both it and `health`'s plugin-link
check pointed at `Work Vault/06 - Strategy/_Plugins`, which moved to
`Operations Vault/01 - Plugins` on 2026-08-31 — `link-plugins` was completely non-functional
on this machine since. Fixed both call sites. Live-verified `health` now reports "all 4
plugins linked" instead of a false WARN.

Also surfaced, not built here: the coverage-map fix found five more `scripts/lib/*.py`
modules with no direct test file (`health_checks.py`, `reference_check.py`,
`repo_profiles.py`, `skills_catalog.py`, `token_policy.py`) — pre-existing, outside this
range, real coverage may exist indirectly through `tests/test_launcher_commands.py`'s
whole-launcher load for the ones the CLI re-exports, unverified per-module. See B19.

`bash scripts/validate.sh` and `bash scripts/qa/full-qa-pass.sh` both green after every fix
above (167 tests, up from 161).

**B19 — five `scripts/lib/*.py` modules with no direct test file (LOW, spec only).**
Surfaced by B18's coverage-map fix, not part of the reviewed range. `health_checks.py`,
`reference_check.py`, `repo_profiles.py`, `skills_catalog.py`, `token_policy.py`. Some may
already be exercised indirectly — `skills_catalog.py` and `health_checks.py` are re-exported
through `scripts/olivercode` and `tests/test_launcher_commands.py` /
`test_hook_install_health.py` load the whole launcher — but none has a test that loads it
directly by its own `scripts/lib/<name>.py` path the way every other lib module now does.
Not built here: five test files is a separate session's work, not a quick win.

**B20 — OliverCode's own `skills/` has no structure/MCP-efficiency gate (MED, spec only).**
`core/contracts/SKILL_EFFICIENCY_STANDARD.md` sets a fleet-wide bar (no monolith
`SKILL.md`, no duplicate paragraphs, MCP-call efficiency by named pattern) but the only
mechanical enforcement is the vault's `Operations Vault/01 - Skills/skill-governance/skill-fleet-audit`,
scoped to `01 - Skills/` and not runnable against this repo's own `skills/` as shipped —
it resolves paths relative to a `01 - Skills/`-shaped tree. Port its 3 checkers
(`check_skill_structure.py`, `check_mcp_patterns.py`, `check_clarity.py` is already
covered fleet-wide by the ASD-STE100 gate) into a repo-local script under
`scripts/lib/` that walks `skills/*/SKILL.md` instead, and wire it into `validate.sh`.
Not built here: a new checker plus a `validate.sh` gate is a separate session's work, not
a quick win.

**B21 — gate-count drift, invisible to the mechanical checker (HIGH, done).**
`ARCHITECTURE.md:15` states "Pre-commit gates — six in an adopted repo, eight in
OliverCode itself." `core/contracts/FRAMEWORK_BASELINE.md` (line 93) separately lists the hook as
"8 checks" and names only 8, omitting backlog hygiene, archived-content, and writing-clarity
entirely. The real counts, per `.githooks/pre-commit`'s own `Gate N/11` markers and
`docs/GOVERNANCE.md`'s table, are nine (adopted) and eleven (OliverCode) — the numbers
`README.md:278` already states correctly. `scripts/lib/consistency_check.py` (the GATES
check, built for exactly this failure class per A3) does not catch either line: its regex
requires the number immediately before the word "gates," and both lines put the number
before "in" / "checks" instead. Fix both lines to nine/eleven, and widen the checker's
regex to catch this phrasing, or it drifts again the same way.

**B22 — two unreconciled backlog paradigms, no routing rule (HIGH, done).**
`core/contracts/PROJECT_STRUCTURE_STANDARD.md` and `core/templates/project/docs/repo-structure-contract.md`
mandated a file-based `.github/user-stories/<project>/US-*.md` story system and stated
"backlog.md is retired as an active planning filename." `docs/DOCUMENTATION_STANDARD.md`
required `docs/BACKLOG.md` as the standing file, and neither side named the other or said
which wins. Checked against the live fleet before deciding — not a guess: both systems are real and
currently populated. Three fleet repos have genuine, populated
`.github/user-stories/<project>/US-*.md` files under the file-based contract. Seven other
repos have a real `backlog-config.json` and use the GitHub Project board instead — one
of those seven still carries an inert `.github/user-stories/README.md`, left over from
before its own history shows the commit that moved it off the file-based system. Deleting
the file-based contract would have orphaned three live repos' real content; declaring either
side the sole winner would have been false. Decision:
scope, not delete. `PROJECT_STRUCTURE_STANDARD.md` and `repo-structure-contract.md` now state
up front that a repo naming a `backlog-config.json` uses the GitHub Project board instead and
this contract doesn't apply there; `docs/DOCUMENTATION_STANDARD.md`'s backlog policy (B23)
now states the GitHub Project board is the default for a newly bootstrapped repo, and this
file-based contract stays in force, unchanged, for a repo that already adopted it. See B42
for the gap this surfaced in `olivercode-adoption` and the bootstrap manifest.

**Follow-up, same day: the file-based system is now fully retired, not just scoped.** Read
all three holdout repos' stories before touching anything: two of the three (6 and 9
stories) were already Done/Complete with real commits, so there was no open work to carry
over -- deleted outright. The third (19 stories) was genuinely open with real dependency
chains and milestones, so each story became a GitHub Issue (title, body, Acceptance
Criteria preserved verbatim), with a new Project, 5 milestones matching the live tracker's
own milestone groupings, 14 epic labels from each story's own Epic field, and every
dependency chain added as a "Blocked by #N" comment once issue numbers existed. A fourth
repo, not one of the three originally found, turned up the same inert
`.github/user-stories/README.md` leftover B22 already flagged in passing -- deleted too.
With the holdout count at zero, `PROJECT_STRUCTURE_STANDARD.md`'s file-based sections
(Story Artifact Rules, Path Map, Allowed Repo Profiles, Story Path Flow) were removed
rather than kept dormant, since nothing reads them now, and the bootstrap manifest's
`.github/user-stories/` template scaffold was deleted so no future repo gets stamped with
it. Closes B42.

**B23 — documented backlog policy contradicted BACKLOG.md's own shape (MED, done).**
`docs/DOCUMENTATION_STANDARD.md` stated "`docs/BACKLOG.md` holds open work only... History
lives in git... No archive sections accumulating." This file carries a "Design decisions," a
"Resolved — the A-series," and a "Deliberately kept / decided" section, all explicitly
historical and defended in its own prose ("kept because each entry records the failure class
the gate exists to stop"). Rewritten to state the rule it actually enforces — a bounded
decision-rationale and resolved-failure-class record is allowed; genuinely finished busywork
still gets deleted — instead of asserting "open work only." Also scoped the whole backlog
policy and the README table's `docs/BACKLOG.md` row to repos with no `backlog-config.json`,
per B22.

**B24 — structure/hygiene contracts had no OliverCode carve-out, and OliverCode didn't
comply with what they mandated (MED, done).** `core/contracts/PROJECT_STRUCTURE_STANDARD.md`'s
scope is "All project repositories under `<vault-root>/Oliver/Project Repos/*`" — the exact
path OliverCode itself sits at — with no exclusion, and it mandates `.github/user-stories/`,
root `docs/repo-structure-contract.md`, and `package.json`-based `npm run check:structure`.
None of these exist in OliverCode (confirmed by `find`). The hygiene rules then living in a
separate `PROJECT_HYGIENE_STANDARD.md` had the same gap for `qa:hygiene`, before that file
was merged into this one (see the activity log). `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md` (lines 5-10)
already carries the needed sentence — "Does not apply to OliverCode itself" — add the
identical carve-out to both files, or a reader reasonably concludes OliverCode violates its
own contract.

**B25 — FILE_LOCATION_STANDARD.md pointed personal/voice content at a dead path (MED, done).**
`core/contracts/FILE_LOCATION_STANDARD.md` (lines 18,28,56) maps personal/voice content to
`private-runtime/voice/`. That path appears nowhere else in the tracked tree — not in
`.gitignore`, not in any script, not in any other doc. The real, working voice mechanism is
`~/.claude/skills/shared-company/voice/baseline.md`, loaded via this repo's own `CLAUDE.md`
"## Voice" section. Remove the row or rewrite it to point at the real mechanism.

**B26 — a real fleet repo's name and metrics are leaked into a contract every fork inherits
(LOW, done).** `core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` (lines 22-24) names
"Fallow" by name with real line-count metrics (141,801 lines; 13,000 build artifacts; 11,140
one backlog file) as a worked example. `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md`'s own
redaction rule requires project-name placeholders in files every fork ships. Replace the real
name with `[repo-name]` and keep the line-count shape as an illustrative, non-attributed
example.

**B27 — CLAUDE.md restated EXECUTION_CONTRACT.md's pipeline instead of citing it (LOW, done).**
`CLAUDE.md`'s "## Pre-Commit" section prints "CODE→DOCS→AUDIT→QA→GATE→COMMIT→PUSH," the same
7-stage pipeline `core/contracts/EXECUTION_CONTRACT.md` (lines 16-47) already owns as a detailed
diagram. `CONTRIBUTING.md`'s "Required Workflow" section does this correctly — it names the
contract instead of reprinting the chain. Make `CLAUDE.md` do the same, so a stage rename
only has to be caught in one file.

**B28 — stale path `meta/skill-fleet-audit`, repeated in five places, two of them real code
(MED, done).** `core/contracts/SKILL_EFFICIENCY_STANDARD.md`, `docs/BACKLOG.md`, and
`scripts/local-scheduler/README.md` all cited `meta/skill-fleet-audit` as the skill's path.
It actually lives at `Operations Vault/01 - Skills/skill-governance/skill-fleet-audit/`
(family `skill-governance`, not `meta`) — confirmed on disk. The alias also showed up in
`scripts/olivercode`'s and `scripts/lib/health_checks.py`'s own docstrings, comments, and an
error message — the actual path construction in `command_audit_fleet` was already correct,
so this was cosmetic drift, not a functional bug. Fixed all five in one pass, per
this framework's own rule 2 for duplicate findings.

**B29 — skills/INDEX.md's `writing-documentation` row broke its own table (LOW, done).**
The table declares three columns (`Skill | Domain | Load When`); the `writing-documentation`
row collapses Domain and Load When into one cell with no closing `Load When` value. Split it
into its own Domain and Load When cells to match every other row.

**B30 — `backlog-management/SKILL.md` restated its own frontmatter, and loaded a full
incident narrative on every filing (LOW, done).** The body's "Which repo, which config"
section ("This skill is repo-agnostic. It never hardcodes...") was a near-verbatim
restatement of the frontmatter description one paragraph above the `---` — cut. Separately,
step 6 embedded a full incident narrative (the ad-hoc deletion precedent, "19 other
closed-work plan docs") inline in the main procedure, loaded on every single filing though it
only mattered for the rare "should I delete this plan doc" branch — moved to
`references/plan-doc-deletion.md`, leaving only the operative rule in the body.

**B31 — template QUALITY_BASELINE.md's Sync and Audit sections gave the identical,
undifferentiated command (LOW, done).** `core/templates/project/QUALITY_BASELINE.md` labeled
two sections "Sync Command" and "Audit Command," both showing `.githooks/pre-commit` with no
distinction of what each actually checks or changes. Renamed to the two real, distinct
commands (`scripts/olivercode sync-hooks` / `scripts/olivercode health`) that
`core/workflows/project-standardization-lifecycle.md` already uses for this exact split.

**B32 — two procedure pairs covered identical ground with no cross-reference (MED, done).**
`core/workflows/story-lifecycle-sop.md` and `skills/backlog-management/SKILL.md` both walk
"intake gate, status fields, acceptance criteria, close with evidence" in different
vocabulary, and neither names the other — `core/workflows/README.md` points only to the SOP,
so a reader never learns the GitHub-Project skill exists. Separately,
`core/workflows/project-standardization-lifecycle.md`'s step 1 independently restates
`skills/olivercode-adoption/SKILL.md`'s bootstrap/sync-hooks/registration steps, with neither
file pointing at the other. Added a cross-reference each way instead of a full content merge: the SOP now scopes
itself to repos without `backlog-config.json` and points to `backlog-management`; the
lifecycle workflow's step 1 and `olivercode-adoption`'s step 6 now point at each other
(human-decision version vs. mechanical version of the same step). A full merge, if ever
needed, stays a separate decision.

**B33 — MANUAL_SETUP.md restated the README's load order before its real content started
(LOW, done).** `core/templates/project/docs/MANUAL_SETUP.md`'s steps 1-2 repeated
`core/templates/project/docs/README.md`'s load order (README → SETUP_MODES → MANUAL_SETUP →
product docs) verbatim before step 3 reached the actual env-file setup. Dropped steps 1-2;
content now starts at the env-file step.

**B34 — `repo-audit-with-execution-batches/SKILL.md` restated its own hand-offs twice in one
file (LOW, done).** Batch 3's and Batch 6's inline hand-off sentences (to `docs-reality-audit`
and `/security-review`) are restated almost verbatim in the file's own "Complementary Skills"
section at the bottom. Cut the inline sentences; the bottom section already owns this list.

**B35 — two template doc stubs had zero callers anywhere in the framework (LOW, done).**
Two files under `core/templates/project/docs/` — a `product/README.md` and a
`tech-debt/README.md` — were two-line stubs ("keep this aligned with X") that `grep -rn`
across `core/`, `skills/`, and `docs/` found no reference to outside the files themselves —
nothing instructed an agent to read or write them. Removed from the template and from
`shared/project-bootstrap-manifest.json`'s
`requiredDirectories`/`templatedFiles`.

**B36 — `docs/OLIVERCODE_LAUNCHER.md` miscounts its own command surface and omits two real
commands (HIGH, done).** The doc listed 9 bullet commands, then stated "these 8 commands are
the entire surface" — wrong even against its own list. `scripts/olivercode` implements 11
(`grep -n 'if cmd ==' scripts/olivercode`): `audit-fleet` and `push-fleet` were real, used
commands missing from the doc entirely. Rewritten with all 11 commands, pulled from the code,
and the count fixed.

**B37 — the launcher command list disagreed across three sources, and one doc used a dead
field name (MED, done).** `docs/FEATURE_MAP.md`'s launcher row listed a third, different
subset of the same 11 commands (it had `audit-fleet`/`push-fleet`, which B36's doc was
missing, but itself omitted `link-plugins`, which `docs/NEW_MACHINE.md` actually invokes by
name). Fixed in the same pass as B36, so code, `FEATURE_MAP.md`, and `OLIVERCODE_LAUNCHER.md`
now agree. Separately, `docs/GOVERNANCE.md` called the downstream validation field
`validate:merge` — that name exists nowhere in the repo. The real field, used correctly in
`docs/NEW_MACHINE.md` and `shared/repo-profiles.example.json`, is `canonicalValidationCommand`
— fixed. `docs/FEATURE_MAP.md`'s separate mention of `scripts/validate-repo.sh` was checked
against the original finding and found correct as written: `scripts/validate.sh
--target-repo` really does exec that filename by convention (per D2 above) — left as is, not
the same mechanism as `canonicalValidationCommand`.

**B38 — `docs/GOVERNANCE.md` was the single most duplication-heavy file found, six separate
ways (MED, done).** (1) Its `hookVariant` trade-off anecdote was duplicated near-verbatim in
`shared/repo-profiles.example.json`'s `_hookVariant_note` — invisible to
`duplication_check.py` since one side is JSON. Cut here; the file now points to the JSON
note as the one home. (2) It retold the `GATE-FALSIFIABILITY-1` story from
`docs/DECISIONS.md` in full instead of citing it by ID, the exact thing that ledger exists to
prevent — now cites it. (3) The CI-pause policy was explained in full prose three times with
no shared owner — here, in `docs/ADOPTING.md`, and in `docs/FEATURE_MAP.md` — each calling
the JSON block "canonical" but none pointing to this file's own fuller version. This file
keeps the explanation; the other two now point here. (4) "What Must Stay True" was
unfalsifiable bullets naming no check or owner, overlapping `docs/FEATURE_MAP.md`'s Non-Drift
Rule — removed. (5) "Backend Enforcement (Supplementary)" restated facts already given
earlier in the same file — folded into the earlier section, heading removed. (6) "Required
Gate Runner" told the reader to run bare `.githooks/pre-commit`, three lines above "Unified
Validation Entrypoint" presenting the real sanctioned command — removed as redundant and a
risk of running the weaker check.

**B39 — KEEPALIVE_STANDARD.md's new-repo checklist pure-restated the section above it (LOW,
done).** `docs/KEEPALIVE_STANDARD.md` (lines 100-109)'s 7-step "Adding a New Repo" checklist repeats,
point for point, the more precise wiring table and commands already given at lines 24-83.
Replaced with a one-line pointer to the per-deployment-type steps above.

**B40 — EXTERNAL-TOOLING.md understated the writing-clarity gate's real scope (LOW, done).**
`docs/EXTERNAL-TOOLING.md` (line 21) says the gate covers staged `SKILL.md`/`CLAUDE.md` only. Per
`docs/DECISIONS.md`'s `GATE-SCOPE-1` and `docs/GOVERNANCE.md`'s own table, the gate was
deliberately extended to also cover `references/*.md` after a real violation went undetected
there. Fixed to match.

**B41 — TROUBLESHOOTING.md's "Command not found" section didn't address that failure (LOW,
done).** The section's only content is "run `scripts/olivercode --help`" plus an unrelated
aside — it never names the actual cause (no PATH alias, wrong cwd) or gives a verification
step. Rewritten to name the real cause (no PATH alias, must run from inside the clone).

**B42 — `olivercode-adoption`'s four human decisions didn't cover which backlog paradigm a
repo uses, and bootstrap stamped the file-based scaffold into every new repo regardless
(MED, done).** Closed by deleting the thing instead of making its stamping conditional: with
every holdout repo migrated to a GitHub Project (B22's follow-up), the file-based backlog
paradigm no longer exists anywhere in the fleet, so the manifest's `.github/user-stories/`
template entries were removed rather than gated behind a fifth adoption decision that would
have had only one real answer left. `olivercode-adoption`'s four decisions stay four.

### Deliberately kept / decided (do not redo)

- `core/templates/project/pre-commit` intentionally differs from `.githooks/pre-commit`: the
  OliverCode copy adds Gate 6 (contract integrity) and Gate 8 (token policy). The template
  carries the anon-key meta-tag allowlist. Both correct. Do not converge them.
- `core/contracts/AGENT_SYSTEM_MANIFEST.json` looks like a duplicate of
  `docs/FRAMEWORK_BOUNDARY.md`'s path map but is the tracked half of the G1 example/overlay
  pair and has a real `local/` counterpart. Keep both.
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
  admission criteria. The real sharp edge was Gate 8 failing with an unactionable message.
  That is fixed. Revisit only if fleet size makes the edit genuinely repetitive.
- The governance CI pathway (`scripts/run-governance-target.sh` +
  `core/templates/project/.github/workflows/olivercode-governance.yml`) is absent from every
  fleet repo today. That is the billing pause, not dead code — it is a working path the moment
  CI returns. Keep.
