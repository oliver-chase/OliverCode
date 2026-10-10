---
name: deep-review
description: "Post-build deep review loop: single sequential review agent over a commit range, simplify pass, validate-then-remove legacy cleanup, live re-verification on the real deploy. When the repo names a live GitHub Project backlog, also validates that closed-issue evidence still matches reality. Ends with a live session tracker so coverage and current state survive the session. Run before closing any multi-commit build session. Also run it on direct request: 'QA this', 'QA the work', 'bring in another agent to review/QA this', 'review tonight's work'."
---

# Deep Review (post-build review loop)

This skill reviews a session's own output before the session calls it done. It verifies findings against code, removes validated-expired legacy, and writes all state into a tracker another agent can resume from. It differs from `repo-audit-with-execution-batches`, a surface scan of a repo at rest.

This skill is the operational "how" for `DEVELOPMENT_LIFECYCLE_STANDARD.md` §5 (QA as a separate, adversarial pass) and §7 (simplify as part of finishing). That contract states the principle and this skill runs it. Read the contract for the why. This file never restates it.

## When to run

Two granularities, both owner-set, neither optional:

- **Per unit, before its commit**. Every discrete piece of work gets its own scoped review agent before its commit: one backlog item, one bug fix, one feature slice. Size that agent to that diff alone (step 2 below). Fix or defer every finding first. Commit only after that review has run. This skill's own history came from this loop. A backlog item shipped, a review ran, the findings landed, then the commit followed. Repeat that per item. Never batch it into one end-of-session pass.
- **Before closing any session that produced multiple commits**. The wider sweep runs steps 3 through 7 across the whole session's commit range. It catches what a per-unit review can't see: duplication across units, drift between them, and the tracker update. Also run it on direct request ("review tonight's work", "validate what we just built").

The unit of review for the wide sweep is a commit RANGE, not a repo. The unit for the per-commit gate is the diff about to be committed. That diff is usually smaller than a range.

## Non-negotiables (owner-set)

0. **No commit before its own review**. A finished unit of work is not done until a review agent has read the diff. Every finding is then either fixed or written into the tracker. Committing first and reviewing after defeats an adversarial pass. By then the "fix" is a follow-up commit, not a gate.
1. **One review agent, sequential — never a fan-out**. A single general-purpose agent walks the whole range. The orchestrating agent runs the simplify pass itself. Two workers total, maximum.
2. **Findings must be verified against actual code before reporting**. The reviewer reads the files, not just the diff. Real bugs only: correctness, security, behavioral regressions, broken wiring. No style nits, no hypotheticals.
3. **Fix every finding in-session or write it into the backlog tracker**. Nothing lives only in the conversation.
4. **Cleanup is part of review, not a separate task**. See the remove-don't-archive protocol below.
5. **Track as you finish**. Every unit of work appends one status line to the repo's live session tracker IN THE SAME COMMIT. A unit is a review agent's findings applied, a cleanup batch, or a spec built. Parallel or later agents then see current state, not a stale snapshot.

## The loop

### 1. Scope the range

Run `git log --oneline <base>..HEAD`. The base is the last reviewed commit (the tracker records it) or the session's first commit. Hand the agent the range, a one-paragraph summary of what shipped, and the review angles below.

### 2. Review agent (the one subagent)

**Scope the prompt tightly. This is the real token-cost lever, not review depth**. Some prompts ask the agent to validate everything live, build its own tests, and run every X against every Y. That multiplies into an unbounded number of tool calls with no natural stopping point. The agent is also fresh, with none of the orchestrator's cache. Seen live: an open-ended 7-point ask burned 160k tokens and 68 tool calls in one run. Fix the prompt, not the checklist:

- Name the exact commands to run, not "make sure this works."
- Cap the re-test surface at one fresh fixture per code path under review. Name a specific edge case if one matters. Do not ask the agent to go find edge cases itself.
- Prefer resuming or forking a session with shared cache over a fresh general-purpose agent, when context already gathered would help the review. A fresh agent re-derives everything from zero, and that is usually the actual cost driver.

Prompt it to read the full diff per file plus surrounding context, then hunt in priority order:

- **Correctness:** logic errors, None/undefined handling, race conditions, and SQL that must run on every supported backend. Also broken references after refactors (functions, ids, or classes used but no longer defined) and event wiring whose selectors no longer match the markup.
- **Security:** injection, auth bypass, tenant/scope leaks (validate every scope-switch try/finally), secrets in the diff.
- **Behavioral regressions:** what did the old code do that the new code silently dropped? Real example: a page consolidation lost the only UI path from "approved" to "generate", so every approval dead-ended.
- **Substrate blind spots:** anything the local test substrate can't exercise (RLS policies, container limits, deploy-only env). Flag these explicitly as "passes locally, unverified on real deploy."

Output: ranked findings, each with file/function, one-sentence defect, concrete failure scenario, and minimal fix. State clean areas in one line.

### 2b. Frontend/UX angles (mandatory when the range touches any UI)

Cover EVERY user-facing surface — admin/operator UI and public pages alike, not just the screens the session worked on:

- **Design-system lock-in / no hardcoding:** zero inline styles, and zero hardcoded colors, sizes, or spacing outside the token sheet. One radius system, one accent, and every JS-generated class exists in the stylesheet. If the repo lacks a mechanical gate for this, ADD one in the same session. The proven pattern is an inline-style scan wired into the validate aggregator, and it removes the finding class for good.
- **Component reuse:** repeated markup patterns must go through the shared component/renderer, never copy-pasted per page. Duplicated render functions across pages are a finding.
- **User flow:** walk each primary journey end to end as the user would. Every step must be reachable from the previous one, with no dead ends. Real example: an approval step whose output had no next action anywhere in the UI. Empty states funnel forward. Post-action feedback tells the user what actually happened.
- **User journey docs:** the repo's journey/flow doc must match the shipped UI page-for-page. Stale page names or steps are findings.
- **Accessibility:**
  - Keyboard path: a focus-visible ring on every interactive element, no keyboard traps, logical tab order.
  - Labels: every input labeled, no placeholder-as-label, and buttons that self-describe or carry an accessible name.
  - Contrast at WCAG AA for text and controls.
  - Touch targets usable on coarse pointers. Hover-only affordances need a touch path.
  - Media elements carry captions/alt or a documented reason.
- **Responsiveness:** at ~360/768/1024/1440/1920 — no horizontal page overflow, nothing overlaps, wide content scrolls inside its own container.

### 2c. Backlog-issue accuracy (only when the repo names a live GitHub Project)

Not every repo tracks work this way. Skip this phase entirely if the repo's own `CLAUDE.md` names no `backlog-config.json` (or equivalent). Where one exists, the session likely closed some issues with an evidence comment during the range under review. Sample a few of those closes against the real repo state:

- The file paths and line numbers the comment cites still exist and say what it claims.
- The commit SHA it names is real and in this range.
- The claimed fix is actually present in the code today, not just in the commit message.

A close with unverifiable or wrong evidence is a finding. Reopen it or fix the comment, same as any other defect. `docs-reality-audit`'s own Truth Hierarchy phase applies the same discipline for a configured Project. Here it covers one review pass instead of a whole-repo audit.

### 3. Simplify pass (run it yourself, in parallel with the agent)

Mechanical evidence first, opinions second:

- Duplicated functions across files (`grep -oE "function \w+" | sort | uniq -c` or the language equivalent).
- Dead classes/helpers: defined but referenced nowhere else.
- Superseded code the session's own diffs made redundant.
- Wasted work: repeated I/O, sequential independent calls, counts via `len(list(...))` where a COUNT query belongs.

Fix what's safe. Backlog what isn't.

### 4. Apply findings

Fix in severity order. Each fix gets its own verification (test or live probe). A finding whose fix would change intended behavior gets a tracker entry instead, marked with why.

### 5. Cleanup: remove, don't archive

Legacy found during review gets VALIDATED then REMOVED — git history is the archive. Validation per file:

- Zero code references (`grep -r` across code, scripts, configs — remember same-dir relative imports and commented env-var docs).
- Content describes removed functionality or a superseded era, or the file self-declares historical.

**Never remove current-state files**. That covers the backlog, audit tracking, gap registers, capability matrices, and anything that shows where the project stands. When unsure whether a file is expired or current-state, ask the owner. Removal is cheap to defer.

After removing, patch every dangling reference to live paths. Prose history mentions may stay, since they describe the past accurately.

### 6. Live re-verification

Anything flagged "passes locally, unverified on real deploy" gets verified against the real environment before the session closes. Otherwise it gets a tracker entry at the TOP of open items. This skill exists to prevent one expensive failure mode above all. Three HIGH bugs once showed up only under the production database's row-level security, invisible to the entire local suite.

### 7. Update the tracker

The repo's backlog carries a **live session tracker** section (template: `core/templates/project/docs/BACKLOG-live-tracker.md`):

- "Where things stand" summary (rewrite, keep current)
- Ranked open items (top item = what the next agent should do first)
- "Reviewed through: `<commit sha>`" — THE coverage marker. `scripts/audit-staleness.py` computes staleness fleet-wide from it
- Append-only activity log (one line per completed unit, same commit)

## Mechanical gotchas (hit for real)

- Local test substrates lie by omission: SQLite has no RLS, always populates `lastrowid`. Dev machines have no container memory limit. If the deploy differs structurally, review the difference explicitly.
- A rule without a gate regresses. If review keeps finding the same class (inline styles, archive dirs, secrets), add a validate-script gate in the same session. That removes the finding class for good.
- Reference-scanning traps: alias-only greps miss same-dir relative imports. Anchored env greps miss commented `# VAR=` doc lines. A code reference found only inside another file already on the kill list doesn't count.

## Output conventions

- Findings and fixes land in commit messages (the durable audit trail) plus one tracker line each.
- Cleanup commits state what they removed, the validation done, and what they deliberately KEPT and why.
- Close the session with the tracker's "where things stand" rewritten to match reality.
