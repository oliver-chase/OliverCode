# Complementary Skills — Use Alongside, Don't Duplicate

This skill covers doc-vs-code truth and doc consolidation only. It deliberately does not hunt for code bugs, quality issues, or UI problems. Pull in the dedicated tool for those instead of improvising a lighter version inline:

- **`/code-review`** — when the audit's code-verification steps (Phase 3) turn up an actual correctness bug in the code, don't fix it ad hoc. That's different from a doc merely claiming something false about the code — a doc-audit side effect, not the audit's job. Run `/code-review` on the bug as its own pass.
- **`/simplify`** — if Phase 3/4 surfaces duplication or dead code in the codebase (not just docs), that's `/simplify`'s job, not this audit's. The two share the no-duplication principle but operate on different material.
- **`diagnosing-bugs`** — if a doc's claim needs root-cause work — not just proof that something's broken — switch to that skill first. Come back to the doc fix once you know the real behavior.
- **A frontend/UX skill** — docs-reality-audit doesn't evaluate interface or interaction quality. If the project has a UI as part of a broader "review this project" ask, pair it with whichever design skill the machine has. See `docs/EXTERNAL-TOOLING.md` — OliverCode ships none, by scope. Run the two as separate, parallel-purpose passes rather than folding one into the other.
