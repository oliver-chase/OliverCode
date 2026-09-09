---
name: functionality-audit
description: "Full functionality audit of a live product repo — crash-safe incremental execution, quick wins fixed inline, larger findings written as context-free executable specs. Covers dead code, broken flows, doc truth, RLS/security, tooltips, revert symmetry, and marked-complete-but-isn't."
---

# Functionality Audit (crash-safe, write-as-you-go)

Distinct from `repo-audit-with-execution-batches` (surface scan → report):
this one verifies the product actually WORKS end to end, fixes quick wins
inline, and assumes the session may be cut off at any moment.

## Non-negotiables (owner-set, learned the hard way)

1. **Single sequential pass.** No multi-agent fan-out, ever — one pass by you,
   or one scoped read-only agent for a big inventory. (Standing owner rule.)
2. **Write-as-you-go, commit-per-chunk.** Before auditing anything, write a
   progress tracker into the repo's backlog doc (checkbox per area) and commit
   it. Append findings per area, commit + push after every 1-2 areas. A cutoff
   must lose nothing. The next session resumes from the first unchecked box.
3. **Tracker boxes start UNCHECKED.** Mark `[x]` only when the area is done.
   (Real mistake: pre-marking all boxes made the tracker a lie on commit 1.)
4. **Quick wins fixed inline. Everything larger becomes a SPEC** written so a
   future agent with zero session context can execute it: the ask, the files,
   the evidence, the tradeoffs, a recommended order. Never build features
   mid-audit.
5. **Verify, never assume. Code wins.** Session memory, doc claims, and code
   comments all lie: a header comment claimed two consumers that didn't
   reference it. Memory said a lane was a stub that had since been built.
   Docs claimed nav state 5 days stale. Check the actual code every time.
6. **Full verification loop before every commit:** typecheck + full test
   suite + repo's own structure/contract gates + full production build.

## Area list (run in order. Add follow-ups as new numbered areas)

1. **Repo/folder structure.** Loose root files, untracked-but-code-referenced
   files (dangling on fresh clone), empty dirs, template/real data splits,
   gitignore correctness. Root-doc sprawl → one home.
2. **API route inventory.** For every route: who consumes it? Categories that
   fall out: **dead** (zero consumers — delete. Anonymous endpoints that cost
   money per call are top priority), **stub** (runs and reports success while
   doing nothing — flag as marked-complete-but-isn't), **dormant-but-gated**
   (auth'd, unused — backlog a surface-or-remove decision, don't delete
   unilaterally).
3. **Public user journey.** Every nav/footer/page link resolves. Pages
   reachable ONLY via one widget chip. Sunset pages still telling visitors
   things that are no longer true (e.g. "sign in to submit" when sign-in is
   admin-only). Flows that dead-end at a login wall for users who can't log
   in. Walk it as a first-time visitor would.
4. **Docs-vs-code behavior diff.** Diff documented intents/flows against the
   real dispatch code. Diff env vars: code reads vs `.env.example` vs setup
   doc. Gotcha: commented-out `# VAR=` entries in an env example ARE
   documentation — an anchored `^VAR` grep falsely reports them missing.
5. **Admin journey.** Every dashboard card/link resolves. Redirects preserve
   query strings. Every admin-editable thing actually round-trips to the
   backend (form field → API field → storage → display).
6. **Dead code sweep.** Zero-importer modules. MUST grep BOTH import forms —
   `@/alias/path` AND same-dir `./relative` — before deleting. Run typecheck
   immediately after deletion to catch false positives. Verify a "consumed by
   X" comment by checking X actually references it. Record the method gotchas
   you hit in the backlog so the next sweep doesn't repeat them.
7. **Documentation accuracy + runbook test.** Stale claims vs current code.
   Then the stand-up-from-scratch test: could a new operator go from clone to
   deployed with ONLY the docs? Missing pieces are usually: DB
   creation/migration order, hosting-dashboard clicks, scheduler secrets,
   first-admin creation, third-party domain verification.
8. **Hardcoding + genericization.** Region/brand strings in live code paths
   (examples and reference tables are fine). If deploy-elsewhere is a goal:
   spec a single env-driven identity module (brand name, UA, metadata, legal
   entity, contact) with current values as defaults — spec only, don't build.
9. **Summary.** What shipped, what's backlogged, recommended execution order
   ranked by owner leverage.

## Follow-up battery (run when the owner asks "was X included?")

Answer honestly which areas were NOT covered, then run them as new numbered
areas. The recurring four:

10. **Security/RLS.** Diff every `create table` against every
    `enable row level security` in migrations (tables dropped later don't
    count). Scan for `using (true)` policies. Check grant breadth — a blanket
    grant to `authenticated` means one future migration missing enable-RLS
    silently exposes its table (add a CI/checklist guard). List owner-side
    dashboard actions (e.g. disable public signups) separately — not fixable
    from the repo.
11. **UI affordance consistency (tooltips).** Scan every interactive element
    for `title=`. Regex traps: JSX tags span lines, and `() =>` inside props
    contains `>` — use a brace-aware scanner, not `<button[^>]*title`.
    Fix the consequential gaps (destructive/high-stakes actions first).
    Deliberately leave elements whose visible label self-describes.
12. **Change-AND-revert symmetry.** For everything the admin can change: can
    they see its history, and can they restore a prior value in one click?
    Read-only history views and audit logs with no UI are the common gaps.
13. **Marked-complete-but-isn't.** Three shapes: runtime (jobs/runs reporting
    "completed" while doing nothing), docs ("verified against code" claims
    predating N commits), and memory (session/agent memory describing a stub
    that has since been built — correct the record. Code wins).

## Design-system consolidation sub-method

When the audit turns up visual drift (or the owner asks for "less variation"):
inventory variance with grep counts first (`fontSize:`, hex colors, margins),
then merge each ROLE to one token. Rules that held up: merge SIZE, keep COLOR
semantic (warn/error/muted carry meaning. A 12.5px one-off doesn't). Bake an
override into the token only when 100% of call sites already agree (6/7 with a
documented exception = leave it). Backgrounds that encode state (quarantined/
open/closed) are signal, not drift.

## Mechanical gotchas (all hit for real)

- Same-dir relative imports evade alias-only dead-code greps (see area 6).
- Anchored env-var greps miss commented `# VAR=` documentation lines.
- Single-quoted sed/perl replacements can't produce JS template literals —
  verify emitted syntax, then typecheck.
- Never hand-edit generated type files (`.next/types/*`) after deleting a
  route — rebuild regenerates them correctly.
- After `git rm` on a wrong guess, `git checkout HEAD -- <file>` restores.
  Typecheck is the safety net that catches it.

## Output conventions

- One home: the repo's existing backlog doc. Findings numbered `AUDIT-N`,
  sub-items `AUDIT-Na/b/c`.
- Each area's section splits **"Fixed inline (quick wins)"** from
  **"Backlog"** — and states scope limits plainly ("only fills on first
  geocode") so partial fixes are never mistaken for full coverage.
- Commit messages carry the findings summary — the audit trail must survive
  in git history even if the backlog doc is later trimmed.
