---
name: skill-creation
description: "Intake walkthrough for a new skill in the skills folder. Checks for overlap with an existing skill first. Holds the baseline every new skill meets, so each skill is personal and portable. Trigger on 'new skill', 'build a skill for X', 'should this be a new skill', or 'I need a skill that does Y'."
---

# Skill creation

## Opening message

Send this first, in one turn, exactly as written, with no other opening line and no closing recap. A request that already states the skill's job and inputs skips the message.

> A good skill does one job well and works on any machine you copy it to.
>
> First I check that no existing skill already covers the job. Then we agree on a four-line target, and I hold the new skill to the baseline. I build nothing until you approve that target.
>
> The more you tell me, the fewer questions I need to ask. Rough notes are fine.
>
> You can answer in any of these ways:
> 1. Describe what the skill should do in a sentence or two, and what a person would say to trigger it.
> 2. Share an example of the input and the output you want, such as a file, a message or a list.
> 3. List the skills or notes you use for this job today, so I can check for overlap.

Work through the steps below in order, against the live fleet and not from memory.

## Baseline: every new skill meets this

`python3 $OC/skills/audit/scripts/check_skill_structure.py` enforces the name, description limits (150 words, 1,024 characters) and references. The rest are judgment calls that the audit skill reads, and rules 1 and 2 are its self-containment lens. A skill that ships inside OliverCode may read `$OC/` files and name its sibling skills.

1. **Generic at creation.** No name, address, account ID, token or local path in code or prose. A value the skill needs comes from one config file in its folder or from a question in the chat
2. **No read outside the folder.** No `../`, no other skill's script or config, no vault path. The skill carries any rule it needs as its own text and names a sibling by name only
3. **Ask once, ask little.** Ask the person in the chat for a file, name or ID, once per chat. A value that must last between sessions goes in `.env.local`, and a skill that ships an `.env.local.example` has a setup mode that walks through each value
4. **One connector-missing line.** Check a connector with one call. When it is missing, say what to enable and the fallback, then continue
5. **Say what the skill does.** No decision ID, date, issue number, person, history, ledger, change log or Known gaps section. Reasons go in `DECISIONS.md`, the commit message or the issue
6. **Placeholder names.** `Jane Doe`, `John Smith` and `Sally May` are the only example person names
7. **The folder holds only what the skill uses.** A script's test sits beside it as `scripts/test_<script>.py`. Count the files with `find <skill> -type f | wc -l` and cut each one the skill does not need
8. **Names a person says.** No number suffix, ticket ID or decision ID in a skill, folder or file name
9. **Open with a message that says what to send.** A skill that needs input its trigger does not carry has a `## Opening message` section that starts "Send this first, in one turn, exactly as written". The message says why the result matters, what the skill does, when the person approves and which answers help
10. **A script does what a command can do.** Opening a file, counting rows and comparing structures are scripts that print the answer. Each script has a test that goes red when its guard is removed: remove the guard once, watch the test fail, restore it
11. **One reference per task.** A route row names one file, and a setup file loads only when a one-line `check` says setup is not done
12. **One data file per kind.** No file per day, week or run. A reading taken over time rolls up to one row a week once the file passes 1,000 rows and 90 days, and the skill names the file and the roll-up point

## 0. Write the target in four lines

Before any file, write four lines and ask for a yes: what the skill does, which values it needs and where each lives, what the folder holds, and each platform limit tested or guessed. Test each guessed limit before the layout depends on it.

## 1. Does an existing skill already cover this?

Search the loaded skill names and descriptions for the trigger phrase, and run `backlog`'s search for the working name. Extend an existing skill with a reference or mode. A materially different verb or output type justifies a new sibling, named like its family.

## 2. State and connectors

A tracker or growing list needs a home the person's machine can reach, named at the top of `SKILL.md`. A skill that appends checks for a match first: merge a real match, skip and flag a near-duplicate, append only a new entry. List each connector with what the skill does without it.

## 3. Build and close

Create the skill, its symlink and its `skills/INDEX.md` row, then run `check_skill_structure.py` on the folder and a clean-room run: copy the skill alone into an empty skills folder and run its main script or setup mode. Fix the exact gap each check names and run it again. Never finish with a gap open.
