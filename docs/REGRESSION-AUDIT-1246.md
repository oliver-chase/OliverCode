# Regression audit for #1246

Measured on 26 Nov 2026 at commit `80ddb7ed`, which is kept on the branch `archive/2026-11-25`. Main was restored to the tree of `18ad4ff9` after this measurement (#1269). Times are US Eastern. The figures come from the headless session transcripts, the run log, the landing logs, the closed-issue list and the commit history, including the pre-squash backup for 22 Nov.

## Two-hour windows, 22 Nov 12:00 to 24 Nov 24:00

Landings are runs of `olivercode land` that ended in `pushed` or in a failure. Builder sessions are headless sessions started in a story worktree. Stories closed counts issues closed as completed.

| Window | Main commits | Landings pushed | Landings failed | Stories closed | Builder sessions |
|---|---:|---:|---:|---:|---:|
| 22 Nov 12–14 | 29 | 15 | 0 | 14 | 0 |
| 22 Nov 14–16 | 18 | 7 | 0 | 7 | 0 |
| 22 Nov 16–18 | 22 | 8 | 0 | 6 | 0 |
| 22 Nov 18–20 | 11 | 4 | 0 | 4 | 0 |
| 22 Nov 20–22 | 34 | 15 | 0 | 2 | 1 |
| 22 Nov 22–24 | 18 | 13 | 0 | 20 | 19 |
| 23 Nov 00–02 | 12 | 8 | 0 | 6 | 19 |
| 23 Nov 02–04 | 0 | 5 | 0 | 9 | 14 |
| 23 Nov 04–06 | 0 | 2 | 0 | 0 | 0 |
| 23 Nov 06–08 | 0 | 0 | 0 | 2 | 0 |
| 23 Nov 08–10 | 13 | 13 | 0 | 14 | 23 |
| 23 Nov 10–12 | 13 | 11 | 0 | 10 | 42 |
| 23 Nov 12–14 | 19 | 19 | 0 | 18 | 101 |
| 23 Nov 14–16 | 12 | 11 | 0 | 10 | 118 |
| 23 Nov 16–18 | 14 | 15 | 0 | 14 | 127 |
| 23 Nov 18–20 | 8 | 5 | 3 | 3 | 82 |
| 23 Nov 20–22 | 13 | 5 | 4 | 4 | 48 |
| 23 Nov 22–24 | 7 | 2 | 0 | 3 | 45 |
| 24 Nov 00–02 | 3 | 3 | 0 | 7 | 26 |
| 24 Nov 02–04 | 12 | 12 | 1 | 12 | 53 |
| 24 Nov 04–06 | 10 | 9 | 0 | 10 | 99 |
| 24 Nov 06–08 | 13 | 12 | 1 | 15 | 52 |
| 24 Nov 08–10 | 0 | 0 | 0 | 0 | 3 |
| 24 Nov 10–12 | 4 | 0 | 0 | 14 | 0 |
| 24 Nov 12–14 | 3 | 0 | 0 | 4 | 0 |
| 24 Nov 14–16 | 0 | 0 | 0 | 0 | 0 |
| 24 Nov 16–18 | 2 | 0 | 0 | 2 | 0 |
| 24 Nov 18–20 | 2 | 0 | 0 | 2 | 0 |
| 24 Nov 20–24 | 0 | 0 | 0 | 0 | 0 |

The work on 22 Nov before 20:00 was done by interactive sessions. Headless builders start at 20:00 on 22 Nov. No headless builder session and no pushed landing is recorded after 08:06 on 24 Nov.

## Cost per landing, from the run log

The run log carries a time on each row from 09:43 on 23 Nov to 08:06 on 24 Nov. Cost is the figure the CLI reports for each session.

| Window | Landings | Build sessions | Review sessions | Cut short | Cost | Cost per landing | Sessions per landing |
|---|---:|---:|---:|---:|---:|---:|---:|
| 23 Nov 10–12 | 11 | 29 | 11 | 3 | $13.2 | $1.20 | 3.6 |
| 23 Nov 12–14 | 19 | 60 | 42 | 3 | $22.5 | $1.18 | 5.4 |
| 23 Nov 14–16 | 11 | 67 | 54 | 4 | $20.7 | $1.88 | 11.0 |
| 23 Nov 16–18 | 15 | 66 | 58 | 2 | $19.1 | $1.27 | 8.3 |
| 23 Nov 18–20 | 5 | 50 | 37 | 3 | $15.4 | $3.08 | 17.4 |
| 23 Nov 20–22 | 5 | 37 | 19 | 2 | $7.9 | $1.58 | 11.2 |
| 23 Nov 22–24 | 2 | 28 | 19 | 2 | $6.7 | $3.35 | 23.5 |
| 24 Nov 00–02 | 3 | 17 | 10 | 2 | $3.9 | $1.31 | 9.0 |
| 24 Nov 02–04 | 12 | 41 | 12 | 1 | $5.1 | $0.43 | 4.4 |
| 24 Nov 04–06 | 9 | 80 | 25 | 7 | $11.5 | $1.28 | 11.7 |
| 24 Nov 06–08 | 12 | 45 | 13 | 6 | $7.1 | $0.59 | 4.8 |

- Highest output: 23 Nov 12–14, 19 landings.
- Lowest cost per landing: 24 Nov 02–04 and 06–08, 12 landings each at $0.43 and $0.59. Review sessions fell from 54–58 a window to 12–13 after small routine stories began landing on validation alone (#1111, on main at 23:04 on 23 Nov).
- The average number of builder sessions running at once never passed 1.8 in any window.

## How each drain run ended

| Run ended | Last line |
|---|---|
| 23 Nov 11:06 | a story landed and closed |
| 23 Nov 19:36 | Drain stopped: 1 building story released to Ready |
| 23 Nov 21:16 | Drain stopped: 5 building stories released to Ready |
| 23 Nov 21:23 | Drain stopped: 3 building stories released to Ready |
| 23 Nov 23:03 | Drain stopped: 3 building stories released to Ready |
| 24 Nov 04:30 | Drain stopped: 3 building stories released to Ready |
| 24 Nov 06:36 | Drain stopped: 3 building stories released to Ready |
| 24 Nov 08:06 | Drain done: 12 stories closed, 9 blocked, 28 sessions |

Six of eight runs ended on a stop signal with builders still working. The last run finished its queue with 9 of 21 stories blocked, and no run was started after it.

## Why landings stopped

Result words across the 61 landing handovers:

| Result | Count |
|---|---:|
| validate-failed | 25 |
| rebase-conflict | 16 |
| limits-refused | 10 |
| outside-area | 7 |
| dirty-worktree | 2 |
| main-kept-moving | 1 |

## Test suite at candidate commits

Each commit was cloned and its suite run in an empty home, with `gh`, `claude` and `osascript` replaced by stubs.

| Commit | Time | Tests | Result |
|---|---|---:|---|
| `ab30cde1` | 23 Nov 12:08 | 1,668 | all pass |
| `011167c1` | 23 Nov 14:08 | 1,782 | all pass |
| `18ad4ff9` | 23 Nov 17:23 | 1,850 | all pass |
| `9b4c8aeb` | 23 Nov 18:53 | 1,916 | `test_candidates` fails |
| `2ca2a225` | 24 Nov 00:50 | 1,987 | `test_candidates` fails |
| `bc144305` | 24 Nov 07:42 | 2,096 | `test_candidates` fails |
| `80ddb7ed` | 25 Nov 22:44 | 2,263 | 13 modules fail, the end-to-end drain test among them |

## Share of the runner's work

Of 239 landing logs, 219 are for this repository and 20 are for governed repositories.

## Defects confirmed at `80ddb7ed`

- `cmd_land.weakened` raises on a diff that adds test assertions with no net code, so the landing fails. Added in `373045d7`.
- A session that ends on the time limit records no cost, and the spend check then refuses every later session for that story. A drain stopped by a signal leaves the same state for each story in flight. One unreadable line in the run log refuses every story.
- A registered hook whose script file is missing exits 2, which blocks the prompt or tool call. Health skips the missing-script check when the instruction link is absent.
- The suite shows a desktop notification from a `test_drain` fixture on every run, and calls the real `gh` when no fake is supplied.
- `olivercode uninstall` left five scheduled jobs loaded.
- Filing accepts a story with no Files area and dispatch refuses it.
- The CI workflow is disabled and the default branch is unprotected.
