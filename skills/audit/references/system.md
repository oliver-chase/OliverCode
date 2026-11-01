# Whole target

The default route: a repo, a suite or a system read end to end.

## Before reading

1. State what the target is meant to be. Take it from the README's first lines and the entry skill, then check it against what the code does
2. Measure it:

```bash
git ls-files | wc -l
git ls-files | xargs wc -l | tail -1
for d in $(git ls-files | cut -d/ -f1 | sort -u); do printf "%-30s %5s files %7s lines\n" "$d" "$(git ls-files "$d" | wc -l)" "$(git ls-files "$d" | xargs cat 2>/dev/null | wc -l)"; done
```

3. Measure what loads: the `CLAUDE.md` chain and its imports, and each skill's description and body
4. Split the files into reviewer areas of about 3,000 lines, keeping each area whole: code, tests, docs, skills, templates

## The reviewer brief

Give each reviewer exactly this, filled in. One reviewer per area, all started at once.

> You are auditing one slice of `<target>`, line by line. Make no edits.
>
> The target is meant to be: `<one sentence>`. Your slice: every tracked file under `<paths>`, listed with `git ls-files <paths>`. Read every line of every file in full.
>
> Apply these seven lenses, and verify each finding against the code before you report it: autonomy and user flow, self-containment, accuracy, one home per concept, over-engineering and unused parts, token cost in use, and voice. The checks for each are in `<path to lenses.md>`. Read `<path to VOICE.md>` first.
>
> Report only defects with evidence. Return a ranked list, each with the lens, `file:line`, the defect in one sentence, the command or code that proves it and the smallest fix. Then list the files you read that are clean, and your totals of files and lines read. Keep it under 1,500 words.

## After the reviewers return

- Re-check the biggest claims yourself, as the procedure says, and drop any that do not reproduce
- Merge duplicates across reviewers, and add the findings that only show across areas: the same rule in two areas, and a feature whose code, docs and tests sit in three areas and are all unused
- Size the cut. For each proposed removal, measure its lines and files, and total them against today's size

## Filing

One epic named for the result, such as "Every job has one home". One story per boundary that can land on its own: a security fix, a set of deletions, one merge of skills, the docs, the voice, the tests. Order them so deletions land before the docs and voice work that would otherwise rewrite text about to go.
