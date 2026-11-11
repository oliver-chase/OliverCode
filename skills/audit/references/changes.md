# Changes

The work a session produced, reviewed before it is called done. It runs at two sizes.

- **Each unit, before its commit.** One backlog item sized M or above, or a bug fix or feature slice of that size, gets its own review of its own diff before it is committed. An XS or S unit relies on the repo's validation. Every finding is fixed or filed first
- **The session, before it closes.** A session with 5 or more commits or 500 or more changed lines gets one wider review over its whole range, which catches what a per-unit review cannot see: duplication across units, drift between them, and the tracker

## The review

1. **Scope the range.** `git log --oneline <base>..HEAD`, where the base is the Reviewed-through commit in `docs/BACKLOG.md` or the session's first commit. Review only this session's commits when other sessions commit to the same repo
2. **One reviewer agent on `haiku`** for a diff over 3,000 changed lines, and the lead for a smaller one, reads the full diff of each file with its surrounding code. Brief it tightly, since an open-ended brief is the real cost: name the exact commands to run, name the edge cases that matter, and allow one fresh fixture per code path. It hunts, in order:
   - Correctness: logic errors, missing-file and empty handling, races, references broken by a rename, wiring whose selectors no longer match
   - Security: injection, auth and scope leaks, secrets in the diff, a guard that fails open
   - Regressions: what the old code did that the new code silently drops
   - What the local tests cannot exercise, such as row-level security, container limits or deploy-only settings. Mark each "passes locally, unverified on the real deploy"
3. **Simplify while the reviewer works.** Look for functions duplicated across files, helpers nothing calls, and code the session's own changes made redundant. Fix what is safe and file the rest
4. **Apply findings** in order of severity, each with its own test or live check. A finding whose fix would change intended behavior is filed, with the reason
5. **Remove legacy the review finds.** Check that nothing references it, then delete it, since git holds the history. Never remove a file that records current state, such as the backlog or a tracker. When unsure, ask the owner
6. **Verify on the real environment** anything marked unverified, or file it at the top of the open items
7. **Check closed issues** where the repo names a backlog: the cited paths still say what the close claims, the commit exists, and the fix is in the code today
8. **Count the commit findings** with `python3 scripts/commit_audit.py <repo> [<repo> ...]`. It prints each class (no story, pull-request merge, code with no test, co-author form, voice) with its count and the change since the last run, and changes nothing

## The tracker

The repo's `docs/BACKLOG.md` records coverage in one line, "Reviewed through: `<sha>`", under "Coverage". Update it when a review finishes, and only to a commit the review read.
