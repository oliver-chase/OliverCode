# Whole target

The default route: a repo, a suite or a system read end to end.

## Before reading

1. State what the target is meant to be, from the README's first lines and the entry skill, and check it against the code
2. Count the files and lines per folder:

```bash
git ls-files | wc -l
git ls-files | xargs wc -l | tail -1
for d in $(git ls-files | cut -d/ -f1 | sort -u); do printf "%-30s %5s files %7s lines\n" "$d" "$(git ls-files "$d" | wc -l)" "$(git ls-files "$d" | xargs cat 2>/dev/null | wc -l)"; done
```

3. Measure what loads: the `CLAUDE.md` chain and its imports, and each skill's description and body
4. Run `python3 "$OC/skills/audit/scripts/portability.py" <target>`, and hand its rows to the docs and self-containment readers
5. A reader judges the sweep rows and does not search for them again

## The reviewer brief

Give each reader this brief, one reader per batch from `audit_ledger.py --batches`, run in waves as step 3 of the procedure says until no batch is left.

> You are auditing one slice of `<target>`, line by line. Make no edits.
>
> The target is meant to be: `<one sentence>`. Your slice is this batch: `<the batch's files>`. Read every line of every file in full, and name any file you did not finish.
>
> Apply the ten lenses in `<path to lenses.md>`, and verify each finding against the code before you report it. Read `<path to VOICE.md>` first.
>
> Report only defects with evidence, of every kind: bugs, over-engineering, inefficiency, dead code, optimization, missing, stale or wrong documentation, and functionality gaps. Return a ranked list, each with an id (R1, R2 and so on), the lens, `file:line`, the defect in one sentence, the command or code that proves it and the smallest fix. Then add a second list headed "Simplify": every file, function, export, flag, config key, test or gate in your slice that could be deleted, merged, shrunk or replaced by a standard tool with the same behavior, each with the lines it removes and the evidence of use. Name any file over 400 lines and say whether it should split. Then list the files you read that are clean, and your totals of files and lines read. Keep it under 1,500 words. The audit re-checks your claims, so cite the exact line and command. Read only: do not run tests, scratch repos or mutations. For a suspected bug or a test that cannot fail, cite the file and line and the one command to run.

## After the reviewers return

- Re-check the biggest claims yourself and drop any that do not reproduce
- Merge duplicates across readers, and add findings only visible across areas, such as one rule in two areas. An audit split across sessions does this with `findings.py cross`, as "A chunked audit" in `SKILL.md` describes
- Judge the shape, which no reviewer sees from one slice: name each small skill that its nearest neighbor could absorb, and what a core with add-ons off by default would hold
- Write each lens's opening sentence for the owner before its table: what the lens's findings mean and the next step, in one or two sentences

## Filing

Track only substantive, independently actionable follow-up. Search existing issues first and extend one when it already owns the outcome. Group related work into a small number of issues. Do not file cosmetic observations, speculative recommendations, or every item in a Simplify list. Small safe fixes belong in the current change when the owner asked for fixes; otherwise report them without manufacturing backlog work. Each new issue needs evidence, an outcome, acceptance criteria and a clear reason it cannot simply be handled now.
## Filing

Build a ledger first: one row per finding and per "Simplify" item, each with its issue number, before the report goes out. The epic states `Size target: at most N lines` and the order of the stories. One epic named for the result, such as "Every job has one home". One story per boundary that can land on its own: a security fix, a set of deletions, one merge of skills, the docs, the voice, the tests. Order them so deletions land before the docs and voice work that would otherwise rewrite text about to go.
