---
name: plan-pressure-test
description: "Adversarially checks a plan doc (written by the plan skill) against live system state before it gets executed. Re-derives every checkable claim, such as file existence, cross-references, and whether reused infrastructure fits the new use, instead of trusting the write-up. Trigger on 'pressure test this plan' or 'check this plan before we run it'. Also trigger when a plan doc from the plan skill is about to run."
---

# Plan Pressure Test

A plan doc states claims. Some are true. Some are guesses that read as confident because they are written down. This skill tells the two apart before execution starts, by running the check, not by re-reading the prose. The `plan` skill writes a doc and stops. This skill is the gate between "plan written" and "plan approved".

## Opening message

Send this first, in one turn, exactly as written, with no other opening line and no closing recap. A request that names its plan file skips the message.

> A false claim in a plan costs far more to fix once the plan is running.
>
> Before anyone executes the plan, I test each of its claims against the live files and tools. I check whether a file exists, what a script does, and whether reused machinery fits the new use. I log what holds and what fails, then append the findings to the plan. You decide how to fix the plan and whether a finding blocks it.
>
> Any detail on the repo's current state helps, and a rough plan is fine.
>
> You can answer in any of these ways:
> 1. Send the path to the plan file, usually a markdown file in `<repo>/docs/plans/`.
> 2. Paste the plan text here, and I will check it and show the findings in the thread.
> 3. Give the plan's name and the repo it targets, and I will find the file.

## Process

1. **Read the whole plan.** Every Step, every Risk, the Goal and the Definition of Done.

2. **Extract every checkable claim.** A claim is checkable when it names something real. Examples are a file path, a function's behavior, a tool's default argument, a symlink, a cross-reference and a count. "This needs the user's judgment" is not checkable. Skip it.

3. **Check each one live, never from memory:**
   - A claimed file or symlink: list the directory.
   - A claimed function or script behavior: read the source, or run a case that proves or disproves it.
   - A claimed reuse ("this extends the existing X mechanism"): read X's implementation. Check that it does what the new use needs, not only that it exists under a plausible name.
   - A claimed absence ("no other skill references this"): grep for it.
   - A downstream effect ("removing this breaks nothing"): search for what depends on the thing the plan changes.

4. **Log every check, not only the failures.** A claim that holds is a checked-good finding, one line. A claim that does not hold is a correction. State what the plan said, what is true, and what the plan needs to do differently.

5. **Append a "Pressure-Test Findings" section to the plan file,** dated, right before its Definition of Done. Do not rewrite the plan's step text. If a finding changes what a step does, say so in the findings section.

6. **Never invent a finding to look thorough.** A step with nothing wrong gets a one-line confirmation.

7. **Hand off.** This skill checks. It does not fix, and it does not decide whether a finding blocks execution. That call belongs to the plan owner.
