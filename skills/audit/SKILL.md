---
name: audit
description: "The one audit for anything: a whole repo or suite, a skill or skill family, the docs, a commit range before it closes, or a plan before it runs. Reads every line, verifies each finding against the code, and files fixes as one epic. Trigger on 'audit this', 'QA this', 'review tonight's work', 'are the docs accurate', 'audit my skills', 'audit my Claude config', 'is this over-engineered' or 'pressure test this plan'."
---

# Audit

An audit tells the owner what a target is meant to be, what it is today and what to change, with every claim checked against the files. Every route runs the same procedure and writes the same report, and only the scope and the added checks differ. Every script path below is relative to this skill's folder, so run scripts from there.

## Opening message

Send this first, in one turn, exactly as written, with no other line before or after it. A request that names its target, such as "audit this" inside a repo, skips it and audits that repo whole.

> An audit is only worth acting on when every finding is checked against the real files.
>
> I read every line of what you point me at and check it against seven lenses: how a new user gets it working, whether it runs on its own, whether its claims are true, whether each idea has one home, what it carries that nothing uses, what it costs to load, and whether its writing follows the voice. I check each finding myself before I report it, then file the fixes in your backlog.
>
> You can answer in any of these ways:
> 1. Say "audit this" inside a repo, and I will audit the whole repo.
> 2. Name a skill, a family of skills or a folder of docs, and I will audit that.
> 3. Ask me to review the work this session just did, and I will audit its commits before they close.
> 4. Give me a plan file, and I will test its claims before anyone runs it.

## Routes

Pick the route the request names and load its file. A request that fits two routes runs the wider one.

| The request names | Route | Load |
|---|---|---|
| A repo, a suite, a system, or nothing ("audit this") | Whole target | `references/system.md` |
| A skill, a skill family or a skills folder | Skills | `references/skills.md` |
| The docs, a README, or "are these accurate" | Docs | `references/docs.md` |
| This session's work, a commit range, "QA this" | Changes | `references/changes.md` |
| A plan file, or a plan about to run | Plan | `references/plan.md` |

Every route loads `references/lenses.md`. A target with a user interface also loads `references/frontend-ux.md`.

## The procedure

1. **Scope.** List every tracked file in scope with its size: `git ls-files <scope> | xargs wc -lc`. The list is the read contract, and the report names it.
2. **Read every line.** Split a scope larger than one reader can hold across reviewer agents, about 3,000 lines each. Brief each reviewer with its file list, the seven lenses and the output shape in `references/system.md`. A reviewer reads its files in full and edits nothing.
3. **Re-check.** Before reporting, rerun the evidence for each reviewer's biggest claims: a security defect, a behavior bug and anything the report recommends deleting. A claim that does not reproduce is dropped.
4. **Report** in the order below, written per `docs/VOICE.md` in the target repo or `~/.claude/VOICE.md`.
5. **File.** Search the backlog first, then file one epic for the audit and one story per boundary, each with its priority, size, the evidence and a command that shows the problem before the fix and its absence after. The repo's `CLAUDE.md` names its backlog. Use `backlog`, or `docs/BACKLOG.md` where the repo has no Project.

Fix nothing during the audit, with three exceptions: a fix the owner asked for in the same request, the changes route, which fixes its findings before the commit, and the plan route, which appends its findings to the plan.

## The report

1. What the target is meant to be, and for whom, in plain words
2. What it is today: its parts and size, what loads in every session and what loads on use, and how a new user gets it, starts it and what it does for them. Run `bash scripts/size.sh <target>` and put its table in the report: files, lines and KB for code, tests, docs and skills, plus the open backlog by status
3. Whether the size makes sense, both in how the text is written and in how it runs. Answer "is it the right size" with a verdict, the ratios from `size.sh` (tests per 100 lines of code, docs and skills per 100 lines of code and tests), and the lines to cut or add. Say how much is left: open issues by status and the added work. Run `python3 scripts/fleet_check.py --time <target>` and put its budget lines in the report: test count and runtime, doc words and skill words against `docs/BUDGET.json`. The changes route runs `fleet_check.py <target>` without `--time`, which skips the test run
4. The findings, grouped by lens, each with a file and line, the evidence and the smallest fix
5. Everything over-engineered, duplicated, competing or unused, named one by one with the evidence of use, the test cut list and the standard tool for each rule mechanism
6. What was read, what the lead re-checked, and what is still unknown
7. Whether the fixes reach the goal. Measure files, skills and bytes before and after, and label any estimate as one. Say whether a new user would reach a result by talking, and whether someone who has never seen the target could use it. When the fixes only trim and leave the shape as it is, say so plainly and propose the structural moves that would reach the goal, such as a core with add-ons switched off by default or a small skill folded into its nearest neighbor. List the open backlog items that work against the goal, for the owner to keep, defer or close

## Rules

- A finding is a defect with evidence. A style preference outside the voice, a hypothetical and a "consider" are not findings
- Owner data in a shipped file is a finding even when no list of names exists: a person's or business's name, an ID, a color, a motif or a niche written as the default
- Count each voice violation by kind, and name the file of every competing writing rule. The `fleet_check.py` voice lines give the file and line of each violation it can find, and its board lines name every difference from `shared/kanban-baseline.json`
- Say what could not be verified, and why
