# Key Pitfalls — Check Every Audit

| Pitfall | Why it bites |
|---|---|
| Trusting a doc's own "current design system" / "current stack" claim | Multiple docs can each claim to be current and contradict each other — only the file that matches the live CSS/config wins |
| A structured status table with plausible-looking IDs | Structure and specificity are not evidence. Cross-check IDs against real files before treating rows as fact |
| Editing dated QA/evidence log entries to match the new doc structure | Evidence logs (dated "on YYYY-MM-DD we did X") are historical record, not living docs — rewriting them falsifies the audit trail. Only fix live navigation references, never the timestamped entries themselves |
| Deleting/merging a doc without grepping for hardcoded path references | Breaks shell `require_file` gates, stale code comments, CI configs silently |
| Assuming a doc split (e.g. "part-01..part-06") stays enforced | Check for an actual size-cap validator before assuming the split can't be undone. It's often just a one-time, unenforced decision that's now causing the docs to drift out of sync with each other |
| "Fixing" a stale doc mechanically without checking relevance | Ask whether the described feature is still used/prominent before polishing a more-accurate detail onto it. Sometimes the right fix is to trim the detail, not preserve it |
| Applying a vault-specific formatting rule (e.g. "no tables") to an unrelated repo | Formatting standards from one system (e.g. a Word-paste vault) don't automatically transfer to a git-hosted code repo's README — GitHub renders tables fine. Port the *discipline* (SSOT, no duplication), not every literal rule |
