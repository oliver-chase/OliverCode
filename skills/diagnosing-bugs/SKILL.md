---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
---

# Diagnosing bugs

A discipline for hard bugs. Skip a phase only with a stated reason.

## Phase 1 — Build a feedback loop

**This is the skill.** A tight pass/fail signal that goes red on this bug finds the cause, and bisection, hypothesis-testing and instrumentation all consume it. Spend most of the effort here.

Ways to build one, roughly in this order:

1. A failing test at whatever seam reaches the bug (unit, integration, e2e)
2. A curl or HTTP script against a running dev server
3. A CLI call with a fixture input, diffing stdout against a known-good snapshot
4. A headless browser script, a replayed trace, a throwaway harness, a fuzz loop, a `git bisect run` harness or an old-versus-new diff
5. Last resort, a structured script that drives a human through the clicks

Then tighten it: faster (cache setup, narrow the scope), sharper (assert the specific wrong value, so a run that merely finishes cannot pass) and deterministic (pin time, seed RNG, isolate the filesystem, freeze the network). For a non-deterministic bug, raise the reproduction rate by looping the trigger 100 times, adding stress, narrowing timing windows and injecting sleeps. A 50% flake is debuggable and a 1% flake is not.

When no loop can be built, stop and say so, list what you tried, and ask for access to an environment that reproduces it, a captured artifact (HAR, log dump, core dump, timestamped recording) or permission to add temporary production instrumentation. Do not hypothesise without a loop.

Phase 1 is done when you can name one command that you have already run, that drives the real code path, asserts the user's exact symptom, gives the same verdict every run, finishes in seconds and runs unattended. If you catch yourself building a theory from the code before that command exists, stop.

## Phase 2 — Reproduce and minimise

Run the loop and watch it go red with the symptom the user described, across several runs. Capture the exact symptom so later phases can verify the fix. Then shrink the repro to the smallest scenario that still goes red, cutting inputs, callers, config, data and steps one at a time.

## Phase 3 — Hypothesise

If the code path is correct, check the data source (file, Sheet, API, mailbox) next. Write 3 to 5 ranked, falsifiable hypotheses before testing any: "If X is the cause, changing Y makes the bug disappear." Show the ranked list, and proceed with your ranking if the user is away.

## Phase 4 — Instrument

Each probe maps to one prediction from Phase 3, and you change one variable at a time. Prefer a debugger or REPL, then targeted logs at the boundaries that tell the hypotheses apart. Never log everything and grep. Tag every debug log with a unique prefix such as `[DEBUG-a4f2]`, so cleanup is one grep. For a performance regression, take a baseline measurement first, then bisect.

## Phase 5 — Fix and regression test

Write the regression test before the fix, at a seam where the test exercises the real bug pattern as it occurs at the call site. If no such seam exists, that is the finding: the architecture prevents locking the bug down. With a seam: turn the minimised repro into a failing test, watch it fail, apply the fix, watch it pass, then re-run the Phase 1 loop on the original scenario.

## Phase 6 — Cleanup and post-mortem

Before declaring done: the original repro no longer reproduces, the regression test passes (or the missing seam is documented), all `[DEBUG-...]` instrumentation and throwaway prototypes are gone, and the commit message states the hypothesis that proved correct. Then ask what would have prevented this bug, and make any architectural recommendation after the fix is in.
