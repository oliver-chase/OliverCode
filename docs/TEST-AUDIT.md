# Test audit

The audit of OliverCode's test suite for value, brittleness, duplication and runtime (#1181). It records what exists, what was measured, what changed and what to do next. No test module was removed.

## Method

- Counts come from the test functions in each module, read from the source on `main` at 4030766
- Runtimes come from one `bash scripts/validate.sh` run on an 8-core Mac with four smoke workers. The run shared the machine with other work, so each figure is higher than an idle run, and the figures compare to each other and to the same machine's later runs
- Per-test times come from running a module alone with a timing runner
- A module's category comes from the behavior it protects, and a cluster is a set of modules that protect one area

## Inventory

151 test modules hold 2,162 tests. 130 modules sit under `tests/` and 21 under `skills/`, which ship with the skills and stay.

| Cluster | Modules | Tests | Module seconds in the run |
|---------|---------|-------|---------------------------|
| Landing, claims, queue and runner | 25 | 481 | 222 |
| Hooks, gates and scans | 23 | 331 | 170 |
| Install, launcher, PATH and fleet | 19 | 296 | 115 |
| Status, groom, board and backlog | 22 | 387 | 92 |
| Docs, guide and skill text | 10 | 85 | 8 |
| Health, maintenance and other | 52 | 582 | 141 |

The module seconds add up to more than the wall time of the gate, because four workers run modules at once.

### Slowest modules

| Module | Tests | Why it is slow | Verdict |
|--------|-------|----------------|---------|
| `test_land` | 63 | A real `git` process for each fetch, merge, push and worktree step. A tree copy costs about 19 ms of a 390 ms test, so setup is not the cost | Keep. Safety coverage for landing and claims |
| `test_queue_shim` | 12 | Real shell and the installed wrapper | Keep the real invocation. The health calls were the other half of its time and are fixed below |
| `test_commit_msg` | 34 | 47 real `git commit` calls through the hook | Keep. Each case is a different message rule |
| `test_olivercode_on_path` | 12 | Four real login and interactive zsh and bash starts | Keep. Distinct PATH contracts |
| `test_drain_canary` | 3 | One fake story through the real drain, land and close | Keep. Runs at the push to the default branch (see Tiers) |
| `test_groom`, `test_story_outbox`, `test_maintain` | 46, 12, 39 | Each ran a full `olivercode health` for a single line | Changed below |

## What changed

**Health tests no longer walk the machine's worktrees.** Five modules called the full `olivercode health` to read one line each. 3.8 of its 5.1 seconds were two checks that list every git worktree of the real checkout, which also made the result depend on the machine. `quiet_health` in `tests/_support.py` runs health with those two checks stubbed. The checks keep their own tests in `test_land`, and `test_maintain` holds one test that health still calls both.

| Module | Before | After |
|--------|--------|-------|
| `test_story_outbox` | 11.0 s | 2.6 s |
| `test_groom` | 12.1 s | 3.2 s |
| `test_queue_shim` | 23.9 s | 6.4 s |
| `test_olivercode_on_path` | 17.4 s | 4.4 s |
| `test_maintain` | 8.3 s | 4.0 s |
| Total | 72.7 s | 20.6 s |

Each figure is one run of the module alone on the same machine, before and after, with the same tests passing. That is 52 seconds less work for the gate to schedule. The gate's wall time falls by less, because the modules run in parallel.

**One exact-prose assertion became a contract check.** `test_install` asserted the whole step 3 sentence twice, once for the install text and once for the guide, and failed on 2026-11-25 when the wording changed with no change in behavior. It now finds step 3 in each output and requires it to name the story and both commands, `olivercode dispatch` and `olivercode drain`.

## Brittle and redundant tests

- The step 3 sentence above is the clearest case. Wording the owner may reasonably change was a test failure
- Many modules assert long literal strings from output they format themselves. By count of assertions on literals of 25 or more characters, the most exposed are `test_status` (38 of 94 tests), `test_drain` (19 of 71), `test_complete_story` (17 of 27), `test_groom` (13 of 46) and `test_validate_gates` (11 of 29). Each is a rewrite candidate, one module at a time, when its output next changes. A literal stays when the exact text is the contract, such as a command the owner copies
- `test_docs_accuracy`, `test_guide`, `test_install` and `test_launcher_commands` (6, 14, 28 and 48 tests) overlap on onboarding wording. The rule sentence is now asserted once for the docs and once for the guide. Merge the rest into one authoritative test per invariant before adding new ones
- `test_land` copies a `seed` repository into every test and never reads it. It costs about 6 ms a test, so it is left alone until the next edit of that file

## Recommendations by cluster

| Cluster | Keep | Rewrite | Merge | Remove | Add |
|---------|------|---------|-------|--------|-----|
| Landing, claims, queue and runner | All of it: data loss, claims, locks, concurrency, API backoff, recovery | Exact message literals in `test_drain` and `test_complete_story` | None found | None | A race test for two dispatches claiming one story, if `test_dispatch` does not hold one |
| Hooks, gates and scans | All of it: secrets, personal data, commit and push refusal | Message literals once, in `test_hook_message` | None found | None | None |
| Install, launcher, PATH and fleet | The real shell and install probes | Onboarding wording in `test_install` (done for step 3) and `test_launcher_commands` | The four onboarding modules above | None | None |
| Status, groom, board and backlog | Behavior of each check | `test_status` literals | None found | None | None |
| Docs, guide and skill text | Link and catalog checks | Sentence assertions to semantic ones | With the install cluster | None | None |
| Health, maintenance and other | Each check's own test | None found | None found | None | None |

No test is recommended for removal. A removal needs a named test that protects the same behavior, and this pass found none.

## Tiers

Every test runs somewhere, and none is dropped.

1. **Fast, every round.** The smoke runner with `--changed`, which runs the modules affected by the changed files, plus the queue-bypass check and the commit gates on the changed files
2. **Targeted integration, for state, claims, hooks, landing and install changes.** The modules in the first three clusters that the change touches, including `test_land`, `test_drain_canary`, `test_commit_msg` and the PATH and shim probes
3. **Full, before a push to main, on landing and for a release.** `bash scripts/validate.sh`, about 90 seconds on an idle 8-core machine

`test_drain_canary` takes about 20 seconds for three tests. A full `validate.sh` run leaves it out and prints that it did, and `olivercode validated check` runs it once for each tree at the push to the default branch and records the pass (#1155). A round runs it when a changed file is one its code names.

## Not covered by this pass

- A test-by-test map of `test_commit_msg` for duplicate message cases
- Per-test profiles of `test_queue_shim` and `test_olivercode_on_path` beyond the health calls
- A gap analysis of destructive-action and trust-boundary tests beyond the clusters above

Each would be a follow-up with its own measurement.

## Removal log

| Date | Change | Reason | Evidence |
|------|--------|--------|----------|
| 2026-11-25 | No test removed | None met the bar of a named duplicate | Full run of 2,174 tests passes |
| 2026-11-25 | Step 3 assertion rewritten | Wording failure with no behavior change | `test_install` passes and fails when step 3 loses a command |
| 2026-11-25 | Five health calls use `quiet_health` | The worktree walk is not what those tests read | Times above, and `test_maintain` holds the call check |
