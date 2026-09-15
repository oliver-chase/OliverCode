# Plan: Skill Orchestration Discoverability Audit

Date: 2026-09-15
Related: `Operations Vault/01 - Skills/_BACKLOG.md` (SPEC-21 resolution, SPEC-22 through
SPEC-25), `core/contracts/SKILL_EFFICIENCY_STANDARD.md`, `docs/SKILLS-PLACEMENT.md`,
`docs/BACKLOG.md` (B20)

## Goal

Resuming "SPEC-21" this session took a fleet-wide grep instead of one lookup, because
nothing in the skill orchestration system points an agent straight from a name to its
owner. That incident is a symptom, not the defect. This plan finds and fixes the actual
gaps in how skills across OliverCode's `skills/` and the vault's `01 - Skills/` are
found, created, and kept current, so the next resumption doesn't repeat the same search.

## Findings (verified on disk this session, not estimated)

1. **Spec-ID collisions across repos.** `SPEC-21` exists, unrelated, in both
   `Operations Vault/01 - Skills/_BACKLOG.md` and a fleet product repo's own
   `docs/SPEC_BACKLOG.md` + `AUDIT_BACKLOG.md`. No repo namespaces its IDs. This is what
   forced the grep-and-read-both this session paid for.
2. **Skill-count prose has no mechanical check against reality.** `01 - Skills/
   README.md`, `personal/README.md`, and `.olivercode/user-skills-inventory.md` each
   hand-state a skill count and say it is "kept current" by convention.
   `Operations Vault/_validate_structure.js` computes the real count but never diffs it
   against those claims. Already drifted once (39→37, caught by hand during an
   unrelated merge).
3. **`.olivercode/user-skills/` is stale and orphaned.** Holds real content for
   `frontend-ui-references` and `vault-content-parsing` — both superseded 2026-09-10 by
   `01 - Skills/personal/` (their live `~/.claude/skills/` symlinks already point there,
   confirmed) — plus `voice-humanizer`, retired fleet-wide with no live copy anywhere.
4. **Three OliverCode files still point at that stale path**: `skills/INDEX.md`'s
   Rules section, `core/contracts/FILE_LOCATION_STANDARD.md`'s location table, and
   `docs/EXTERNAL-TOOLING.md`'s routing note — all three say personal/business skills
   live at `.olivercode/user-skills/`, none say `Operations Vault/01 - Skills/`.
5. **No vault-side skill-creation walkthrough.** OliverCode has one for its own
   `skills/` (`docs/SKILLS-PLACEMENT.md`, gated by `validate.sh`'s contract-integrity
   check). The vault has no equivalent — placement, the `~/.claude/skills/<name>`
   symlink, and three separate README/ledger edits are done from memory, with no
   check against `core/contracts/SKILL_EFFICIENCY_STANDARD.md` before shipping.
6. **Structure and MCP-efficiency are audit-only.** `Operations Vault/.githooks/
   pre-commit`, the private variant, runs 4 gates (secret, icon, archived-content,
   ASD-STE100 clarity) — no structure or MCP-efficiency gate. Only clarity blocks a
   commit. SPEC-22 through
   SPEC-25 (49 findings) exist today precisely because nothing forced the check earlier.
7. **No symlink-completeness check for vault skills.** `scripts/olivercode health`
   exhaustively checks OliverCode's own `skills/` against `~/.claude/skills/`, using
   `skills/INDEX.md` as the canonical list. For the vault's skills it only catches a
   symlink that exists but is broken — nothing enumerates `01 - Skills/*/SKILL.md` and
   confirms each one has a symlink at all.
8. **Dead health check.** `scripts/lib/health_checks.py`'s `_check_plugin_links` checks
   a `01 - Plugins/` directory retired 2026-09-10. It now permanently WARN-skips.
9. **Router mechanism, for context.** Skill-tool matching is semantic against each
   `SKILL.md`'s `description` — no deterministic index sits in front of it. README/INDEX
   files are human-facing only. "Router quality" is description precision, and
   `skill-fleet-audit`'s clarity dimension already checks description length. Existing
   coverage, not a new gap — included so the plan doesn't propose rebuilding it.

## Steps

1. **Fix the 3 stale `.olivercode/user-skills/` pointers** (findings 3, 4) —
   `skills/INDEX.md`, `FILE_LOCATION_STANDARD.md`, `EXTERNAL-TOOLING.md` all get
   corrected to `Operations Vault/01 - Skills/`, then delete `.olivercode/user-skills/`
   itself (git holds its history). One small, mechanical change, no design decision
   needed. *Why first: every other fix in this plan assumes the pointer is right, and
   this is the cheapest one to get wrong by skipping.*

2. **Fold gap 7 and gap 8 into one change**: replace `health_checks.py`'s dead
   `_check_plugin_links` (retired directory, never fires) with a `_check_vault_skill_
   links` that reuses its exact shape — enumerate `Operations Vault/01 - Skills/*/
   SKILL.md`, confirm each has a live, correctly-targeted symlink at `~/.claude/skills/
   <name>`, report missing/wrong-target the same way `_check_plugin_links` already
   reports install-vs-broken. *Why together: same code shape, same author decision
   ("what does a healthy symlink layer look like"), no reason to design it twice.*

3. **Disambiguate spec IDs without renumbering history.** Renaming existing SPEC-N
   entries would break every commit message, memory note, and cross-reference that
   already cites them — too disruptive for the problem. Instead: (a) add one line to
   the top of every repo's own backlog file stating its SPEC-IDs are scoped to that
   file only, and (b) write a small `find-spec.sh`/`.py` that greps every known
   backlog file fleet-wide for an ID and prints file + surrounding context, so a bare
   "SPEC-21" resolves in one command instead of a manual multi-file grep-and-read.
   *Why this shape: the pain observed this session was disambiguation cost, not the
   existence of a collision — fixing the lookup is cheaper and less disruptive than
   fixing the naming.*

4. **Extend `_validate_structure.js` to cross-check the hand-written skill count.**
   Parse the count/list `01 - Skills/README.md`, `personal/README.md`, and `.olivercode/
   user-skills-inventory.md` each state, compare against the real folder count the
   validator already computes, fail or warn on mismatch. Closes finding 2 the same way
   `docs-reality-audit`'s doc-vs-code pattern already works elsewhere in this fleet.

5. **Decide: gate structure/MCP-efficiency at commit time, or stay audit-only —
   explicitly, not by default.** Clarity is gated because ASD-STE100 findings are close
   to deterministic. Structure and MCP-efficiency findings are explicitly "likely, not
   confirmed" per the checkers' own stated boundary — gating them risks blocking a
   legitimate commit on a heuristic false positive (exactly what SPEC-21 just found
   twice). Recommendation: keep audit-only, but require `skill-fleet-audit` to run
   before any session that adds or edits a skill closes — a process rule, not a gate,
   until the checkers' false-positive rate is provably low enough to block on.

6. **Build the vault-side skill-creation walkthrough (finding 5) — spec only, not
   built in this plan.** A `meta/` skill or `scripts/new-skill.sh` mirroring OliverCode's
   `SKILLS-PLACEMENT.md` steps: family-folder placement, the symlink, all three README/
   ledger edits, and a `skill-fleet-audit` run against the new skill before calling it
   done. Write this up as its own spec in `01 - Skills/_BACKLOG.md` once steps 1-4 land,
   so it can point at the finished symlink-completeness check (step 2) instead of
   duplicating that logic.

## Risks

- **Deleting `.olivercode/user-skills/` before every reference is fixed** would turn 3
  dangling pointers into 3 pointers at nothing. Mitigation: step 1 fixes all 3 files
  in the same change that deletes the directory, verified by re-running the grep this
  plan used to find them before deleting.
- **Gating structure/MCP-efficiency by default** could block a real commit on a
  checker-acknowledged heuristic finding, the same false-positive class SPEC-21 fixed
  twice this session. Mitigation: step 5 keeps it a process rule, not a gate, until
  the checkers' false-positive rate is known.
- **Renumbering spec IDs to fix collisions** would break every existing commit message
  and memory note that already cites one. Mitigation: step 3 fixes the lookup instead
  of the naming.

## Pressure-Test Findings (2026-09-15)

Every checkable claim above was verified live against the current filesystem and git
state, not re-read from the prose. One correction changes what Step 1 actually removes,
one correction narrows what Step 4 can safely claim to do as a direct edit, and two
claims held exactly as stated.

**Correction — Finding 3 overclaimed what `.olivercode/user-skills/` holds.**
`ls -la` on all three subdirectories (`frontend-ui-references`, `vault-content-parsing`,
`voice-humanizer`) shows each one completely empty — no `SKILL.md`, no files at all,
just `.` and `..`. `git ls-files` and `git check-ignore -v` both return nothing for the
path, which is expected: git cannot track an empty directory, so there was never
anything here for git to hold. Step 1's rationale ("git holds its history") is wrong —
there is no history because there was never any content, not because a commit
preserved it. The action itself is still correct and even lower-risk than stated:
deleting these three empty directories loses nothing, full stop. Fix before executing:
reword Step 1 to say the directories are empty and untracked, not that git backs them
up.

**Checked-good — Step 2's reuse target is real and fits.** `_check_plugin_links` is
defined in `scripts/lib/health_checks.py:159`, imported into `scripts/olivercode` at
line 22-24, and invoked at line 539 inside `command_health` as
`t.add(*_check_plugin_links(vault_root))`. Its signature —
`(vault_root: Path) -> tuple[int, int, int]` (passed, failed, skipped) — is exactly the
shape a new `_check_vault_skill_links(vault_root)` needs, and it drops into the same
file and the same `t.add(*_check_X(...))` call pattern with no adaptation. Confirmed
this is the correct reuse target — the inline OliverCode-skills symlink check inside
`scripts/olivercode` (~line 695-755) is a different, non-extracted local block in
`command_health` itself, not a function, and is not what Step 2 should mirror.

**Correction — Finding 2 / Step 4 overclaims where the skill count actually lives.**
Grepped `01 - Skills/README.md` and `personal/README.md` directly for any fleet-wide
total ("N skills"): neither states one anywhere. Only
`.olivercode/user-skills-inventory.md` does, in one free-form sentence ("plus the 38
skills in..."). `README.md` instead carries separate, narrower claims: per-family
sub-counts in section headers (e.g. "`vtwo-growth/` — Strategic Growth OS, 6 skills that
move together"). Step 4 as written conflates these into one "parse the count each file
states" task, but they're two different problems — one free-form sentence in one file
(mechanical, one regex) versus N per-family header counts scattered across sections
(a real parsing-design decision: what counts as a match, what happens when a family's
count is stated in prose instead of a header). Given that, Step 4 sits closer to Step
6's "spec only" category than to Steps 1-3's mechanical edits. Recommendation: narrow
Step 4's immediate scope to just the one real total in
`user-skills-inventory.md`, and move the per-family header-count check to a backlog
spec alongside Step 6 rather than folding it into this plan's direct-edit set.

**Checked-good — Step 3's premise.** Confirmed the fleet product repo's own
`docs/SPEC_BACKLOG.md` carries 122 real `^#{1,4} SPEC-[0-9]+` headings (counted directly,
not estimated) — the collision risk this step addresses is a substantial, repeated pattern
in a real, actively-used file, not a one-off coincidence.

**Checked-good — the historical plan file is correctly left alone.**
`docs/plans/2026-09-15-audit-fleet-consolidation-and-automation.md` also references the
stale `.olivercode/user-skills/` path (confirmed by grep) but Step 1 does not list it
among the 3 files to correct. That's right, not an omission: per this framework's own
Code Intent Standard (rule 4b, past tense is stable), a dated plan is a historical
record of what was true when it was written, not living documentation — fixing it would
misdescribe what the original plan actually said at the time.

## Execution Log (2026-09-15)

All 6 steps executed same session, approved as-is. Two more corrections surfaced during
execution itself, beyond the pressure-test pass — logged here rather than editing Step
text, per this skill's own protocol.

**Step 1 — done as corrected.** All 3 pointer files fixed; `.olivercode/user-skills/`
removed with `rmdir` (fails loudly on anything non-empty, so the emptiness claim from
the pressure test was verified a second time by the deletion method itself, not just
trusted). Re-grepped afterward: only the two dated plan files still mention the old
path, both correctly left alone.

**Step 2 — done, and reuse went further than planned.** Building
`_check_vault_skill_links` surfaced that its natural home, `iter_fleet`/
`resolve_repo_path`, lived inline in `scripts/olivercode` itself, not in a shared lib —
exactly the kind of single-copy-that-should-be-shared this whole plan is about. Moved
both into `scripts/lib/repo_profiles.py` so Step 3's `find-spec.py` could import them
instead of becoming a third inline copy. One test broke from the move
(`test_source_uses_case_insensitive_comparison`, which read the launcher's own source
text for a string that had moved) — fixed to read the new location; not a behavior
change, a test that was checking a file path instead of a behavior. Ablated the new
check against a fake unlinked skill before trusting it: confirmed the FAIL path fires,
not just the happy path. Live run: 38/38 vault skills correctly linked, 167 framework
tests still pass.

**Step 3 — done, and the tool caught 2 real bugs in itself before shipping.**
`find-spec.py` walks the vault plus every profiled fleet repo for `*BACKLOG*.md` files
with no hardcoded list — first live run against `SPEC-21` printed 14 matches, double
what existed, because the vault-root walk and the separately-profiled fleet repo's own
walk both scanned the same physical files under two different labels. Fixed by refusing
to descend into any nested git repo other than the root being walked. Second bug: `B20`
(OliverCode's own B-series) returned zero matches, because `iter_fleet` deliberately
excludes the framework repo from fleet iteration and nothing added it back as an
explicit search root. Fixed by adding OliverCode's own root explicitly. Both caught by
testing against real, known-answer cases (`SPEC-21`'s known collision, `B20`'s known
existence) before trusting the tool, not by reading the code and reasoning it looked
right. One-line scoping notes added to both files that define `SPEC-N` headings (the
vault's `_BACKLOG.md`, and the other fleet repo's own `SPEC_BACKLOG.md`); `find-spec.py`
documented in OliverCode's own `CLAUDE.md`, which loads in every session on the machine.

**Step 4 — done, but not the way the plan or the pressure test described.** Writing the
cross-check surfaced a simpler fix: the fleet's own Code Intent Standard (rule 5) already
says a volatile number should not live in prose at all, only the command that computes
it. Since `.olivercode/user-skills-inventory.md`'s "38 skills" was the only real
fleet-wide total anywhere (confirmed in the pressure-test pass), removing the number and
pointing at `node _validate_structure.js` instead closes the drift risk completely, with
no parser to maintain and nothing left that can go stale. Checked whether the same move
was cheap for the one per-family count too (`vtwo-growth/`'s header, pressure-test found
this was a single instance, not "N scattered counts" as Finding 2 first described) —
it was: the section already lists all 6 skills by name directly below the header, so the
header's own number was redundant, not load-bearing, and got dropped the same way.
No backlog spec needed for either half of Finding 2; both are closed, not deferred.

**Step 5 — decided, not built.** Recorded the plan's own recommendation (audit-only
stays; a process rule instead of a gate) as a standing instruction in
`Operations Vault/CLAUDE.md`, next to the existing `_validate_structure.js` rule it
extends.

**Step 6 — spec'd, not built, as planned.** Added SPEC-26 to the vault's
`01 - Skills/_BACKLOG.md`, pointing at Step 2's finished symlink-completeness check so a
future build does not reimplement it.

## Definition of Done

- [x] `skills/INDEX.md`, `FILE_LOCATION_STANDARD.md`, `EXTERNAL-TOOLING.md` all point at
      `Operations Vault/01 - Skills/`; `.olivercode/user-skills/` deleted
- [x] `health_checks.py` has a live vault-skill symlink-completeness check; the dead
      plugin-links check is gone
- [x] Every repo's backlog file states its SPEC-IDs are locally scoped; a `find-spec`
      lookup script exists and is documented in at least one CLAUDE.md
- [x] The one real skill-count claim (`.olivercode/user-skills-inventory.md`) and the one
      real per-family count (`README.md`'s `vtwo-growth/` header) both point at the live
      count or the list itself instead of a hand-maintained number — no cross-check
      script needed because there is no longer a number to drift
- [x] The structure/MCP-efficiency gate-vs-audit-only decision is made explicitly and
      recorded (this plan's step 5, or Kiana's own call if different)
- [x] A spec for the vault-side skill-creation walkthrough exists in `01 - Skills/
      _BACKLOG.md`, referencing the finished symlink-completeness check
