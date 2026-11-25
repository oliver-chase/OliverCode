# To done

"Audit and fix" means finish the agreed, worthwhile scope—not empty the entire repository backlog. Preserve safety and correctness; do not turn unrelated open issues or cosmetic observations into blockers.

1. **Gate.** Follow the requested mode. Report-only stops after the evidence-based report. Fix mode proceeds with safe, in-scope changes and asks only for decisions that materially block progress.
2. **Prioritize.** Handle safety/data-loss defects first, then correctness and recovery, then high-value simplification and owner experience. Group related changes so each useful batch can land independently.
3. **Implement.** Re-check each change against live source. Run focused tests and relevant checks. Use full validation when the change crosses subsystem boundaries or before a release. Commit and deliver through the repository's protected-branch workflow; never bypass required safety checks.
4. **Escalate selectively.** Ask the owner about genuine trade-offs, permissions, destructive actions and ambiguous requirements. Continue independent work while waiting.
5. **Recheck.** Verify changed behavior and report what was run, skipped, failed and not run. Do not require a fresh-reader pass for every low-risk change.
6. **Close the loop.** Update or close only the issues actually completed, with evidence. Leave unrelated backlog items alone. A target is done when the agreed scope is complete and no P0/P1 issue within that scope remains—not when every open issue in the repository is closed.
7. **Tell the owner once.** Summarize outcomes, commits/PRs, checks and remaining risks. Do not offer a recurring audit schedule unless it would solve a demonstrated ongoing problem.
