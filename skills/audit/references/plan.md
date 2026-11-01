# Plan

A plan file, tested before anyone runs it. A plan states claims, and some of them are guesses that read as facts because they are written down. This route tells the two apart by running each check.

1. Read the whole plan: every step, risk, goal and the definition of done
2. List every checkable claim, meaning anything that names something real: a file, a function's behavior, a tool's default, a link, a cross-reference or a count. A judgment call is not checkable, so skip it
3. Check each one live:
   - A file or link: list it
   - A behavior: read the source, or run a case that proves or disproves it
   - A reuse ("this extends X"): read X and confirm it does what the new use needs
   - An absence ("nothing else uses this"): grep for it
   - A downstream effect ("removing this breaks nothing"): find what depends on it
4. Record every check. A claim that holds gets one line. A claim that fails says what the plan said, what is true, and what the plan needs instead
5. Append a dated "Pressure-test findings" section to the plan, just before its definition of done, and leave the step text as written
6. Hand the findings to the plan's owner, who decides how to fix the plan and whether a finding blocks it
