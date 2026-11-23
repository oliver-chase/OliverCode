# Repair an existing skill

This procedure brings one existing skill up to the baseline in `SKILL.md`. It changes only what the owner approves.

## 1. Find the skill

Take the skill folder from the owner. When the owner gives a skill name, look for the folder in the skills folder and confirm the path in one line. A frozen skill is one the owner has said changes only on request. Read and report on it, and edit it only when the owner asks for the repair in the same message.

## 2. Run the mechanical rules

```bash
python3 "$OC/skills/audit/scripts/check_skill_structure.py" --baseline <folder>
```

`$OC` is the OliverCode checkout, which the first lines of `~/.claude/CLAUDE.md` resolve. Any `python3` from 3.9 on runs the checker.

The checker covers rules 1, 2, 5, 6, 8, 16 and 17 in full. For rules 3 and 12 it covers only a skill that ships `.env.local.example` with no setup mode, and the rest of those rules is read in step 3. Record the count of findings per rule. This is the before number.

## 3. Read the judgment rules

Read `SKILL.md`, each reference, each script and each config in the folder against these rules, one at a time:

- Rule 3: a value asked for twice in one chat, or a value that must last between sessions and is not saved
- Rule 12: any skill that has a config file, a dependency, a connector or a schedule needs a setup mode that does each of those and is safe to run twice
- Rules 4, 7, 9, 10, 11, 13 and 14
- Rule 15, the parts the checker does not run, which the rule in `SKILL.md` lists

A gap needs the file and line that show it, and a rule with no evidence has no gap. When a pass is read only, rule 10's remove-the-guard test cannot run: mark that rule `unknown` with the reason "not run", and run the test in step 6 for each test the repair adds.

## 4. Print one list

Print one table of every gap, mechanical and judgment, with these columns:

| Rule | File and line | Evidence | Smallest fix |
|---|---|---|---|

The smallest fix is the least change that closes the gap. Three marks keep the table honest:

- `unknown` with the reason, for a rule you could not judge from the files. It is not a gap and the report lists it
- `false positive` with the evidence, for a checker finding that misreads the text. It is not a gap and the count leaves it out
- `owner decision` with the options, for a gap whose fix changes a shared file, a linked or byte-identical copy that a manifest declares, or a behavior the skill's users rely on

When no row is a gap, reply "no gaps", change nothing and stop.

## 5. Apply the approved fixes

Wait for the owner to say which fixes to apply. Apply only those. Approving "the recommended fixes" never applies an `owner decision` row. Keep every rule and fact the skill carries, and add no history, ticket ID or date to it. A fix the owner skips stays in the report as a gap left.

## 6. Check again

Rerun the checker from step 2 for the after number. Then run the clean-room test from step 3 of `SKILL.md`: copy the skill alone into an empty skills folder, run its setup mode, then run its main script. Fix any failure the copy shows, with the owner's approval, and run it again.

## 7. Report

Report in plain sentences, with the count per rule before and after, the clean-room result and each gap left with the reason it stays. Close with the one next action, such as approving a skipped fix.
