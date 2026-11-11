---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
---

# Diagnosing bugs

A discipline for hard bugs. Skip phases only when explicitly justified.

## Phase 1 — Build a feedback loop

**This is the skill.** A **tight** pass/fail signal that goes red on _this_ bug finds the cause, and bisection, hypothesis-testing and instrumentation all consume it. Without one, staring at code will not save you.

Spend most of the effort here.

### Ways to construct one — try them in roughly this order

1. **Failing test** at whatever seam reaches the bug — unit, integration, e2e
2. **Curl / HTTP script** against a running dev server
3. **CLI invocation** with a fixture input, diffing stdout against a known-good snapshot
4. Other loops: a headless browser script, a replayed captured trace, a throwaway harness, a fuzz loop, a `git bisect run` harness, or an old-versus-new diff
5. **Human-in-the-loop script.** Last resort. If a human must click, drive _them_ with a structured script so the loop is still structured

### Tighten the loop

Once you have _a_ loop, **tighten** it:

- Can I make it faster? (Cache setup, skip unrelated init, narrow the test scope.)
- Can I make the signal sharper? (Assert on the specific symptom, such as the wrong value, so a run that merely finishes cannot pass.)
- Can I make it more deterministic? (Pin time, seed RNG, isolate filesystem, freeze network.)

### Non-deterministic bugs

Raise the **reproduction rate**: loop the trigger 100×, parallelise, add stress, narrow timing windows, inject sleeps. A 50% flake is debuggable and a 1% flake is not.

### When you genuinely cannot build a loop

Stop and say so explicitly. List what you tried. Ask the user for: (a) access to whatever environment reproduces it, (b) a captured artifact (HAR file, log dump, core dump, screen recording with timestamps), or (c) permission to add temporary production instrumentation. Do **not** proceed to hypothesise without a loop.

### Completion criterion — a tight loop that goes red

Phase 1 is done when the loop is **tight** and **red-capable**: you can name **one command** that you have **already run at least once**, and that is:

- [ ] **Red-capable** — it drives the actual bug code path and asserts the **user's exact symptom**, so it can go red on this bug and green once fixed
- [ ] **Deterministic** — same verdict every run
- [ ] **Fast** — it finishes in seconds
- [ ] **Agent-runnable** — you can run it unattended

If you catch yourself reading code to build a theory before this command exists, **stop.** No red-capable command, no Phase 2.

## Phase 2 — Reproduce + minimise

Run the loop. Watch it go red.

Confirm:

- [ ] The loop produces the failure mode the **user** described, the same symptom at the same place
- [ ] The failure is reproducible across multiple runs
- [ ] You have captured the exact symptom so later phases can verify the fix

### Minimise

Once it's red, shrink the repro to the **smallest scenario that still goes red**. Cut inputs, callers, config, data, and steps **one at a time** — keep only what the failure needs.

## Phase 3 — Hypothesise

Check the obvious shortcut first: if Phase 1/2 shows the code path is correct, the data source (file, Sheet, API, mailbox) is wrong, so fix the data.

Generate **3–5 ranked hypotheses** before testing any of them.

Each hypothesis must be **falsifiable**:

> "If <X> is the cause, then <changing Y> will make the bug disappear / <changing Z> will make it worse."

Show the ranked list before testing. Proceed with your ranking if the user is away.

## Phase 4 — Instrument

Each probe must map to a specific prediction from Phase 3. **Change one variable at a time.**

Tool preference:

1. **Debugger / REPL inspection** if the env supports it
2. **Targeted logs** at the boundaries that distinguish hypotheses
3. Never "log everything and grep"

**Tag every debug log** with a unique prefix, e.g. `[DEBUG-a4f2]`. Cleanup at the end becomes a single grep.

**Perf branch.** For performance regressions: establish a baseline measurement first, then bisect.

## Phase 5 — Fix + regression test

Write the regression test **before the fix** — but only if there is a **correct seam** for it.

A correct seam is one where the test exercises the **real bug pattern** as it occurs at the call site. **If none exists, that is the finding:** note that the architecture prevents locking the bug down.

If a correct seam exists:

1. Turn the minimised repro into a failing test at that seam
2. Watch it fail
3. Apply the fix
4. Watch it pass
5. Re-run the Phase 1 feedback loop against the original scenario

## Phase 6 — Cleanup + post-mortem

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop)
- [ ] Regression test passes (or absence of seam is documented)
- [ ] All `[DEBUG-...]` instrumentation removed
- [ ] Throwaway prototypes deleted
- [ ] The hypothesis that turned out correct is stated in the commit message

**Then ask: what would have prevented this bug?** If the answer involves architectural change, make the recommendation after the fix is in — you have more information now than when you started.
