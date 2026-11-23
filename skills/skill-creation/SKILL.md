---
name: skill-creation
description: "Intake walkthrough for a new skill in the skills folder. Checks for overlap with an existing skill first. Holds the baseline every new skill meets, so each skill is personal and portable. Trigger on 'new skill', 'build a skill for X', 'should this be a new skill', 'I need a skill that does Y', 'repair this skill' or 'bring this skill up to the baseline'."
---

# Skill creation

## Opening message

Send this first, in one turn, exactly as written, with no other opening line and no closing recap. A request that already states the skill's job and inputs skips the message.

> A good skill does one job well and works on any machine you copy it to.
>
> First I check that no existing skill covers the job. Then we agree on a four-line target, and I build nothing until you approve it.
>
> The more you tell me, the fewer questions I ask. Rough notes are fine.
>
> You can answer in any of these ways:
> 1. Describe what the skill does in a sentence or two, and what a person would say to trigger it.
> 2. Share an example input and the output you want, such as a file, message or list.
> 3. List the skills or notes you use for this job today, so I can check overlap.

A request to repair or audit an existing skill against the baseline loads `references/repair.md` and skips steps 0 to 2. Otherwise work through the steps below in order.

## Baseline: every new skill meets this

`python3 $OC/skills/audit/scripts/check_skill_structure.py` enforces the 150-word description cap and that each cited skill and file exists. `check_skill_structure.py --baseline` covers rules 1, 2, 5, 6, 8, 16 and 17, and the `.env.local.example` case of 3 and 12, and the audit skill reads the rest. A skill inside OliverCode may read `$OC/` files and name siblings.

1. **Generic at creation.** No name, address, account ID, token or local path in code or prose. A needed value comes from one config file in its folder or a question in the chat
2. **No read outside the folder.** No `../`, no other skill's script or config, no vault path. The skill carries any rule it needs as its own text
3. **Ask once, ask little.** Ask in the chat for a file, name or ID, once per chat. A value that must last between sessions goes in `.env.local`, and a skill that ships an `.env.local.example` has a setup mode that walks through each value
4. **Walk each connector.** Check a connector with one call and name tools as `Server:tool`. When it is missing, set it up when a command or the browser can, else give the exact steps, name the fallback and continue. Never ask in the chat for a password or code
5. **Say what the skill does.** No decision ID, date, issue number, person, history, change log or Known gaps section. Reasons go in the commit message or the issue. One line per paragraph in markdown prose, with no hard-wrapping
6. **Placeholder names.** `Jane Doe`, `John Smith` and `Sally May` are the only example person names
7. **The folder holds only what the skill uses.** A script's test sits beside it as `scripts/test_<script>.py`. Cut each file the skill does not use
8. **Names a person says.** No number suffix, ticket ID or decision ID in a skill, folder or file name
9. **Open with a message that says what to send.** A skill needing input its trigger lacks has a `## Opening message` section that starts "Send this first, in one turn, exactly as written". The message says why the result matters, what the skill does, when the person approves and which answers help
10. **A script does what a command can do.** A script handles its own errors and explains each constant. Each script has a test that goes red when its guard is removed: remove the guard once, watch the test fail, restore it
11. **One reference per task.** A route row names one file, and a setup file loads only when a one-line `check` says setup is not done
12. **Self-installing.** One setup mode takes a fresh copy to working with no manual step: it installs dependencies, creates the config from the example file, connects each connector (rule 4) and writes the schedule, such as a launchd or cron entry, for any recurring job. It is safe to run twice and prints what works
13. **Portable.** Paths use forward slashes and come from the home folder or the skill's own folder, and the skill names any platform it needs. The clean-room copy in step 3 proves it
14. **One data file per kind.** No file per day, week or run. A reading taken over time rolls up to one row a week once the file passes 1,000 rows and 90 days, and the skill names the file and that point
15. **Written for the model that reads it.** The description is in the third person. Add only what Claude does not know, give one default in place of a menu, and use one term per idea. `SKILL.md` stays under 500 lines, references sit one level deep, and the name never contains `claude` or `anthropic`
16. **Steps call scripts.** A skill that ships scripts names the script or command in each step it runs, and the script holds the logic. A step that must happen every time is code, and a rule that must hold is a check that fails
17. **Token-free by default.** A refresh, heartbeat or poll is a script with no model call, and a page refresh never starts a model. A recurring job that needs judgment runs a named gate script first and starts a model only when the gate finds work

## 0. Write the target in four lines

Before any file, write four lines and get a yes: what the skill does, which values it needs and where each lives, what the folder holds, and each platform limit tested or guessed. Test each guessed limit before building on it.

## 1. Does an existing skill already cover this?

Search skill names and descriptions for the trigger phrase, and run `backlog`'s search for the working name. Extend an existing skill with a reference or mode. A different verb or output justifies a new sibling named like its family.

## 2. State and connectors

A tracker or growing list needs a home the person's machine can reach, named in `SKILL.md`. A skill that appends checks for a match: merge a real match, flag and skip a near-duplicate, append only a new entry. List every connector, how setup connects it and what the skill does without it.

## 3. Build and close

Create the skill, its symlink and `skills/INDEX.md` row, then run `$OC/skills/audit/scripts/check_skill_structure.py` on the folder and a clean-room run: copy the skill alone into an empty skills folder and run its setup mode, then its main script. Test the skill on Haiku, Sonnet and Opus with three real requests. Fix each gap a check names and run it again.
