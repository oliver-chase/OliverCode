# Whole target

The default route: a repo, a suite or a system read end to end.

## Before reading

1. State what the target is meant to be. Take it from the README's first lines and the entry skill, then check it against what the code does
2. Measure it. `bash scripts/size.sh <target>` prints files, lines and KB by kind (code, tests, docs, skills, config), the test and documentation ratios, and the open backlog by status. It is the table the report's size sections cite. The loop below adds the per-folder view:

```bash
git ls-files | wc -l
git ls-files | xargs wc -l | tail -1
for d in $(git ls-files | cut -d/ -f1 | sort -u); do printf "%-30s %5s files %7s lines\n" "$d" "$(git ls-files "$d" | wc -l)" "$(git ls-files "$d" | xargs cat 2>/dev/null | wc -l)"; done
```

3. Measure what loads: the `CLAUDE.md` chain and its imports, and each skill's description and body
4. Run `python3 scripts/sweep.py <target>`, which lists unused code, orphans and oversized files with no model. A reader judges those rows and does not search for them again

## The reviewer brief

Give each reader this brief. At most three readers, each on `haiku`, all started at once: code, tests, and docs with skills and config. A scope of 3,000 lines or fewer needs none.

> You are auditing one slice of `<target>`, line by line. Make no edits.
>
> The target is meant to be: `<one sentence>`. Your slice: every tracked file under `<paths>`, listed with `git ls-files <paths>`. Read every line of every file in full.
>
> Apply these seven lenses, and verify each finding against the code before you report it: autonomy and user flow, self-containment, accuracy, one home per concept, over-engineering and unused parts, token cost in use, and voice. The checks for each are in `<path to lenses.md>`. Read `<path to VOICE.md>` first.
>
> Report only defects with evidence, of every kind: bugs, over-engineering, inefficiency, dead code, optimization and stale or wrong documentation. Return a ranked list, each with an id (R1, R2 and so on), the lens, `file:line`, the defect in one sentence, the command or code that proves it and the smallest fix. Then add a second list headed "Simplify": every file, function, export, flag, config key, test or gate in your slice that could be deleted, merged, shrunk or replaced by a standard tool with the same behavior, each with the lines it removes and the evidence of use. Name any file over 400 lines and say whether it should split. Then list the files you read that are clean, and your totals of files and lines read. Keep it under 1,500 words. The lead re-checks your claims, so cite the exact line and command.

## After the reviewers return

- Re-check the biggest claims yourself, as the procedure says, and drop any that do not reproduce
- Merge duplicates across readers, and add the findings only visible across areas, such as one rule in two areas or a feature unused in code, docs and tests alike
- Judge the shape, which no reviewer sees from one slice. List every skill with its size and trigger, then name each small skill that its nearest neighbor could absorb, and what a core with add-ons switched off by default would hold
- Size the cut: lines and files per removal, totaled against today's size

## Filing

Build a ledger first: one row per reviewer finding and per "Simplify" item, with its issue number. Every row has an issue before the report goes out. The epic states a size target in lines and the order of the stories. One epic named for the result, such as "Every job has one home". One story per boundary that can land on its own: a security fix, a set of deletions, one merge of skills, the docs, the voice, the tests. Order them so deletions land before the docs and voice work that would otherwise rewrite text about to go.
