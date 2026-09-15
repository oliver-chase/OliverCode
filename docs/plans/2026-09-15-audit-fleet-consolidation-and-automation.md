# Plan: Audit Fleet Consolidation + Scheduled Automation

Date: 2026-09-15
Related: this session's `skill-usage-audit` findings and hook-drift fixes (OliverCode
`6b5543b`, `d5d3dbe`); `docs-reality-audit`'s new `references/` split (same session,
precedent for progressive disclosure); `fallow/scripts/local-scheduler` (launchd pattern,
including its documented duplicate-scheduler incident); `Operations Vault/01 -
Skills/vtwo-ops/meeting-notes` (existing router precedent, different shape — see Step 2).

Cross-repo note: this plan is centered on OliverCode (the CLI already owns fleet iteration
via `repo-profiles.json`/`_iter_fleet`, and both the scheduler and push-automation are
OliverCode-CLI features), so it's filed here per the plan skill's own repo-ownership rule.
Steps 2 and 6 touch `Operations Vault/01 - Skills/` directly.

## Goal

OliverCBot asked for four related things in one message:

1. Restructure the 4 overlapping "audit my skills" tools (`personal/skill-structure-audit`,
   `personal/skill-usage-audit`, `personal/mcp-efficiency-audit`, and `_audit.py` — a bare
   script, not a skill) into something coherent, mirroring how the vault already organizes
   things.
2. Make them run together by default — asking for "an audit" should not require knowing 4
   separate tool names exist.
3. Run that composed audit on a schedule, unattended.
4. Push commits across the fleet + vault on a schedule too, unattended — no per-push ask.

Work Vault's `06 - Strategy` root cleanup (7 misfiled files, found earlier this session) is
explicitly out of scope here — deferred, handled separately later.

## Step 1 — Confirm there's no real overlap to resolve first

**What:** Read `_audit.py` in full before designing around it.
**Why:** Can't merge 4 tools into 1 orchestrator on a guess about what each one checks.
**Outcome (done during planning):** Confirmed. `_audit.py` does exactly 2 things — runs
`ste-lint.py` (writing clarity) against every `SKILL.md`, and checks each skill's
`description` field against a word-count cap. Zero overlap with the other 3:
`skill-structure-audit` checks structure/duplication/workflow shape,
`mcp-efficiency-audit` statically scans documented MCP call patterns,
`skill-usage-audit` traces a real session's actual tool calls. Four genuinely distinct,
complementary dimensions — the fragmentation is real, the redundancy isn't.
**Risk:** None — this step is read-only.

## Step 2 — Merge into one skill, not a router-in-front-of-4

**What:** Build one new skill (working name `skill-fleet-audit`) whose `SKILL.md` runs all
4 checks by default and merges them into a single report, rather than a thin router that
picks exactly one (the `meeting-notes` pattern).
**Why:** `meeting-notes`'s router picks exactly one document type because blending types is
explicitly banned there. These 4 audits are the opposite — they're complementary, non-
exclusive dimensions of the same question ("is my skill fleet healthy"), so a caller asking
for "an audit" wants all 4, not a menu. Composing them as one skill also directly satisfies
ask #2 (no one dimension runs alone) without adding a 5th installed/symlinked thing on top
of the existing 4.
**Concrete moves:**
- New skill at `Operations Vault/01 - Skills/meta/skill-fleet-audit/` (new family folder —
  see Step 3 for why `meta/`, not `personal/`).
- `scripts/check_skill_structure.py`, `scripts/check_mcp_patterns.py`, and `_audit.py`'s
  two checks (ste-lint + description word count) become internal scripts/modes this one
  skill's `SKILL.md` calls in sequence — not 3 separate skill directories any more.
- `skill-usage-audit`'s real-session trace stays a distinct fourth mode inside the same
  skill (it can't be merged mechanically with the other 3 — it needs the live conversation
  — but it's still one skill with 4 modes, not 4 skills).
- `SKILL.md`'s own Process section: run structure-audit + mcp-efficiency-audit + the
  ste-lint/description sweep unconditionally every invocation (they're cheap, static,
  fleet-wide); run the usage-audit mode only when the request is scoped to "this session" /
  "that task" (its own stated same-session boundary doesn't change).
- Delete the 3 old skill directories and `_audit.py` once the merge is verified against the
  same fixtures each one already has (don't re-invent tests — port them).
**Risk:** A caller who wants only one dimension (e.g. just the MCP-efficiency check) now
gets all 4 → mitigate with a `--only structure|mcp|usage|clarity` flag on the merged skill's
script entry point, default (no flag) = all 4.

## Step 3 — New family folder: `meta/`, not `personal/`

**What:** Create `Operations Vault/01 - Skills/meta/` as a new family folder alongside
`vtwo-ops/`, `vtwo-hr/`, `vtwo-gtm/`, `vtwo-growth/`, `vtwo-product/`, `personal/`. Move
`skill-fleet-audit` there.
**Why:** `Operations Vault/CLAUDE.md`'s own routing rule groups skills by family, and the
existing families split by real domain difference (HR vs GTM vs ops) — not by "type of
tool." `personal/` is OliverCBot's own productivity/life tools (`weekly-tasks`,
`vault-folder-organization`) — a different domain than fleet-maintenance tooling that
happens to be invoked by a person rather than V.Two's business. Filing skill-fleet-audit
under `personal/` mirrors the vault's convention worse than giving it its own family, the
same way `vtwo-hr`/`vtwo-gtm` split rather than everything living under one catch-all.
**Concrete moves:**
- `01 - Skills/meta/skill-fleet-audit/` (from Step 2).
- Update `01 - Skills/README.md`'s family table, `.olivercode/user-skills-inventory.md`,
  and re-run `_validate_structure.js`.
**Risk:** A new top-level family is a real structural decision under
`Operations Vault/CLAUDE.md` — flag it as a decision for OliverCBot to confirm before executing,
not something to silently do mid-build.

## Step 4 — `olivercode audit-fleet` CLI subcommand

**What:** Add `audit-fleet` to `scripts/olivercode`, alongside the existing `sync-hooks`
(reuses the same `_iter_fleet`/`repo-profiles.json` iteration it already has).
**Why:** The composed skill from Step 2 needs one non-interactive entry point a scheduler
can call — a Claude session invoking a Skill isn't available to a cron job.
**Behavior:** For every registered fleet repo/skill directory (starting with just this
vault's `01 - Skills/` and OliverCode's own `skills/` — see Step 6's Risk on scope), run
`skill-fleet-audit`'s 3 static modes (structure, MCP-efficiency, clarity/description) against
it, non-interactively, and write findings to that tree's own `_BACKLOG.md`/`BACKLOG.md`
convention (same place a live session would). The `skill-usage-audit` mode is excluded here
— it needs a live session, not a cron job.
**Risk:** A cron-run audit finding real STE100 violations with nobody watching just
accumulates backlog noise → cap it to write findings only, never auto-fix, and have it print
a one-line summary to a log file `run` can tail, not fix anything unattended.

## Step 5 — `olivercode push-fleet` CLI subcommand, and reconciling it with the standing confirm-before-push rule

**What:** Add `push-fleet [--dry-run]` to `scripts/olivercode`. For every registered repo
(+ the vault) with a clean working tree and commits ahead of its own upstream, run `git
push`. Skip (report, don't touch) any repo with uncommitted changes — this command never
commits on OliverCBot's behalf, only pushes what's already committed and already passed that
repo's own pre-commit gates.
**Why this doesn't violate the interactive safety rule:** The assistant's standing rule —
always confirm before `git push` in a live session — is about *interactive* sessions, where
a human is present to ask. This is a separate, non-interactive, scheduled process outside
any chat session. Its safety net is mechanical instead of conversational: each repo's own
`pre-push` hook (secret scan, force-push/history-rewrite block — the vault's version from
this session, `.githooks/pre-push`) is the gate, exactly the same enforcement a live `git
push` from this session already runs through. Nothing about this changes how *this*
assistant behaves when OliverCBot is asking for a push mid-conversation — that still gets
confirmed every time, in every session, unless OliverCBot separately adds a durable
CLAUDE.md instruction opting the assistant itself out of that (a materially bigger,
separate decision — not proposed here).
**Concrete moves:**
- `push-fleet` command in `scripts/olivercode`, `--dry-run` prints what it would push
  without pushing.
- **Every fleet repo needs a `pre-push` hook before this is enabled for it** — right now
  only the vault has one (`.githooks/pre-push`, built this session, not yet an OliverCode
  template — see that commit's own note). Extend `sync-hooks` to also manage `pre-push`
  (currently `_install_hook_pair` only touches `pre-commit` — confirmed this session), or
  this command has no mechanical gate on repos that never got the vault's manual pre-push
  build.
- Start scoped: enable `push-fleet` only for the vault + OliverCode itself first (lowest
  blast radius, both effectively personal/framework repos), not every product repo, until
  that's proven safe over a few weeks.
**Risk:** Auto-pushing a repo mid-refactor (a commit that's syntactically fine but
incomplete work) makes it live before a human reviews it → mitigate with the scoped rollout
above, and consider a per-repo `repo-profiles.json` opt-in flag (`"autoPush": true`) rather
than blanket-enabling everything at once — mirrors how `hookVariant` already lets a repo
opt out of `sync-hooks`.

## Step 6 — The scheduler itself: mirror `fallow/scripts/local-scheduler` exactly

**What:** `OliverCode/scripts/local-scheduler/` — `install.sh`, `uninstall.sh`, a
`tick`-style entry point, README with setup/migration/retirement instructions. Same shape as
fallow's, adapted to call `olivercode audit-fleet` (weekly cadence — matches actual
skill-build session frequency, not something that needs hourly checks) and
`olivercode push-fleet` (more frequent — e.g. every few hours — since it's just flushing
already-made commits) via `launchd`.
**Why mirror fallow's exact pattern:** That scheduler already survived a real incident —
two schedulers (`launchd` + a separate `crontab` job) running simultaneously with no lock
between them, discovered live. Reusing its install/uninstall/lock discipline avoids
re-discovering that failure mode here.
**Risk — exact cadence is a real open decision, not something to hardcode on a guess:**
confirm weekly/hourly-ish numbers with OliverCBot before `install.sh` ships, the same way
fallow's own cadence was a deliberate choice, not a default.
**Risk — Mac-asleep cron-skip:** already a known, documented gap for this class of
scheduler (see `osg-security`/Fallow memory) — launchd fires on wake, not while asleep, so a
window can be missed. Acceptable for this use case (skill audits and pushes have no
real-time deadline) but worth stating rather than assuming away.

## Pressure-Test Findings (2026-09-15, before execution)

Checked every load-bearing claim above against live state instead of trusting the write-up.
Four real corrections, one confirmed-safe:

1. **Step 2 gap, now fixed below:** all 3 old skills are live-symlinked at
   `~/.claude/skills/{skill-structure-audit,skill-usage-audit,mcp-efficiency-audit}`. The
   merge must remove those 3 and add one new symlink for `meta/skill-fleet-audit` — the
   original step didn't say this explicitly. Checked for other skills referencing these 3 by
   name (a hidden dependent that deletion would break) — none found; only this session's own
   now-superseded plan docs mention them.
2. **Step 2 correction:** "port tests, don't reinvent" was wrong — checked disk, zero
   fixture files exist for any of the 3 skills. Each one's test fixtures were built inline
   during its own build session and never saved. The merge must rebuild fixtures fresh (same
   synthetic cases described in `_BACKLOG.md`'s Live tracker), not port files that don't
   exist.
3. **Step 3 simplifies:** read `Operations Vault/_validate_structure.js`'s actual
   `scanSkillsTree()` — it's fully generic, no hardcoded family-name allowlist. A new
   `meta/` folder needs zero validator code changes, only the README/inventory doc updates
   already planned. Removes a risk the original step implied but didn't confirm.
4. **Step 4 correction:** `audit-fleet` doesn't actually need `_iter_fleet`/
   `repo-profiles.json` at all — that machinery iterates git *repos* for hook management;
   this command only ever targets 2 fixed skill-directory roots (the vault's `01 - Skills/`
   and OliverCode's own `skills/`). Reusing repo-fleet iteration for a 2-path job is the
   wrong tool. Hardcode the two roots (configurable via flag) instead.
5. **Confirmed, no change:** `_iter_fleet` yields every fleet repo with no `hookVariant`
   skip built in (that skip lives in `sync-hooks`'s own loop) — so `push-fleet` reusing it
   naively would try every fleet repo, including the two with custom hook variants that
   never got a `pre-push` install. This validates Step 5's existing caution (scoped
   rollout, per-repo opt-in) rather than finding something new — it was already the right
   call, just now confirmed against the actual skip logic instead of assumed.
6. **Minor, informational:** OliverCode's `.github/workflows/framework-ci.yml` triggers on
   every push (`on: [push, pull_request]`, read-only permissions). A few-times-daily
   `push-fleet` cadence means a few-times-daily CI run — cheap and safe, just noted so it
   isn't a surprise in Actions history.

## Step 7 — Bake pressure-testing into `meta/`, so this isn't a one-off

**What:** OliverCBot asked that plan pressure-testing (exactly what Findings 1-6 above just did)
become a standing skill in the new `meta/` family, not something re-requested each time.
Build `meta/plan-pressure-test/` — reads a plan doc written by the `plan` skill, re-derives
every claim it can check live (file existence, cross-references, reused-infra fit,
what-actually-changed-since-the-claim-was-written), and appends a "Pressure-Test Findings"
section directly into the plan file before execution starts — the same shape this plan just
got by hand.
**Why:** The generic `plan` skill (`~/.claude/skills/plan`) is a vendor/global skill, not
owned by this vault — OliverCBot's ask was specifically for this to live in `meta/`, not for a
global skill edit. A standalone skill also composes cleanly with any future `/plan` output,
not just ones in `meta/`'s own domain.
**Also:** write a `feedback`-type memory capturing "after `/plan` writes a doc and before
executing it, run `meta/plan-pressure-test` on it" — memory is what makes a standing
process apply in a future session without OliverCBot re-asking; the skill file alone is only
discoverable, not automatically triggered.
**Risk:** A pressure-test skill that itself only pattern-matches claims without actually
running checks would be theater, not verification → its own `SKILL.md` must require the
same discipline this plan just modeled: never assert a gap without checking it live.

## Definition of Done

- [ ] OliverCBot confirms the `meta/` family-folder decision (Step 3) before it's created.
- [ ] `_audit.py` + the 3 audit skills merged into one `meta/skill-fleet-audit/` skill,
      verified against each original tool's own existing test fixtures, old directories and
      `_audit.py` deleted, `README.md`/inventory/`_validate_structure.js` updated.
- [ ] `olivercode audit-fleet` runs non-interactively against both the vault's `01 -
      Skills/` and OliverCode's own `skills/`, writes findings to each tree's own backlog
      convention, fixes nothing unattended.
- [ ] `sync-hooks` (or a sibling mechanism) manages `pre-push` for every repo `push-fleet`
      will touch, not just the vault.
- [ ] `olivercode push-fleet --dry-run` reviewed live before the real (non-dry-run) version
      is scheduled anywhere.
- [ ] `scripts/local-scheduler/` installed and confirmed running via `launchctl list`,
      cadence explicitly confirmed with OliverCBot beforehand.
- [ ] `push-fleet`'s automatic scope starts at vault + OliverCode only, per-repo opt-in for
      anything wider.
- [ ] `meta/plan-pressure-test` built and symlinked, verified against this very plan as its
      first real case.
- [ ] Memory written: pressure-test every `/plan` output before executing it, going forward.
