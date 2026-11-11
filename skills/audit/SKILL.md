---
name: audit
description: "The one audit for anything: a whole repo or suite, a skill or skill family, the docs, a commit range before it closes, or a plan before it runs. Reads every line, verifies each finding against the code, and files fixes as one epic. Trigger on 'audit this', 'QA this', 'review tonight's work', 'are the docs accurate', 'audit my skills', 'audit my Claude config', 'is this over-engineered' or 'pressure test this plan'."
---

# Audit

An audit tells the owner what a target is meant to be, what it is today and what to change, with every claim checked against the files. Every route runs the same procedure and writes the same report. Every script path below is relative to this skill's folder, so run scripts from there.

## Opening message

Send this first, in one turn, exactly as written, with no other line before or after it. A request that names its target, such as "audit this" inside a repo, skips it and audits that repo whole.

> I read every line of what you point me at, check it against seven lenses (new-user flow, self-containment, accuracy, one home per idea, unused parts, cost to load and run, voice), verify each finding, and file every one in your backlog.
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
2. **Sweep.** Run `python3 scripts/sweep.py <target>`, `python3 scripts/fleet_check.py --time <target>` and `bash scripts/size.sh <target>`. They find unused code, orphan files, oversized files, budget overruns and voice violations with no model, and their rows are the candidates the next step judges.
3. **Read every line, cheaply.** A scope of 3,000 lines or fewer is read by the lead. A larger scope goes to at most three reader agents on `haiku`, split by area (code, tests, and docs with skills and config), briefed from `references/system.md`. A reader edits nothing. Never start one agent per 3,000 lines or one per file.
4. **Verify.** The lead checks the findings and never starts a second round of agents. Rerun the evidence for every bug, every security claim and everything the report recommends deleting. Check accuracy by running each claimed path, command and count, and check test necessity by removing the guarded code in a scratch copy and watching whether the test fails. A claim that does not reproduce is dropped. Haiku finds and the lead checks.
5. **Report** in the order below, written per `docs/VOICE.md` in the target repo or `~/.claude/VOICE.md`.
6. **File everything.** Bugs, over-engineering, inefficiency, dead code, optimization, stale documentation and voice all get filed, and no finding stays out because it is small. Search the backlog first, then file one epic and one story per boundary, bundling small fixes of one kind into one story. Each story carries its priority, size, the evidence and a command that shows the problem before the fix and its absence after. The repo's `CLAUDE.md` names its backlog. Use `backlog`, or `docs/BACKLOG.md` where the repo has no Project. When an earlier audit already filed stories, map each finding to one and file only what none covers.
7. **Coverage check.** List every finding and every recommendation the report makes, each with the issue that holds it. A finding with no issue gets one now, and the report ends with this list.

Fix nothing during the audit, with these exceptions: a request to fix, which runs the stories in order with deletions first and then the repo's validation, the changes route, which fixes its findings before the commit, and the plan route, which appends its findings to the plan.

## The report

Every audit, on every route, prints these headings in this order, and a heading with nothing to say reads "Checked, nothing found" with what was checked.

1. **What it is.** What the target is meant to be and for whom, in one or two sentences
2. **Goal.** The result this audit aims at, with a size target in lines
3. **Size today.** The `size.sh` table, the verdict on whether it is the right size, the ratios and the `fleet_check.py --time` budget lines. State what loads in every session and what loads on use
4. **Findings.** One table per lens (the seven in `references/lenses.md`, plus test necessity and accuracy) with `file:line`, the evidence, the smallest fix and the issue that holds it
5. **Cuts and simplifications.** A table of every deletion, merge and tool swap: what goes, lines removed, feature kept, issue, and the total against today's size. Estimates are labeled
6. **Outcomes.** What the target is after the fixes, before and after in files, lines, skills and bytes, whether a new user reaches a result by talking, and whether the fixes reach the goal. When they only trim, name the structural move that would reach it
7. **Added to the board.** The epic and every story with number, title, priority, size and status, then the open items that work against the goal for the owner to keep, defer or close
8. **Read and unknown.** What was read, what the lead re-checked and what could not be verified

## Rules

- An audit aims at a smaller, simpler target that keeps its features. Over-engineering, dead code, oversized files and tests that cannot fail weigh as much as bugs. The epic states a size target in lines
- Every finding and recommendation is filed. An owner decision is filed as a story that names what it blocks
- A finding is a defect with evidence. A style preference outside the voice, a hypothetical and a "consider" are not findings
- Owner data in a shipped file is a finding even when no list of names exists: a person's or business's name, an ID, a color, a motif or a niche written as the default
- Count each voice violation by kind, and name the file of every competing writing rule. The `fleet_check.py` voice lines give the file and line of each violation it can find, and its board lines name every difference from `shared/kanban-baseline.json`
