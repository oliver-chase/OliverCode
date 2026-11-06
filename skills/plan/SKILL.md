---
name: plan
description: "Use when the user says 'make a plan', 'write this up as a plan first', or 'don't start coding yet, just plan'. Writes a structured plan (Goal/Steps/Risks/Definition-of-Done) as a dated markdown file, <repo>/docs/plans/YYYY-MM-DD-<slug>.md. Does not execute. Distinct from Claude Code's built-in ephemeral Plan Mode, which writes no file."
---

# Plan — Markdown planning protocol

## Process

1. Understand what's being asked
2. Decompose into sequential steps
3. For each step: what, why, expected outcome, risk level
4. Write to file (markdown), NOT executed

## Claims discipline

A plan asserts live state, such as "this file exists" or "3 of 8 items already do X". Before a sentence claims something across N named items, read all N, whether N is 3 or 30. When that costs too much before drafting, the plan says so, as in "checked 3 of 8, the rest assumed from their names", and the `audit` skill's plan route tests the rest.

## Plan file location

Write the plan to `<repo>/docs/plans/YYYY-MM-DD-<slug>.md`, dated the day it is written, in the repo the work centers on. When the work spans several repos, ask the user which repo holds it.

## Plan headers

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

## Execution protocol

1. Write plan → present to user
2. User approves → execute step by step
3. Mark steps done as completed
4. If a step reveals new info, append a finding, don't rewrite the plan
