# Backlog-issue accuracy

Load this from `deep-review` step 2c when the repo names a live GitHub Project.

Not every repo tracks work this way. Skip this phase entirely if the repo's own `CLAUDE.md` names no `backlog-config.json` (or equivalent). Where one exists, the session likely closed some issues with an evidence comment during the range under review. Sample a few of those closes against the real repo state:

- The file paths and line numbers the comment cites still exist and say what it claims.
- The commit SHA it names is real and in this range.
- The claimed fix is actually present in the code today, not just in the commit message.

A close with unverifiable or wrong evidence is a finding. Reopen it or fix the comment, same as any other defect. `docs-reality-audit`'s own Truth Hierarchy phase applies the same discipline for a configured Project. Here it covers one review pass instead of a whole-repo audit.
