# Simplification review

A judgment review of one skill folder or one family. It finds what to remove, inline, merge or shorten, and it never adds a feature. Read every file in scope in full before judging any of it.

## Scope

Read these files in full:

- Each `SKILL.md` and every file in `references/`, `modes/` and `assets/`.
- Every script and its tests.
- Every JSON config and fixture.
- Its README row.

A pptx example, a template, a fixture, a regression transcript or an example document may break a content rule. Do not file or fix that. Duplication, dead files and file weight still count for those files. Text that a build copies into a finished document as written is output, and it keeps its rules.

## The six questions

Judge each word, line, function and file against these.

1. **Words.** Does the sentence tell the model something it would not do anyway? Does it restate a rule that has a home elsewhere? Does it hedge, narrate how the text changed, or give an example that only restates the rule above it? Does a step repeat what its reference file states?
2. **Structure.** Does a route load a file it does not need? Is a reference file one paragraph in disguise? Do two modes overlap? Is there a menu, a setup question, a config knob, a fallback or a branch that no real user takes?
3. **Code.** A function with one caller. A wrapper that only forwards. A flag never set to a non-default value. A per-type spec with empty fields. Two scripts that do one job. A hand-rolled version of what the standard library or a bundled library does. An error path that cannot occur. A test that asserts a mock or a constant. A comment that narrates the mechanism and does not name the defect it prevents. A script nothing calls.
4. **Duplication.** Identical or near-identical files across skills. The same command chain, list, rule or schema written in more than one place. A copy next to its master.
5. **Systems.** A gate, budget, baseline, fixture or setup step that guards something that is gone, or that no defect justifies. A baseline that only records the current count and never drops. A gate that cannot name the defect it prevents goes.
6. **Work by hand.** Does the text tell the model to open a file, count, compare or read a structure that one command could print? Does a recurring task repeat what the last run already did, with no saved date to start from? Does a route load a setup file on every run when a one-line check could say whether setup is done?

## Decide each finding

Give every finding a file and a line, and one decision.

- **Remove.** Cut it and every call site.
- **Inline.** Fold it into its only caller or reader.
- **Merge.** Name the surviving home.
- **Rewrite.** Shorter, with the same meaning.
- **Keep.** Write the reason in plain words.

A finding that changes a mechanism or crosses a family boundary becomes its own backlog item with the evidence in its body. Do not widen a backlog item silently.

## Check before you trust a signal

- The weight check lists a file as unreferenced when no file names its exact filename. A skill that loads `modes/<mode>.md` from a table, or loads a whole folder, reads as unreferenced. Read how the router loads before you remove it.
- A test that stays green without the code it protects is not a guard. Remove the guard, check that the test goes red, then restore it.
- A repeated paragraph may be shared on purpose. Open both places and judge.

## Keep behavior the same

Before the first edit, run the skill's own tests and the fleet gates, and keep the output.

```bash
# run from this skill's folder
python3 scripts/check_clarity.py
python3 scripts/check_skill_structure.py
```

Run them again after each removal.

## Baseline numbers

Record these before the first edit and again after the last, from the same commands. Dated measurements go in the backlog item's comments, not in a doc.

```bash
# run from this skill's folder; <FAMILY_PATH> is the folder under review
python3 scripts/check_skill_structure.py --weight
find <FAMILY_PATH> -type f \( -name '*.py' -o -name '*.js' -o -name '*.cjs' -o -name '*.sh' -o -name '*.jsx' \) -not -path '*/vendor/*' -not -path '*/.pytest_cache/*' -not -path '*/tests/*' -not -name 'test_*' | xargs wc -l | tail -1
find <FAMILY_PATH> -type f -name '*.md' -not -path '*/.pytest_cache/*' | xargs wc -w | tail -1
find . -type f \( -name '*.py' -o -name '*.js' -o -name '*.cjs' -o -name '*.md' -o -name '*.json' -o -name '*.jsx' \) -not -path './.git/*' -not -path '*/.pytest_cache/*' -not -path '*/dist/*' -not -path './README.md' -size +1k -exec md5 -r {} + | sort | awk '{h=$1; $1=""; a[h]=a[h] "\n" $0; c[h]++} END{for(h in c) if(c[h]>1) print c[h] " copies:" a[h]}'
```

The first command prints files, size, `SKILL.md` lines, description words, unreferenced and uncalled files for every skill. Run `check_skill_structure.py --routes` to list the route rows that load more than 2000 words for one task. The last three print code lines, words and identical files across skills. No output from the code-lines command means the folder has no scripts.

## Report

List the files you read, grouped by kind. Give a findings table with file, line, question, the quoted words, the decision and the surviving home. Give the numbers from the baseline commands, before and after. A result of nothing found is valid only with the list of what you read and why you keep each file.
