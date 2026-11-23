---
name: audit
description: "The one audit for anything: a whole repo or suite, a skill or skill family, the docs, a commit range before it closes, or a plan before it runs. Reads every line, verifies each finding against the code, files every fix with a priority, and on a whole repo stops at the report and the filed issues, and fixes them all too when asked for audit and fix. Trigger on 'audit this', 'QA this', 'review tonight's work', 'are the docs accurate', 'audit my skills', 'audit my Claude config', 'is this over-engineered', 'is this shareable' or 'pressure test this plan'."
---

# Audit

An audit tells the owner what a target is meant to be, what it is today and what to change, with every claim checked against the files. Every route runs the same procedure and writes the same report, and a whole repo then stops at the report and the filed issues, and goes on to done (`references/done.md`) only on "audit and fix". Script paths are relative to this skill's folder. It runs alone; only the board check needs the backlog skill beside it.

## Opening message

Send this first, in one turn, exactly as written, with no other line. A request that names its target (a repo, skill, skills or docs folder, commit range or plan file) skips it and audits that target.

> I read every line of what you point me at, check it against ten lenses (autonomy and user flow, self-containment, accuracy, one home per concept, over-engineering and unused parts, cost in use, voice, documentation coverage, functionality gaps, portability and sharing), verify each finding, and file every one in your backlog with a priority. On a whole repo I stop there, and you run the backlog yourself. Say "audit and fix" and I fix them too.
>
> You can answer in any of these ways:
> 1. Say "audit this" inside a repo, and I will audit the whole repo.
> 2. Name a skill, a family of skills or a folder of docs, and I will audit that.
> 3. Ask me to review the work this session just did, and I will audit its commits before they close.
> 4. Give me a plan file, and I will test its claims before anyone runs it.

## Routes

Load the file of the route the request names. A request that fits two routes runs the wider one.

| The request names | Route | Load |
|---|---|---|
| A repo, a suite, a system, or nothing ("audit this") | Whole target; to done only on "audit and fix" | `references/system.md`, `references/done.md` |
| A skill, a skill family or a skills folder | Skills | `references/skills.md` |
| The Claude config (`~/.claude`) | Skills, then Docs | `references/skills.md`, `references/docs.md` |
| The docs, a README, or "are these accurate" | Docs | `references/docs.md` |
| This session's work, a commit range, "QA this" | Changes | `references/changes.md` |
| A plan file, or a plan about to run | Plan | `references/plan.md` |

Every route loads `references/lenses.md`. A target with a user interface also loads `references/frontend-ux.md`.

## The procedure

1. **Scope.** Run `python3 scripts/audit_ledger.py <target> --pending`. It lists the files no earlier audit read, or that changed since, with a line total, and says so when there is no ledger yet. That list is the read contract and the report names it. Audit everything only for a first audit or when the owner asks.
2. **Sweep.** Run `python3 scripts/sweep.py <target>`, `python3 scripts/fleet_check.py --time <target>`. They find unused code, orphan files, oversized files, failing tests and voice violations with no model, and their rows are candidates to judge.
3. **Read every line, inside a time box.** Run `python3 scripts/load_guard.py` first: it prints how many readers to start and whether mutation checks may run, and it exits 2 to wait when the machine is overloaded. The audit session reads a scope of 3,000 lines or fewer with no agents, and a repo that size finishes in ten minutes. A larger scope goes to `sonnet` readers, one per facet (each skill, each part of the tool, the tests, the docs), with facets batched to about 3,000 lines and at most 12 readers, briefed from `references/system.md`. A reader only reads: no edits, no tests, no mutations, and it stops after 15 minutes.
4. **Verify.** The audit session checks the findings and never starts a second round of agents. Rerun the evidence for every bug, security claim and recommended deletion. Check accuracy by running each claimed path, command and count. Only the audit session runs tests or mutations: one at a time, on the single test file that guards the code, at most 10 per audit, and only while `load_guard.py` prints `mutations: yes`. Check test necessity by removing the guarded code in a scratch copy and watching whether that test fails. A claim that does not reproduce is dropped.
5. **Report** in the order below, written per `docs/VOICE.md` in the target repo or `~/.claude/VOICE.md`. On a whole repo, print the full report in the thread (what it is, size, findings, over-engineering, cuts, simplifications and the engine parts to cut or merge) before step 6 files or fixes anything
6. **File everything.** Every finding gets filed, however small. Search the backlog first, then file one epic and one story per boundary, bundling small fixes of one kind into one story. Each story carries its priority (below), size, the evidence and a command that shows the problem before the fix and its absence after. The repo's `CLAUDE.md` names its backlog. Use `backlog`, or `docs/BACKLOG.md` where the repo has no Project. When an earlier audit already filed stories, map each finding to one and file only what none covers.
7. **Coverage check.** After the audit run `audit_ledger.py <target> --mark FILE --findings N` with the files actually read and the finding count, which adds a dated run line, and commit `docs/AUDITED.txt`. List every finding and every recommendation the report makes, each with the issue that holds it. A finding with no issue gets one now, and the report ends with this list as its ninth section, headed "Coverage", followed by the tenth, "Engine parts to cut or merge". Then deliver the report once, as one formatted message in the thread and never as a file or a file copy: pipe it to `python3 scripts/check_report.py -` on stdin, fix every line it prints and run it again, and print the message only when it prints `report: complete.`

## A chunked audit

An audit split across sessions stays one audit, run through `python3 scripts/findings.py` on one ledger, `<target>/docs/AUDIT-FINDINGS.json`.

- **One coordinator.** The session that starts the audit runs `findings.py LEDGER start --target T --coordinator <its session> --chunks a,b,c` and owns it to the final report. It alone runs `cross`, `file` and `report`, and it is the only session that files issues
- **One ledger and one scale.** Each chunk session records every finding with `findings.py LEDGER add --chunk C` in the one schema (lens, priority, `file:line`, defect, evidence, fix and, when a rule is broken, `--rule`), then runs `done --chunk C`. Ids run F1, F2 across all chunks and every priority is P0, P1 or P2
- **A cross-cutting pass.** Once every chunk is done, the coordinator runs `cross`. It merges duplicates across chunks, keeps the higher priority, joins one rule broken in several chunks into one finding and lists each rule seen in one chunk for the coordinator to check in the others
- **One report.** The coordinator files each finding with `file --id F3 --issue N`, then `report` prints one Findings table in one priority order for step 5

## Priorities

- **P0.** Data loss or a leak, a safety gate that can be bypassed, or a first use that fails
- **P1.** A wrong result, a broken command, a wrong or missing document for a shipped part, or waste of 10% or more in size, tokens or time
- **P2.** Everything else. It is filed and fixed last, and never dropped

Fix nothing during the audit itself. The exceptions: the whole-target route's to-done phase, which runs the stories in order (`references/done.md`), the changes route, which fixes its findings before the commit, and the plan route, which appends its findings to the plan. The audit stops at the report and the filed issues unless the owner says "audit and fix" or sets `auditMode` to full. A request to report only skips the to-done phase. Once the report and every issue are filed, `python3 scripts/audit_mode.py next` (add `--fix` for "audit and fix") says whether the to-done phase starts (`references/done.md`).

## The report

Every audit prints these headings in this order, which `check_report.py` enforces. A heading with nothing to say reads "Checked, nothing found" with what was checked.

1. **What it is.** What the target is meant to be and for whom, in one or two sentences, and its sharing verdict (portable, portable after fixes, or personal) with the reason
2. **Goal.** The result this audit aims at, with a size target in lines
3. **Size today.** The per-folder file and line counts from `references/system.md`, the verdict on whether it is the right size and the `fleet_check.py --time` test runtime. State what loads in every session and what loads on use
4. **Findings.** One table per lens (the ten in `references/lenses.md`, plus test necessity) with `file:line`, the evidence, the smallest fix and the issue that holds it
5. **Cuts and simplifications.** A table of every deletion, merge and tool swap: what goes, lines removed, feature kept, issue, and the total against today's size. Estimates are labeled
6. **Outcomes.** What the target is after the fixes, before and after in files, lines, skills and bytes, whether a new user reaches a result by talking, and whether the fixes reach the goal. When they only trim, name the structural move that would reach it
7. **Added to the board.** The epic and every story with number, title, priority, size, status and a Why column holding the finding in one sentence, then the open items that work against the goal for the owner to keep, defer or close
8. **Read and unknown.** What was read, what the ledger skipped, what the audit session re-checked and what could not be verified
9. **Coverage.** Each finding with the issue that holds it
10. **Engine parts to cut or merge.** The parts of the engine to cut or merge, each with the issue that holds it

## Rules

- An audit aims at a smaller, simpler target that keeps its features, and weighs over-engineering, dead code, oversized files and tests that cannot fail as heavily as bugs. The epic writes its size target as `Size target: at most N lines`
- Every finding and recommendation is filed. An owner decision is filed as a story that names what it blocks
- A finding is a defect with evidence. A style preference outside the voice, a hypothetical and a "consider" are not findings
- A layout or design fix is judged by whether the composition holds up to realistic longer content, not only the sample shown: uniform margins, deliberate element placement and real slack for longer text
- An example or source file (a template, fixture, deck-copy example or transcript) may break a content rule on purpose, so it is never filed as a defect. Text a build copies into a finished document as written is output and keeps its rules
- Owner data in a shipped file is a finding even when no list of names exists: a person's or business's name, an ID, a color, a motif or a niche written as the default
- Count each voice violation by kind and name the file of every competing writing rule. `fleet_check.py` prints each violation it finds and every board difference from `shared/kanban-baseline.json`
