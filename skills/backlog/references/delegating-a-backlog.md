# Delegating a backlog

Use this when an owner asks for a whole backlog to be finished and several agents will build it. It records what held up when several agents finished a backlog.

## Split by the files a story touches

Group stories so that no two builders edit the same file, then give each builder one group. Name the groups' files in each brief and tell the builder to avoid the others'. Shared files (a size baseline, a skills index) take the higher number or both edits at merge.

## The builder brief

- The repo, the board and the commit it starts from
- A worktree of its own: `git worktree add -b agent/<name> ../<repo>-wt-<name> origin/main`, and never the main checkout
- The story numbers in order, and the rule that a story with no Gherkin gets scenarios written into its body first, because the sign-off check needs scenarios to confirm
- Validation: a quick check on the touched test modules for every commit and the full run once at the end
- The log line and the board move after each story
- Push the branch and stop; the lead merges
- A final report with a commit per story, what was verified and how, and what was not

## Independent QA

A reviewer who built nothing reads the Gherkin, runs a direct check of each scenario and writes `Story N: PASS|FAIL|BLOCKED; confirmed: <scenario name>; <scenario name>` per story. Name every scenario by its whole name in the one report that gets logged. The sign-off check reads one comment, so a later partial re-check hides the scenarios an earlier report confirmed, and the story stays open. Report PARTIAL work as FAIL or BLOCKED, since the logger accepts only those three.

## Fixers and re-checks

Send each QA report to a fixer as the spec, then a second reviewer re-checks only what failed. A finding that no code can prove (an agent ran, an owner said something) becomes a recorded row the agent writes, or the scenario is reworded with the owner's yes.

## Merging

1. Fast-forward when the branch is based on the current main, otherwise merge in a throwaway worktree and fix conflicts there.
2. Run the full validation on the merged result, then push.
3. Never run `git pull --rebase` on a main that holds merge commits: it replays every merge and conflicts.
4. A worktree has no `.venv`; the validation script finds the main checkout's.

## Pitfalls seen

- A wait loop that matches its own command line never ends; wait on a log line or a file
- Add `--quick` checks for speed, and the full validation before every merge
