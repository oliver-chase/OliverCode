---
name: automation-first-agent-design
description: "Use when designing or reviewing a cron job, scheduled pipeline, or agent workflow, or when the user asks 'should this be automated', 'can we make this deterministic instead of LLM-based', 'reduce LLM calls in this pipeline', or 'add a fail-closed guard'. Prefers deterministic flows and zero-LLM paths over agent calls; enforces fail-closed behavior on any gate."
---

# Automation-First Agent Design

## Core Principles

1. **Automation first.** Before adding an LLM call, ask: can a deterministic rule handle this?
2. **Fail closed.** When a check fails, deny access / skip action. Silent failures are worse than false positives.
3. **Graceful degradation.** Every LLM call site must have a non-LLM fallback.
4. **Cost transparency.** Every action logs its cost. If it's not logged, it doesn't exist.
5. **One source of truth.** Data flows in one direction. No circular dependencies between stores.

## Design Pattern

```
User Input
  → Intent Router (regex/keyword, zero LLM cost)
    → Data Query (DB/Sheet/file, zero LLM cost)
      → Static Fallback (pre-written response, zero LLM cost)
        → LLM Call (only when above fails, cost tracked)
```

## Flow Design Rules

| Aspect | Rule |
|--------|------|
| Intent routing | Never use LLM. Keyword/pattern matching only. |
| Data queries | Query the store directly, never ask LLM to read data |
| Error handling | Return a helpful message, never crash |
| State transitions | Explicit state machine, not free-form text |
| Logging | Every action logged with timestamp, user, cost |

## Cron Pipeline Design

- **No LLM in cron jobs.** Cron runs deterministic scripts that produce output. The LLM is optional for summarizing that output.
- **Scripts exit 0 on success, non-zero on error.** Exit codes are the health signal.
- **Lock files prevent concurrent runs.** Use `mkdir`-based atomic locks with stale thresholds.
- **Each job has a single responsibility.** Don't have one cron script that both syncs AND drafts AND sends.

---

> Authored 2026-06-12.
