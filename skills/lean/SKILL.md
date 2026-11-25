---
name: lean
description: "Keeps engineering work deliberately small without cutting correctness. Use on coding, debugging, refactoring, architecture, dependency choices, or when work feels over-engineered. Also supports review, repository audit, deferred-shortcut inventory, and measured impact. Trigger on 'lean', 'smallest sufficient change', 'YAGNI', 'simplify this', 'review this diff', 'what can we delete', or 'measure the gain'."
argument-hint: "[lite|full|ultra|off|review|audit|debt|gain]"
---

# Lean engineering

OliverCode's default engineering method. Inspired by the ideas in [Ponytail](https://github.com/DietrichGebert/ponytail), adapted for OliverCode's interactive-first Claude Code harness. This is an independent implementation, not a vendored copy.

The goal is the smallest complete change that solves the actual problem. Minimize code, moving parts, dependencies, model calls, context, handoffs and validation time **without minimizing correctness or the requested outcome**.

## Modes

- **full (default):** Apply the rules below. If the user says `/lean` with no argument, report that full mode is active.
- **lite:** Build what was asked, but state one materially simpler option if one exists. Do not silently expand scope.
- **ultra:** Challenge whether each requested part needs to exist before implementing it. Offer a smaller complete alternative when it materially improves the result; still implement the agreed outcome.
- **off:** Suspend the extra simplification preference for this task only. Safety, security, correctness, data integrity and explicit user requirements remain mandatory.
- A mode change applies to the current conversation unless the user explicitly asks to make it a standing default. Do not create a new config file or persistent state for a temporary mode.

## Before changing anything

1. Read the task, relevant code and the repo's existing conventions.
2. Trace callers and downstream effects before changing a shared function, interface, schema, command or file format.
3. Ask: **does this need to exist?** Prefer deleting the cause, using an existing capability, or not adding anything.
4. Choose the first complete option in this order:
   - Existing code, helper, component or workflow.
   - Standard library or native platform capability.
   - Dependency already installed in the project.
   - Smallest new implementation that fully works.
5. State assumptions and exclusions only when they affect the outcome. Do not turn simple tasks into a design ceremony.

## Implementation rules

- Deletion and reuse beat addition when behavior remains correct.
- Do not add abstractions, wrappers, configuration, dependencies, compatibility layers or future-proofing without a demonstrated need.
- Follow the repository's existing architecture; do not create a parallel framework to avoid a small edit.
- Keep data in the native form already used by the platform.
- Complete the whole change: callers, tests, fixtures, docs, exports, cleanup and migration where applicable.
- Fix shared root causes once, rather than patching each caller.
- Comments explain why, not what. Keep them short.
- For a deliberate shortcut with a known limit, add `shortcut: <limit>, <condition for upgrading>` beside the code.
- Prefer one readable line over a helper only when the line remains obvious.

## Never trade away

Trust-boundary validation, authentication and authorization, security, privacy, error handling that prevents data loss, concurrency correctness, recovery, accessibility, required tests, or anything the user explicitly requested.

A branch, loop, parser, money calculation, security-sensitive change, state transition or new executable component gets at least one focused test or assert-based self-check. A trivial text-only change does not need a test just to satisfy a ritual.

Validation is proportional to risk:
- Docs and low-risk edits: deterministic checks and relevant focused tests.
- Ordinary code: focused tests plus relevant static checks.
- Claims, locks, dispatch, concurrency, persistence, security, migrations and data-loss paths: focused tests plus targeted integration coverage.
- Full suite: broad changes, release, or scheduled assurance—not automatically every small edit.
- Always distinguish passed, failed, skipped and not-run. Never claim a skipped check passed.

## Keep the interaction human

- Interactive Claude Code conversations are first-class. Strategy, exploration, planning, debugging and ordinary coding stay interactive.
- Do not turn a normal chat into a backlog issue, headless run, manager stage or reviewer stage by default.
- Use OliverCode's backlog and headless runner when the owner explicitly delegates work, asks for a durable tracked item, or the work genuinely benefits from unattended execution.
- Do not add a model call where deterministic code, an existing status file, a focused read or a simple script is sufficient.
- Use independent reviewers, decomposition, retries and model escalation only when risk or evidence warrants them.

## Finish every task

Before reporting completion:
- Read the diff and remove accidental complexity introduced by the change.
- Check for dead code, duplicate logic and stale documentation.
- Report the result, tests/checks actually run, checks skipped or unavailable, and remaining risks in a few plain lines.
- Do not report token savings, speedups or safety as measured unless there is a reproducible before/after measurement.

## Commands

Use `/lean lite|full|ultra|off` to change the current task's mode.

Use `/lean review [uncommitted|staged|branch|PR]` to review a change. Read the full relevant diff and surrounding code; report only actionable findings, ordered by severity, with evidence, consequence, smallest safe fix and missing tests. Reuse the `audit` skill's Changes route for a formal review.

Use `/lean audit [target]` for a repository or subsystem audit. Reuse the `audit` skill and its ledger; include over-engineering, duplicate mechanisms, unused code and complexity in the findings. Never invent findings to fill a quota.

Use `/lean debt [word]` to inventory deferred shortcuts. Search tracked source for `shortcut:` (or the supplied marker), group by file and subsystem, and report the limit, upgrade condition and whether it is still relevant. Do not automatically create an issue for every marker; file only actionable debt that has an owner-visible consequence.

Use `/lean gain [baseline]` to compare measured outcomes. Use existing run logs, validation timings and transcript telemetry where available. Report lines changed, added/deleted code, model calls, input/output/cache tokens, cost, elapsed time, validation time, retries, landed outcomes and escaped defects where measurable. Separate interactive and headless workloads. If no comparable baseline exists, say so and propose the smallest measurement; never fabricate a gain.

## Source and attribution

This method is inspired by the MIT-licensed [Ponytail project](https://github.com/DietrichGebert/ponytail). OliverCode uses its own wording, modes and workflows and does not copy its implementation or claim its benchmark results.
