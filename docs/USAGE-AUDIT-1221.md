# Claude usage audit — #1221

**Date:** 2026-11-25  
**Finding:** the Nov 23–24 usage spike is inconclusive. The repository evidence does not identify a proven cause.

## What the runner did before this audit

- The scheduler could increase builders based on machine load, but local CPU/memory does not measure the owner's Claude subscription allowance.
- `drain --parallel N` was an explicit scheduler override.
- The run lock was per repository; it serialized drain/dispatch in the same repo, while different repos could build side by side.
- Builder restarts, turn-limit handoffs, API-error retries, review and fix calls all ultimately invoke Claude Code headlessly.
- The run log had usage/cost by story and round, but not Claude session ID, session start time, duration, active concurrency, or a durable start/end pair. Timeout rows did not contain usage/cost.

## Protection added in PR #1220

The default `maxBuilders` is now 1, and the default cumulative story ceiling is $6. A story is checked before another builder round, but the old check allowed another round at exactly $6 and treated unknown costs as zero.

## Follow-up changes in this branch

- A process-safe lock around **the actual model invocation**, not only the drain scheduler. Every headless `claude -p` call shares the same local slots, including readers/fixes and work started through another command. `--parallel N` may queue work but cannot create more active Claude CLI calls than `maxBuilders`.
- Durable start/end records in `~/.olivercode/model-sessions.jsonl` with session ID, story label, model, local repo/worktree label, timestamp, duration, slot/cap, active-session count, resumed flag, stop reason, exit code, token categories and cost when reported. Prompt text and transcript contents are not stored.
- Session-start telemetry must write before a Claude process is allowed to start. A missing completion or unpriced session is treated as unknown for that story and parks it before another session.
- The story spend check now parks at **greater than or equal to** the configured ceiling, and the same check runs at every model-session start—including internal validation repairs and reviews—so those calls cannot bypass the outer drain budget.\n- A configurable **8-session per-story attempt ceiling** (`maxStoryAttempts`) is counted from durable session-start records and legacy traces, persists across process restarts/handoffs, and parks the story when exhausted.
- Regression tests cover slot serialization/release, telemetry failure, unknown cost, and exact-ceiling parking.

## Retry and requeue ceilings already in the runner

- Builder rounds: three restarts after the first round (four total per drain run).
- Turn-limit handoffs: park after two consecutive stops.
- CLI timeout: resume the same Claude session once, then stop.
- Reader: at most two attempts for a verdict.
- Reader finding: one fix session, followed by another read.
- Commit-message gate: bounded to four builder rounds, then backlog.
- API errors: exponential backoff per story and a stop after five consecutive queue-wide errors.
- The new `maxStoryAttempts` ceiling adds a persistent cross-run cap to these existing per-run limits.


## Limits of this protection and the root-cause investigation

The slot lock is machine-local. It cannot see interactive Claude sessions, other machines, or other processes that do not use OliverCode. It is therefore an OliverCode concurrency cap—not a Claude-account API-enforced quota. One model invocation can itself exceed the story's ceiling before its final cost is reported; the runner can stop subsequent sessions, not retroactively limit that call.

The local run log begins after the suspected onset window. Failure-log clusters show guard/workflow friction, not model spend, and story throughput is only a proxy. Without the owner's account usage record or telemetry from the missing window, #1080 shared-file concurrency, #1113 handoffs, #1096 retry paths, and #1108 adaptive scheduling remain hypotheses. Do not label any one as the root cause.

## Verification status

The branch has regression tests added, but they have **not been run** in this environment. Review and run the suite locally before merging; this PR should remain draft until tests pass and the owner confirms the default cap/ceiling behavior on the machine that experienced the spike.
