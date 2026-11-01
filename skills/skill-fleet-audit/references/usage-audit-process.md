# Same-Session Usage Dimension — Process

This mode needs the real tool-call sequence of a task under review. That sequence exists only in the conversation that ran the task. It is the one dimension of this skill that cannot run as a static, cron-friendly script. Run it in that same session, or immediately after in a continuation of it.

An already-ended session is out of scope. Nothing in this harness recovers a past session's tool-call history. If the user asks to audit a session that already ended, say so plainly. Then ask them to paste the relevant excerpts or describe what happened. Do not guess at a sequence you cannot see.

## Steps

**1 — Reconstruct the real sequence.** List, in order, every tool and MCP call the task under review actually made. Use the portion of the conversation the user points at, or the whole task if they don't narrow it.

**2 — Run the efficiency checklist against that sequence:**

- A duplicate or overlapping call — the same search run twice, or two calls that returned the same result.
- The wrong tool for the job — a fuzzy search used where a direct, known-path lookup would have worked.
- An unbounded read where a targeted one would have answered the question.
- A retry or pivot loop with no clear stopping rule.
- A call whose result was never used anywhere after.
- A mid-task strategy flip — starting a second, more expensive approach while the first was still plausibly working.

**3 — Audit the skill definition itself against what the task actually needed:**

- A procedure the task needed that the skill's file never covered.
- A convention the agent had to reverse-engineer live because the skill never wrote it down.
- An instruction that proved wrong or too broad once checked against the real data.
- A small piece of tooling that would have replaced a repeated manual step.
- A tool or script that failed with a raw, unhelpful error instead of a clear, actionable message.

**4 — Check every finding live before writing it down.** Never assert a gap without checking it. If a finding claims a file is missing, list the directory. If a finding claims a tool call had no effect, check that against the actual call and its result. Do not check it against memory of what should have happened. A finding that skips this step is a guess, not a finding. Do not write down a guess.

**5 — File each finding** in the GitHub Project that the repo's backlog config names, cheapest and highest-risk first. Run `backlog-management` to file it.

**6 — Flag, never auto-resolve, a finding that needs a real external or shared-system change** — a shared folder restructure, a cross-team process change. Name it as an open question for the user, with what it blocks, instead of deciding it.
