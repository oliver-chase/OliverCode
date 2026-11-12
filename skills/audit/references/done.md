# To done

The whole-target route continues past the report until the target is done, and the owner hears once when it is.

1. **Order.** P0 stories first, then deletions, then merges and fixes, then documentation and the catalog, then text trims, then tests and voice. Deletions land before the docs and voice work that would rewrite the same text
2. **One story at a time.** Re-check the story against the live files, since another session may have changed them. Fix it, run the repo's validation and the story's before and after command, commit, push and merge as the repo's `CLAUDE.md` says, and close the story with the evidence. One commit never mixes stories
3. **Owner decisions.** Ask for every open decision in one message, each with a recommendation, then keep working on everything else. Record each answer on its story. A rejected fix is accepted as a row in `<target>/docs/AUDIT-ACCEPTED.md` with its reason
4. **Record the sharing verdict.** Write `Sharing: portable` or `Sharing: personal - reason` in the README or `<target>/docs/SHARING.md` from lens 10, and file a story for every blocker the verdict leaves
5. **Build the catalog.** Run `python3 scripts/catalog.py --write` after the last story that changes a part, and commit `<target>/docs/CATALOG.md`
6. **Audit again.** When every story is closed, run steps 1 to 4 of the procedure with fresh readers who are not shown the earlier findings. Read only the facets the fixes touched, and run the sweep, catalog and portability scripts on everything. File, fix and repeat. A third pass that still finds a P0 or P1 stops the loop and goes to the owner with the list
7. **Check.** `python3 scripts/done_check.py <repo> --epic <N>` (repeat `--epic` for each epic) must print `done`: the validation passes, budgets are met, the sweep and catalog are clean, the sharing verdict is recorded with no blocker it counts, and the epic and its stories are closed
8. **Tell the owner once.** Give the numbers (files, lines, skill words, always-loaded tokens, tests, test time), the catalog location, the sharing verdict with its reason and every accepted row. Offer a daily scheduled done check that notifies the owner the first time it stops printing `done`
