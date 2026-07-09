---
name: deep-review
description: "Post-build deep review loop — single sequential review agent over a commit range, simplify pass, validate-then-DELETE legacy cleanup, live re-verification on the real deploy, and a live session tracker so coverage and current state survive the session. Run before closing any multi-commit build session."
---

# Deep Review (post-build review loop)

Distilled from a real overnight build-and-review session (2026-07-08):
~20 commits reviewed, 8 verified findings (3 HIGH invisible to the local
test substrate), ~9k LOC of validated-expired legacy removed, all state
written into a tracker another agent can resume from. Distinct from
`functionality-audit` (does the PRODUCT work end to end) and
`repo-audit-with-execution-batches` (surface scan of a repo at rest):
this reviews a SESSION'S OWN OUTPUT before it's considered done.

## When to run

Before closing any session that produced multiple commits — features,
fixes, refactors. Also on request ("review tonight's work", "check what
we just built"). The unit of review is a commit RANGE, not a repo.

## Non-negotiables (owner-set)

1. **One review agent, sequential — never a fan-out.** A single
   general-purpose agent walks the whole range; the orchestrating agent
   runs the simplify pass itself. Two workers total, maximum.
2. **Findings must be verified against actual code before reporting.**
   The reviewer reads the files, not just the diff. Real bugs only:
   correctness, security, behavioral regressions, broken wiring. No
   style nits, no hypotheticals.
3. **Every finding is either fixed in-session or written into the
   backlog tracker.** Nothing lives only in the conversation.
4. **Cleanup is part of review, not a separate task** — see the
   remove-don't-archive protocol below.
5. **Track as you finish.** Every unit of work (review agent's findings
   applied, cleanup batch, spec built) appends one status line to the
   repo's live session tracker IN THE SAME COMMIT — so parallel or
   subsequent agents see current state, not a stale snapshot.

## The loop

### 1. Scope the range

`git log --oneline <base>..HEAD` — base is the last reviewed commit
(the tracker records it) or the session's first commit. Hand the agent
the range, a one-paragraph summary of what shipped, and the review
angles below.

### 2. Review agent (the one subagent)

Prompt it to read the full diff per file plus surrounding context, then
hunt in priority order:
- **Correctness:** logic errors, None/undefined handling, race
  conditions, SQL that must run on every supported backend, broken
  references after refactors (functions/ids/classes used but no longer
  defined), event wiring whose selectors no longer match the markup.
- **Security:** injection, auth bypass, tenant/scope leaks (check every
  scope-switch try/finally), secrets in the diff.
- **Behavioral regressions:** what did the old code do that the new
  code silently dropped? (Real example: a page consolidation lost the
  only UI path from "approved" to "generate" — every approval
  dead-ended.)
- **Substrate blind spots:** anything the local test substrate can't
  exercise (RLS policies, container limits, deploy-only env). Flag
  these explicitly as "passes locally, unverified on real deploy."
Output: ranked findings, each with file/function, one-sentence defect,
concrete failure scenario, minimal fix. Clean areas stated in one line.

### 2b. Frontend/UX angles (mandatory when the range touches any UI)

Cover EVERY user-facing surface — admin/operator UI and public pages
alike, not just the screens the session worked on:

- **Design-system lock-in / no hardcoding:** zero inline styles, zero
  hardcoded colors/sizes/spacing outside the token sheet, one radius
  system, one accent, every JS-generated class exists in the
  stylesheet. If the repo lacks a mechanical gate for this, ADD one in
  the same session (verified pattern: an inline-style scan wired into
  the validate aggregator — the finding class dies permanently).
- **Component reuse:** repeated markup patterns must go through the
  shared component/renderer, never copy-pasted per page (duplicated
  render functions across pages = finding).
- **User flow:** walk each primary journey end to end as the user
  would — every step reachable from the previous one, no dead ends
  (real example: an approval step whose output had no next action
  anywhere in the UI), empty states funnel forward, post-action
  feedback tells the user what actually happened.
- **User journey docs:** the repo's journey/flow doc must match the
  shipped UI page-for-page — stale page names or steps are findings.
- **Accessibility:** keyboard path (focus-visible ring on every
  interactive element, no keyboard traps, logical tab order), labels
  (every input labeled, no placeholder-as-label, buttons self-describe
  or carry an accessible name), contrast at WCAG AA for text and
  controls, touch targets usable on coarse pointers (hover-only
  affordances must have a touch path), media elements carry
  captions/alt or a documented reason.
- **Responsiveness:** at ~360/768/1024/1440/1920 — no horizontal page
  overflow, nothing overlaps, wide content scrolls inside its own
  container.

### 3. Simplify pass (run it yourself, in parallel with the agent)

Mechanical evidence first, opinions second:
- Duplicated functions across files (`grep -oE "function \w+" | sort |
  uniq -c` or the language equivalent).
- Dead classes/helpers: defined but referenced nowhere else.
- Superseded code the session's own diffs made redundant.
- Wasted work: repeated I/O, sequential independent calls, counts via
  `len(list(...))` where a COUNT query belongs.
Fix what's safe; backlog what isn't.

### 4. Apply findings

Fix in severity order. Each fix gets its own verification (test or
live probe). Findings whose fix would change intended behavior get a
tracker entry instead, marked with why.

### 5. Cleanup: remove, don't archive

Legacy found during review gets VALIDATED then DELETED — git history is
the archive. Validation per file:
- Zero code references (`grep -r` across code, scripts, configs —
  remember same-dir relative imports and commented env-var docs).
- Content describes deleted functionality or a superseded era, or the
  file self-declares historical.
**Never delete current-state files** — backlog, audit tracking, gap
registers, capability matrices, anything that showcases where the
project stands. When unsure whether a file is expired or current-state,
ask the owner; deletion is cheap to defer.
After deleting: patch every dangling reference to live paths (prose
history mentions may stay — they describe the past accurately).

### 6. Live re-verification

Anything flagged "passes locally, unverified on real deploy" gets
verified against the real environment before the session closes — or
gets a tracker entry at the TOP of open items. The single most
expensive failure mode this skill exists to prevent: three HIGH bugs
that only manifested under the production database's row-level
security, invisible to the entire local suite.

### 7. Update the tracker

The repo's backlog carries a **live session tracker** section (template:
`core/templates/project/docs/BACKLOG-live-tracker.md`):
- "Where things stand" summary (rewrite, keep current)
- Ranked open items (top item = what the next agent should do first)
- "Reviewed through: `<commit sha>`" — THE coverage marker;
  `scripts/audit-staleness.py` computes staleness fleet-wide from it
- Append-only activity log (one line per completed unit, same commit)

## Mechanical gotchas (hit for real)

- Local test substrates lie by omission: SQLite has no RLS, always
  populates `lastrowid`; dev machines have no container memory limit.
  If the deploy differs structurally, review the difference explicitly.
- A rule without a gate regresses. If review keeps finding the same
  class (inline styles, archive dirs, secrets), add a validate-script
  gate in the same session — the finding class dies permanently.
- Reference-scanning traps: alias-only greps miss same-dir relative
  imports; anchored env greps miss commented `# VAR=` doc lines; a
  code reference found only inside another file already on the kill
  list doesn't count.

## Output conventions

- Findings and fixes land in commit messages (the durable audit trail)
  plus one tracker line each.
- Cleanup commits state what was deleted, the validation done, what was
  deliberately KEPT and why.
- Close the session with the tracker's "where things stand" rewritten
  to match reality.

---

> Authored 2026-07-08 from a real build-review-cleanup session.
