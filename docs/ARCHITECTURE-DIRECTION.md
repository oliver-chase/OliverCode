# OliverCode architecture direction

This document records the product and engineering direction for the November 23 simplicity recovery. It is a decision guide for implementation and review—not a specification to reproduce one historical snapshot exactly.

Related work:
- [#1246 — Investigate and restore delivery throughput](https://github.com/oliver-chase/OliverCode/issues/1246)
- [#1265 — Remove redundant tests, validation gates, and duplicated safeguards](https://github.com/oliver-chase/OliverCode/issues/1265)
- [#1267 — Review independent reader and owner visibility](https://github.com/oliver-chase/OliverCode/issues/1267)

## Product goal

OliverCode is an autonomous operator with a small owner interface, not a minimalist task runner. The owner should be able to describe an outcome and let OliverCode take responsibility for moving the work forward. The owner should not have to orchestrate commands, agents, retries, validation stages, or handoffs.

The target is **simpler internal execution with better owner-facing visibility**.

## The Nov 23 reference

Use November 23, 2026 as a reference for execution discipline, low overhead, and straightforward validation—not as a blind rollback target. Later work may have added valuable autonomy, reliability, recovery, or reporting. Preserve those capabilities when they have demonstrated operational value.

Do not assume that a later feature is waste simply because it adds code, or that an earlier implementation is better merely because it is smaller. Evaluate the behavior it provides and its incremental cost.

## Operating principles

### 1. Reduce overhead, not capability

Prefer fewer model calls, tokens, handoffs, retries, repeated context loads, subprocesses, and duplicate validation runs. Avoid extra layers that merely coordinate or re-check work already reliably covered elsewhere.

A mechanism should earn its cost by protecting a distinct important behavior or improving a real owner/operator decision.

### 2. Preserve autonomous delivery

Keep capabilities that materially support:
- Autonomous progression from a requested outcome to completed work.
- Useful isolated parallel execution.
- Deterministic landing and lifecycle cleanup.
- Recovery from genuinely interrupted operations.
- Clear owner decision boundaries and safe escalation.

Do not reduce OliverCode to a passive task queue or require the owner to supervise every implementation step.

### 3. Keep validation intentional

- Keep the smallest set of gates that protects distinct, important behavioral contracts.
- Merge overlapping tests into existing relevant suites; do not multiply test modules or create meta-tests to validate simplification.
- Remove checks that duplicate another gate, enforce incidental implementation details, or protect no meaningful behavior.
- Reuse a passing validation result only when it applies to the exact same tree and gate semantics; never reuse stale or partial results.
- Preserve correctness, data integrity, safe landing, and recovery.
- Do not optimize for test count, coverage percentage, or the appearance of more gates.

For every retained gate, be able to state what unique behavior it protects and when it runs.

### 4. Keep independent review useful and bounded

The reader is not automatically better because it is more elaborate, nor is the Nov 23 one-turn/no-tools reader automatically better because it is cheaper.

The desired reader is a fresh, independent reviewer with the minimum capability needed to make a meaningful assessment:
- Bound turns, tools, context, retries, and output.
- Allow focused, read-only inspection when the diff alone cannot verify a dependency or claim.
- Avoid open-ended search/review loops and repeated investigation already performed by the builder or tests.
- Report concise, actionable findings tied to files and behavior.
- Distinguish a verified pass from uncertainty or behavior it could not inspect.

Choose the reader design based on demonstrated defect detection and incremental model/tool cost. Do not remove useful inspection capability solely to reduce a turn or tool count. Do not retain multi-step machinery without evidence that it catches important problems.

### 5. Make owner visibility better, not noisier

The owner should be able to understand the state of work without reading raw logs or manually managing the workflow. Reporting should answer:
- What is OliverCode working on now?
- What has it completed, and what is it doing next?
- Is it progressing, blocked, or waiting for an owner decision?
- What failed, what recovery was attempted, and what remains unresolved?
- What verification actually ran and passed?
- What relevant usage or cost information is available?

Keep reporting concise, truthful, timely, and inexpensive. Prefer deriving it from existing lifecycle events and records. Do not create duplicate status, telemetry, or concurrency systems, and do not instrument activity that has no concrete operational or owner decision attached to it.

### 6. Measure outcomes, not machinery

Evaluate changes using completed work, time to completion, spend, rework, reliability, recovery, and owner intervention where measurable.

Do not treat commit counts as story completions, test counts as quality, coverage percentages as product value, or dashboard detail as visibility by itself.

## Decision test for proposed changes

Classify each meaningful mechanism as:

- **Keep** — it protects a distinct important behavior or materially improves autonomy, recovery, safety, or owner control.
- **Merge** — its behavior is useful but duplicates another mechanism or test location.
- **Simplify** — its purpose is useful but its implementation, runtime, or model cost is disproportionate.
- **Delete** — it has no unique behavioral or owner-facing value, or duplicates a cheaper reliable mechanism.

Record the behavior protected, the evidence of value, the incremental cost, and the verification result. When two mechanisms protect the same behavior, prefer the cheaper and clearer one.

## Non-goals

This direction does not call for:
- A blanket rollback to November 23.
- Removing useful autonomy, parallelism, recovery, or owner visibility to reduce line count.
- An open-ended reviewer or another agent for every small task.
- New generic validation frameworks, test registries, meta-tests, or duplicate telemetry systems.
- Preserving every test or gate simply because it already exists.
- Hiding failures or weakening important correctness and safety contracts to make validation appear faster.

**Guiding principle: simplify the machinery, not the product.**
