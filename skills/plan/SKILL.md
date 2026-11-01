---
name: plan
description: "Use when the user says 'make a plan', 'write this up as a plan first', or 'don't start coding yet, just plan'. Writes a structured plan (Goal/Steps/Risks/Definition-of-Done) as a markdown file to <repo>/docs/plans/. Does not execute. Distinct from Claude Code's built-in ephemeral Plan Mode, which writes no file."
---

# Plan — Markdown Planning Protocol

## Process

1. Understand what's being asked
2. Decompose into sequential steps
3. For each step: what, why, expected outcome, risk level
4. Write to file (markdown), NOT executed

## Claims Discipline

A plan is a set of assertions about live state — "this file exists," "this skill has no
probe," "3 of 8 items already do X." Every assertion of that shape names a set of N items.
Before a sentence claims a check across N named items, read all N. A sample, "most of them"
or one case generalized to the rest is not a check. A `find`/`grep` listing that only names
the items is not a check of them either.

This applies whether N is 3 or 30. A larger N is a reason to batch the reads efficiently, not
a reason to sample. When reading all N costs too much before drafting, the plan says so:
"checked 3 of 8, the rest assumed from their names". The `audit` skill's plan check then
tests the rest. That check is the safety net for a wrong inference from real evidence.

## Plan File Location

Repo: `<repo>/docs/plans/`. Some work spans the vault or multiple product repos, not one repo. There is currently no dedicated vault-level plans directory for that case. Write the plan into whichever single repo the work centers on. If the work is genuinely cross-repo, ask the user where they want it instead.

## Plan Headers

Every plan file needs:

```markdown
# Plan: <Title>
Date: YYYY-MM-DD
Related: <links to relevant docs, issues, or prior plans>

## Goal
What we're trying to accomplish.

## Steps
1. <step> — <why>
2. <step> — <why>

## Risks
- <risk> → <mitigation>

## Definition of Done
- [ ] Condition 1
- [ ] Condition 2
```

## Execution Protocol

1. Write plan → present to user
2. User approves → execute step by step
3. Mark steps done as completed
4. If a step reveals new info, append a finding, don't rewrite the plan
