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

## Plan File Location

Repo: `<repo>/docs/plans/`. For work that isn't scoped to one repo (spans the vault or multiple product repos), there is currently no dedicated vault-level plans directory — write the plan into whichever single repo the work is centered on, or ask the user where they want it if the work is genuinely cross-repo.

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
