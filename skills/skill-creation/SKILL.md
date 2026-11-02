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

The intake path for a new skill. Ask each question below in order, against the live fleet, not from memory. Every skill is personal and portable: it is one folder that works on any machine the owner copies it to.

## Baseline: every new skill meets this

These rules apply to skills in a personal skills folder. A skill that ships inside OliverCode may read `$OC/` files and name its sibling skills.

`python3 skills/audit/scripts/check_skill_structure.py` and `check_descriptions.py` enforce the rules a script can check. The rest are judgment calls the audit skill reads.

1. **Generic at creation.** The skill's own files hold no personal fact in code or prose: no name, address, account ID, token or local path. A value the skill needs comes from one config file in the skill folder or from a question in the chat.
2. **No read outside the folder.** No `../`, no `$HOME/.claude/skills/<other>/...`, no vault path, no sibling skill's script or config. The skill carries any rule it needs as its own text.
3. **Person setup.** The skill asks the person in the chat for what it needs, such as a file, a name or an ID. It asks once per chat and asks the fewest questions. It saves only what nothing else can hold.
   - A value may go in `.env.local` when it must last between sessions: a tracker path, a Slack ID, an avoid-list. Other state lives in a file the person names, or in a Slack message or draft. The skill says which at the top.
   - A skill that ships an `.env.local.example` has a setup mode that walks a person with no `.env.local` through each value.
4. **One connector-missing line.** The skill checks a connector with one call. If the connector is missing, it says what to enable and the fallback in one line, then continues.
5. **Describe what the skill does, nothing else.** A skill file holds no decision ID, date, issue number or person. It holds no history, ledger, change log, archive note, Known gaps section or maintainer section. It names no vault or fleet-tooling place. A comment says what the code does, never how it came to be. The reason for a rule goes in the family `DECISIONS.md`, the commit message or the issue.
6. **Placeholder names.** Exactly three names are fictional-safe: `Jane Doe`, `John Smith`, `Sally May`. Any example person name is one of them.
7. **Portable-zip limits.** The `name` field equals the folder name, in lowercase letters, digits and hyphens, at most 64 characters. The `description` field is at most 1024 characters and under 150 words. It leads with the trigger phrases a person says.
8. **One line per paragraph.** Write each paragraph and each list item on one source line. A hard-wrapped line shows as short uneven rows.
9. **Name no other skill and no outside place.** The skill's text never names a sibling skill, the owner's vault, a vault folder, or an earlier name of the skill. A description says what the skill is not for and names no alternative.
10. **The skill folder holds only what the skill uses.** Put the family `DECISIONS.md` and `README.md` in the family folder, beside the skill. Put tests in `<family>/tests/<skill>/`. A zip of the folder then carries no developer file.
11. **Names a person would say.** A skill, folder or file name uses the word a person says aloud. No number suffix, ticket id or decision id appears in a name or in text the person reads. A decision id may stay in a code comment and in `DECISIONS.md`.
12. **Count the files before you finish.** Run `find <skill> -type f | wc -l`. For each file, name what the skill does not need and cut it.
13. **Open with a message that says what to send.** A skill a person triggers cold has a `## Opening message` section in `SKILL.md`. The section starts with one line: send this first, in one turn, exactly as written. The message says why the result matters, what the skill does and when the person approves. Then it says what input helps and lists the ways to answer. It holds no personal fact, and an answer given to it is never asked again.
14. **A step a command can do is a command.** Opening a file, counting rows, comparing two structures or finding a marker is a script that prints the answer. The text tells the model to run it and to act on the output. A model reading a file by hand on every run costs tokens and gets it wrong in a new way each time.
15. **A script has a test that goes red without its guard.** Build the test, remove the guard once, check that the test fails, then restore it. `check_skill_structure.py --weight` lists the scripts no test names.
16. **A skill with several tasks loads one reference per task.** A route row names one file. A setup file loads only when a one-line `check` command says setup is not done.

## 0. Write the target in four lines

Before any file, write four lines and ask for a yes. Line 1: what the skill does in one sentence. Line 2: which values it needs from the person and where each one lives. Line 3: what the folder holds. Line 4: each platform limit that you tested, and each one that you guess. Run a real test of each guessed limit before the layout depends on it. A layout that comes before the agreed target gets rebuilt.

## 1. Does an existing skill already cover this?

Search the loaded skill list's names and descriptions for the trigger phrase. Extend an existing skill that covers it with a new reference file or mode. One signal justifies a new sibling: a materially different verb or output type. Run `backlog`'s search step for the working name too. An Epic or Story may already exist. List the family folders live before you pick one, and match sibling naming inside the family.

## 2. Does it keep state?

A tracker, a record store or a growing list needs a home that the connectors and the person's machine can reach. Name it at the top of `SKILL.md`. The choices are a file the person names on their machine, a download-out loop, or a Slack post. A skill that appends to a list checks what is there before writing. A real match merges or updates. A near-duplicate gets skipped and flagged. Only a new entry gets appended.

## 3. Automation or agent?

The job may be repeatable automation, or it may need judgment each time. Load `automation-first-agent-design` for that decision.

## 4. Which connectors?

List each connector the skill uses and what the skill does without it. Write the connector-missing line for each one. A skill with no fallback for a required connector states that it needs the connector, at the top.

## 5. Close by running the checks

The new skill's `SKILL.md` exists by now, with its symlink created and its `README.md` row written. Run, in order:

1. `python3 skills/audit/scripts/check_skill_structure.py` on the skill folder. Clean means every reference resolves and no file goes unused.
2. `python3 skills/audit/scripts/check_descriptions.py` on the skills folder. Clean means every description is within the word cap.
3. A clean-room run. Copy the skill alone into an empty skills folder and run its main script or setup mode. A missing file or an unset key at that point is a gap the other checks cannot see.

Fix the exact gap each check names, then run it again. Never finish with a named gap open.
