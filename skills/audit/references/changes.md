# Changes

The work a session produced, reviewed before it is called done. It runs at two sizes, and both are required.

- **Each unit, before its commit.** One backlog item, one bug fix or one feature slice gets its own review of its own diff before it is committed. Every finding is fixed or filed first
- **The session, before it closes.** A session with several commits gets one wider review over its whole range, which catches what a per-unit review cannot see: duplication across units, drift between them, and the tracker

## The review

1. **Scope the range.** `git log --oneline <base>..HEAD`, where the base is the tracker's last reviewed commit or the session's first commit. Review only this session's commits when other sessions commit to the same repo
2. **A reviewer agent**, one per about 3,000 changed lines, reads the full diff of each file with its surrounding code. Brief it tightly, since an open-ended brief is the real cost: name the exact commands to run, name the edge cases that matter, and allow one fresh fixture per code path. It hunts, in order:
   - Correctness: logic errors, missing-file and empty handling, races, references broken by a rename, wiring whose selectors no longer match
   - Security: injection, auth and scope leaks, secrets in the diff, a guard that fails open
   - Regressions: what the old code did that the new code silently drops
   - What the local tests cannot exercise, such as row-level security, container limits or deploy-only settings. Mark each "passes locally, unverified on the real deploy"
3. **Simplify while the reviewer works.** Look for functions duplicated across files, helpers nothing calls, and code the session's own changes made redundant. Fix what is safe and file the rest
4. **Apply findings** in order of severity, each with its own test or live check. A finding whose fix would change intended behavior is filed, with the reason
5. **Remove legacy the review finds.** Check that nothing references it, then delete it, since git holds the history. Never remove a file that records current state, such as the backlog or a tracker. When unsure, ask the owner
6. **Verify on the real environment** anything marked unverified, or file it at the top of the open items
7. **Check closed issues** where the repo names a backlog: the cited paths still say what the close claims, the commit exists, and the fix is in the code today

## The tracker

The repo's `docs/BACKLOG.md` carries the live tracker, laid out by `$OC/core/templates/project/docs/BACKLOG-live-tracker.md`. Its marker line, "Reviewed through: `<sha>`", records coverage, and `$OC/scripts/audit-staleness.py` reads it. Update it in the commit that finishes the review.
