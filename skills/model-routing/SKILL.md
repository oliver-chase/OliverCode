---
name: model-routing
description: Use when deciding which LLM tier to call for a step (cheap model for classification/validation vs. capable model for generation), when the user asks 'which model should this use' or 'can we use a cheaper model here', or when configuring LLM_PROVIDER_ORDER. Pattern contract, not implementation.
---

# Model Routing Strategy

## Purpose

Define a consistent model routing pattern across all workflows. The same model should not be used for every task — route by task complexity to control cost and latency.

## Routing Tiers

| Tier | Task examples | Model requirement | Cost target |
|------|--------------|-------------------|-------------|
| **Classification** | Prospect eligibility, reply intent, approval status, error classification | Minimum capable — fast, cheap | Lowest available |
| **Validation** | Output quality check, contract compliance, format verification | Minimum capable — deterministic checks preferred | Zero (use regex/schema first) |
| **Generation** | Draft email content, content creation, metrics summary | Capable — quality matters | Highest budget per call |
| **Routing** | Command dispatch, argument parsing, config resolution | Zero — must be deterministic | No model needed |

## Implementation Pattern

```
1. Classify the task tier (classification / validation / generation / routing)
2. If routing or validation-checkable via regex: no LLM call
3. If classification: use the cheapest model in LLM_PROVIDER_ORDER
4. If generation: use the most capable model in LLM_PROVIDER_ORDER
5. Never default to generation model for classification tasks
```

## Configuration

- `LLM_PROVIDER_ORDER` — ordered list of fallbacks, cheapest to most capable per tier
- Instance-specific model names are NOT defined here — they are instance config
- This skill defines the pattern only

## Related Skills

This skill defines the pattern only — it doesn't track which consumers implement it.

## Non-Goals

- This skill does NOT specify which models to use
- This skill does NOT replace env var config for API keys
- This skill does NOT implement retry or fallback logic (that belongs in the LLM client)
