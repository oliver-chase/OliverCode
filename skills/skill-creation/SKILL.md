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

Ask each question below in order, against the live fleet and not from memory.

## Baseline: every new skill meets this

A skill that ships inside OliverCode may read `$OC/` files and name its sibling skills.

`python3 $OC/skills/audit/scripts/check_skill_structure.py` enforces the rules a script can check, including the 150-word description cap. The rest are judgment calls the audit skill reads.

1. **Generic at creation.** The skill's own files hold no personal fact in code or prose: no name, address, account ID, token or local path. A value the skill needs comes from one config file in the skill folder or from a question in the chat
2. **No read outside the folder.** No `../`, no `$HOME/.claude/skills/<other>/...`, no vault path, no sibling skill's script or config. The skill carries any rule it needs as its own text
3. **Person setup.** The skill asks the person in the chat for what it needs, such as a file, a name or an ID. It asks once per chat and asks the fewest questions. It saves only what nothing else can hold
   - A value that must last between sessions, such as a tracker path or a Slack ID, goes in `.env.local`. Other state lives in a file the person names, or in a Slack message or draft. The skill says which at the top
   - A skill that ships an `.env.local.example` has a setup mode that walks a person through each value
4. **One connector-missing line.** The skill checks a connector with one call. If the connector is missing, it says what to enable and the fallback in one line, then continues
5. **Describe what the skill does, nothing else.** A skill file holds no decision ID, date, issue number or person. It holds no history, ledger, change log, archive note, Known gaps section or maintainer section. It names no vault or fleet-tooling place. A comment says what the code does, never how it came to be. The reason for a rule goes in the family `DECISIONS.md`, the commit message or the issue
6. **Placeholder names.** Exactly three names are fictional-safe: `Jane Doe`, `John Smith`, `Sally May`. Any example person name is one of them
7. **Portable-zip limits.** The `name` field equals the folder name, in lowercase letters, digits and hyphens, at most 64 characters. The `description` field is at most 1024 characters and 150 words or fewer. It leads with the trigger phrases a person says
8. **Name no outside place.** The skill's text never names the owner's vault, a vault folder or an earlier name of the skill. It may name a sibling skill it hands work to, by the skill's name only, never by a path into that skill's folder
9. **The skill folder holds only what the skill uses.** Put the family `DECISIONS.md` and `README.md` in the family folder, beside the skill. Put a script's test beside it as `scripts/test_<script>.py`, or in `<family>/tests/<skill>/` when the skill ships as a zip without developer files
10. **Names a person would say.** A skill, folder or file name uses the word a person says aloud. No number suffix, ticket id or decision id appears in a name or in text the person reads. A decision id may stay in a code comment and in `DECISIONS.md`
11. **Count the files before you finish.** Run `find <skill> -type f | wc -l`. For each file, name what the skill does not need and cut it
12. **Open with a message that says what to send.** A skill that needs input its trigger does not carry has a `## Opening message` section in `SKILL.md`. The section starts with one line: send this first, in one turn, exactly as written. The message says why the result matters, what the skill does and when the person approves. Then it says what input helps and lists the ways to answer. It holds no personal fact, and an answer given to it is never asked again
13. **A step a command can do is a command.** Opening a file, counting rows, comparing two structures or finding a marker is a script that prints the answer, and the text tells the model to run it and act on the output
14. **A script has a test that goes red without its guard.** Build the test, remove the guard once, check that the test fails, then restore it. `check_skill_structure.py --weight` lists the scripts no test names
15. **A skill with several tasks loads one reference per task.** A route row names one file. A setup file loads only when a one-line `check` command says setup is not done
16. **One data file per kind, no dated copies.** A skill that records data appends to one file per kind of thing, and a reading taken over time rolls up to one row a week inside that file once it passes 1,000 rows and 90 days. It writes no file per day, week or run. The skill names its data file and its roll-up point

## 0. Write the target in four lines

Before any file, write four lines and ask for a yes. Line 1: what the skill does in one sentence. Line 2: which values it needs from the person and where each one lives. Line 3: what the folder holds. Line 4: each platform limit you tested and each you guess. Test each guessed limit before the layout depends on it.

## 1. Does an existing skill already cover this?

Search the loaded skill list's names and descriptions for the trigger phrase. Extend an existing skill that covers it with a new reference file or mode. One signal justifies a new sibling: a materially different verb or output type. Run `backlog`'s search step for the working name too. An Epic or Story may already exist. List the family folders live before you pick one, and match sibling naming inside the family.

## 2. Does it keep state?

A tracker, a record store or a growing list needs a home that the connectors and the person's machine can reach, named at the top of `SKILL.md`: a file the person names, a download-out loop, or a Slack post. A skill that appends checks what is there first. A real match merges or updates, a near-duplicate is skipped and flagged, and only a new entry is appended.

## 3. Which connectors?

List each connector the skill uses and what the skill does without it. Write the connector-missing line for each one. A skill with no fallback for a required connector states that it needs the connector, at the top.

## 4. Close by running the checks

The new skill's `SKILL.md` exists by now, with its symlink created and its `skills/INDEX.md` row written. Run, in order:

1. `python3 $OC/skills/audit/scripts/check_skill_structure.py` on the skill folder. Clean means every reference resolves, and every description is within the word cap
2. A clean-room run. Copy the skill alone into an empty skills folder and run its main script or setup mode. A missing file or an unset key at that point is a gap the other checks cannot see

Fix the exact gap each check names, then run it again. Never finish with a named gap open.
