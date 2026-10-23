# Plan: Complete Revamp — From First Principles

Date: 2026-10-22
Related: `docs/BACKLOG.md` B22/B23/B42, today's commits `278da37`..`cdc65aa`

## Goal

OliverCode is one operator's shared orchestration layer across ~19 product repos
(tesknota, fallow, oliver-app, oliver-strategic-growth, oliver-studios, and others), run
from one Mac, with Claude Code as the sole runtime. Its job is to keep every repo
consistent and catch known failure classes (secret leaks, stale docs, duplication
regrowth) without becoming a bigger maintenance burden than the problem it solves.

Today's session already cut real weight: 10 contracts → 9, a dead ~3,000-word Activity
log, an unused persona, a non-functional QA script, several stale-path and gate-count
bugs. This plan covers what's left — the changes big enough that they needed a plan
instead of a drive-by fix, each checked against live state first, not assumed.

## Steps

1. **Converge the two backlog paradigms to one.** — *why:* `PROJECT_STRUCTURE_STANDARD.md`
   still carries a full file-based `.github/user-stories/` contract for repos that haven't
   adopted a GitHub Project board. Checked all three repos still on it
   (`family-stories`, `fallow`, `tesknota` — read, not assumed): all three have real,
   populated `US-*.md` story files, so this isn't dead weight to delete outright. The
   seven repos with a real `backlog-config.json` already use the GitHub Project board,
   and it's the only paradigm the live tooling (`backlog-management`, `board-hygiene`,
   `deep-review`) understands. *Outcome:* migrate the three holdout repos' open stories
   into GitHub Projects (one PR per repo, human-reviewed — this is real backlog data,
   not boilerplate), then delete the file-based contract from
   `PROJECT_STRUCTURE_STANDARD.md` and the `.github/user-stories/` template scaffold from
   `shared/project-bootstrap-manifest.json`. Closes B42 (bootstrap currently stamps that
   scaffold into every new repo regardless of which paradigm it'll use) as a side effect
   of deleting it.
   - **Risk: HIGH, real side effects.** Creating GitHub issues/Projects is not easily
     reversible, and these are live repos the operator runs daily. Mitigation: do the
     migration as three separate, human-approved steps — propose the mapping (which
     `US-*.md` becomes which issue) per repo, get a yes, then execute. Never batch all
     three into one unreviewed pass.

2. **Merge `AGENT_SHARED_STRUCTURE.md` into `docs/FRAMEWORK_BOUNDARY.md`.** — *why:*
   Read both in full. `AGENT_SHARED_STRUCTURE.md` (217 words, the smallest contract) is a
   path map and ownership list — "where do shared things live." `FRAMEWORK_BOUNDARY.md`
   (582 words) answers the same question from the opposite direction — "what does
   OliverCode contain, and where's the line against the runtime environment and sibling
   agent state." They're two halves of one map, maintained separately: today's session
   found and fixed a stale claim in `FRAMEWORK_BOUNDARY.md` (leftover "personas" mentions
   from an earlier, unrelated deletion) that a single merged file would have made easier
   to catch, since there'd be one path map instead of two drifting against each other.
   *Outcome:* fold `AGENT_SHARED_STRUCTURE.md`'s Canonical Paths / Ownership / Sync
   Contract sections into `FRAMEWORK_BOUNDARY.md`, delete the file, repoint its three
   referrers (`AGENT_SYSTEM_MANIFEST.json`'s `shared_contract.structure` key,
   `ARCHITECTURE.md`'s repo-tree mention, and `docs/GOVERNANCE.md`'s "Policy" pointer).
   - **Risk: LOW.** Pure doc merge, no runtime behavior depends on the filename — verify
     with `grep -rl "AGENT_SHARED_STRUCTURE"` before and after, run `scripts/validate.sh`.

3. **Trim `docs/DOCUMENTATION_STANDARD.md`'s `## Voice` section.** — *why:* Already
   identified and flagged to the operator this session, not yet executed. The section
   mostly restates principles the file already explains at length, with reasoning and
   examples, in `## The shape of a README` above it — which violates the file's own
   stated rule ("a paragraph that restates the one above it is still deleted," line 34-35
   as it stands today). *Outcome:* cut the bullets that are pure restatement
   ("Problem first, mechanism second," "Attach the reason," "Explain the decision, do not
   encode it," "Concrete over abstract," "Failure modes are content" — all said fully
   above); keep the two or three that add real, non-redundant information ("Second person
   for the reader's actions, third for the system's," "Numbers are evidence," and "No
   history in current-state docs" if a cross-reference to the Index-README rule at line
   141 doesn't already cover it).
   - **Risk: LOW.** This is a locked contract every fork inherits, so the cut needs to
     preserve the checklist value some readers rely on — keep a short "see above" pointer
     rather than deleting the section heading outright, so a skimming reader still finds
     the Voice section and gets redirected instead of finding nothing.

4. **Leave the gate count (11 OliverCode / 9 downstream) alone.** — *why:* checked every
   gate's entry in `docs/BACKLOG.md`'s Design-decisions and Resolved sections, not
   assumed from the count alone. Each one maps to a real incident that already happened
   once (a leaked secret, a gate-count claim that drifted for months undetected, a
   duplicate rule regrowing after a dedup pass). Cutting any of them removes a defense
   against something that already happened, not hypothetical bloat. *Outcome:* no
   change. This step exists in the plan so the revamp doesn't silently skip the gate
   layer — it was checked, not ignored.

5. **Leave `docs/OLIVERCODE_LAUNCHER.md` + `docs/FEATURE_MAP.md` as two files.** — *why:*
   this plan's original brief named them as a merge candidate ("both describe what's in
   the box"). Checked both in full before accepting that premise: `FEATURE_MAP.md` is the
   index — one row per capability, each pointing to its one owning doc — and
   `OLIVERCODE_LAUNCHER.md` is the detailed per-command reference one of those rows
   points to. `docs/DOCUMENTATION_STANDARD.md` itself names this exact pairing as the
   correct pattern for a reference doc split by surface. The premise didn't hold up on
   verification. *Outcome:* no change.

## Risks

- Step 1 is the only step with real, hard-to-reverse blast radius (live GitHub data in
  three repos the operator runs daily) → mitigated by splitting it into three
  human-approved sub-steps, never one batched pass.
- Steps 2-3 touch files every downstream fork inherits verbatim → mitigated by running
  `bash scripts/validate.sh` (all 11 gates, reference check, duplication check, 142
  smoke tests) after each, before committing, same as every change made today.
- This plan itself could go stale if the operator migrates a repo off the file-based
  backlog independently before Step 1 runs → re-check `find . -iname "*.github/user-stories*"`
  across the fleet before executing Step 1, don't trust this plan's count once time has
  passed.

## Definition of Done

- [ ] Step 1: `family-stories`, `fallow`, and `tesknota` have their open stories in
      GitHub Projects; `.github/user-stories/` contract and template scaffold removed;
      B42 closed.
- [ ] Step 2: `AGENT_SHARED_STRUCTURE.md` deleted, content merged into
      `FRAMEWORK_BOUNDARY.md`, all referrers repointed, `validate.sh` passes.
- [ ] Step 3: `DOCUMENTATION_STANDARD.md`'s Voice section trimmed to non-redundant
      content, `validate.sh` passes.
- [ ] Steps 4-5: recorded as checked, no action needed — not left silently unconsidered.
