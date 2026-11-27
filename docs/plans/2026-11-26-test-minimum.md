# Test minimum audit (#1322)

Audit of which tests guard script lines that no other test guards, measured on staging at 8bb39657.

## Counts

- Script lines: `scripts/` tracked files 18,737 lines (17,817 in the 97 `.py` files). The story's figure was 18,632.
- Test lines: `tests/` 18,687 lines in 113 files, plus `skills/*/scripts/test_*.py` 3,220 lines. The story's figure was 21,754.
- Ratio: 18,687 / 17,817 is about 1.05 test lines per script line in `scripts/*.py`.

## Method

The story's literal command, `coverage run --context=test -m unittest discover tests`, records one static context for the whole run, so it cannot say which file covers a line. It ran here as a baseline: 1,594 tests, one failure (`test_drain`, the engine-repository scratch-copy test) and one broken-link finding, both present on staging before this audit.

Attribution used one coverage run per test module, in a clean clone with a temporary HOME. Subprocess coverage was on through a `.pth` hook and a `python3` shim, so scripts run as child processes are measured. For each module the audit collected the `scripts/` lines it executed and took the lines no other module executed. 110 modules ran. `test_drain` exited non-zero, from the same failure as above.

Limit: shell scripts (`validate.sh`, the git hooks, `olivercode` if it is a shell wrapper) are not measured by coverage. A module with zero measured Python lines may still guard a shell script, so it cannot be marked remove on this evidence alone.

## Result

- 86 modules keep: each executes at least one script line no other module executes.
- 24 modules have no unique Python script line. Seven of them run no shell script (below) and are marked **remove**. Seventeen touch shell scripts or hooks and are marked **hold** until that is checked.

### Remove (7 files, 420 lines)

| File | Lines |
|---|---|
| test_deploy_template.py | 36 |
| test_failure_log.py | 107 |
| test_gate_binary.py | 57 |
| test_gate_secrets_variants.py | 67 |
| test_repo_profiles.py | 84 |
| test_skill_links.py | 43 |
| test_skills_catalog.py | 26 |

### Hold (17 files, 1,907 lines)

test_clean_clone_install, test_commit_msg, test_commit_msg_closes, test_gate_content, test_gate_secrets, test_gitfiles, test_owner_identifiers, test_pre_push, test_precommit_gates, test_run_tests_snapshot, test_script_paths, test_smoke_gate_runs_skill_tests, test_structure_contract, test_support_guard, test_update_rewritten_remote, test_validate_checks, test_validate_gates.

Open-story check: each candidate was checked against the open story titles only. No title names a behaviour one of the seven remove files asserts. #1286 and #1287 remove code that `test_skills_catalog` and `test_skill_links` may exercise, so the removal waits for those to land and the audit re-runs afterwards.

## Before and after

- Before: 18,687 lines in `tests/`.
- After the remove group: 18,267 lines (-420).
- After the hold group too, if it is confirmed safe to remove: 16,360 lines (-2,327).

## Fix stories

1. **Remove seven redundant test files** (XS, 420 lines). Runs after #1286 and #1287 land, then the audit runs again.
2. **Verify the hold group against shell coverage** (S). Measure `validate.sh` and the git hooks, then mark each hold file keep or remove. Removal of any file found to guard a shell script is out of scope.

## Per-test audit (#1339)

Whole suite, `tests/` and `skills/*/scripts/test_*.py`, measured per test on staging at 98aece0.

### Method

- One coverage run per test module (4 at a time), `dynamic_context = test_function`, `core = ctrace`, over `scripts/` and `skills/*/scripts/`. Test files are omitted.
- Subprocess coverage on: a `.pth` hook starts coverage in each child process. It records under the context of the test that spawned it, so lines a script reaches in a child process are attributed to that test.
- Shell scripts are not line-measured (coverage.py does not trace bash). Any test whose file names a shell script, a git hook or `run-tests` is marked hold, not remove.
- Each test is then classed: **keep** if it reaches a script line no other test reaches; **remove** if every line it reaches is also reached by another test and it touches no shell file; **hold** if it reaches no measured line or touches shell.

### Counts

- 1971 tests run (1,971, including skill tests), 1,776 of them reach a measured line.
- keep 717, remove 432, hold 822.
- Plain `unittest` pass: `test_drain` fails here as on staging before this audit (#1322).

### Assertion check: not done

The story's second scenario needs each **remove** candidate checked against the open stories' scenarios. That check is per test and is not done in this audit. So every **remove** below is a candidate, not a verdict. Each removal story re-checks its tests' assertions against the open stories before deleting anything. Open stories at this audit: #1289, #1315, #1288, #1287, #1365, #1366, #1367, #1368, #1369, #1370, #1351, #1350, #1309.

### Remove candidates by file

| File | Tests | Candidates | Lines (span) | Hold |
|---|---|---|---|---|
| tests/test_gh_budget.py | 49 | 31 | 182 | 0 |
| tests/test_status.py | 42 | 29 | 156 | 0 |
| skills/backlog/scripts/test_board_hygiene.py | 33 | 21 | 137 | 0 |
| skills/audit/scripts/test_done_check.py | 24 | 20 | 93 | 0 |
| tests/test_install.py | 26 | 13 | 88 | 2 |
| tests/test_city.py | 27 | 15 | 85 | 0 |
| tests/test_groom.py | 28 | 14 | 75 | 3 |
| tests/test_board_mirror.py | 8 | 8 | 69 | 0 |
| skills/backlog/scripts/test_board_rest.py | 10 | 8 | 64 | 0 |
| tests/test_early_stop_guard.py | 20 | 18 | 64 | 0 |
| tests/test_handoff.py | 14 | 8 | 59 | 0 |
| tests/test_wip.py | 17 | 8 | 59 | 1 |
| tests/test_owner_queue.py | 8 | 5 | 54 | 0 |
| tests/test_model.py | 14 | 8 | 52 | 0 |
| tests/test_local_config.py | 11 | 9 | 51 | 0 |
| tests/test_claims.py | 14 | 6 | 49 | 4 |
| tests/test_main_checkout.py | 13 | 7 | 49 | 0 |
| tests/test_remote_branches.py | 16 | 9 | 47 | 0 |
| tests/test_guide.py | 15 | 8 | 46 | 2 |
| tests/test_install_automode.py | 11 | 7 | 45 | 0 |
| tests/test_olivercode_on_path.py | 13 | 7 | 44 | 0 |
| tests/test_status_hint.py | 10 | 7 | 44 | 0 |
| skills/audit/scripts/test_findings.py | 15 | 4 | 43 | 0 |
| skills/backlog/scripts/test_kanban_baseline.py | 14 | 10 | 43 | 0 |
| tests/test_queue_shim.py | 11 | 7 | 41 | 0 |
| tests/test_removed_jobs.py | 7 | 5 | 40 | 0 |
| tests/test_update_keeps_local_learning.py | 8 | 5 | 38 | 0 |
| tests/test_user_state_survives_update.py | 9 | 4 | 36 | 2 |
| skills/audit/scripts/test_fleet.py | 11 | 10 | 34 | 0 |
| skills/audit/scripts/test_audit_ledger.py | 11 | 6 | 31 | 0 |
| tests/test_boardsweep.py | 11 | 7 | 28 | 0 |
| tests/test_limits.py | 10 | 5 | 28 | 1 |
| tests/test_registry_location.py | 12 | 8 | 28 | 2 |
| tests/test_reset_guard.py | 7 | 5 | 26 | 0 |
| tests/test_voice_copies.py | 7 | 5 | 26 | 0 |
| tests/test_activation_links.py | 4 | 4 | 25 | 0 |
| tests/test_outsiders.py | 7 | 5 | 24 | 0 |
| tests/test_city_cost.py | 5 | 4 | 22 | 0 |
| skills/audit/scripts/test_audit_mode.py | 9 | 6 | 21 | 1 |
| tests/test_private_home.py | 7 | 3 | 21 | 3 |
| tests/test_skill_links.py | 3 | 3 | 20 | 0 |
| tests/test_split.py | 5 | 4 | 20 | 0 |
| tests/test_update_runs_install.py | 6 | 4 | 19 | 0 |
| tests/test_model_guard.py | 5 | 4 | 17 | 0 |
| skills/backlog/scripts/test_batch_project.py | 7 | 2 | 16 | 0 |
| tests/test_city_refresh.py | 4 | 2 | 16 | 0 |
| tests/test_update_rewritten_remote.py | 4 | 4 | 16 | 0 |
| tests/test_city_delivery.py | 4 | 3 | 15 | 0 |
| tests/test_run_lock.py | 12 | 3 | 15 | 0 |
| tests/test_denials.py | 5 | 2 | 13 | 0 |
| tests/test_init_fleet.py | 8 | 1 | 12 | 2 |
| tests/test_intake.py | 5 | 1 | 12 | 0 |
| tests/test_name_drift.py | 4 | 2 | 12 | 0 |
| tests/test_rename_check.py | 4 | 2 | 12 | 0 |
| skills/audit/scripts/test_check_report.py | 8 | 3 | 11 | 0 |
| tests/test_decisions_import.py | 3 | 1 | 11 | 0 |
| tests/test_engine_only.py | 7 | 2 | 11 | 4 |
| tests/test_leak_scan.py | 6 | 3 | 11 | 0 |
| tests/test_harness_commands.py | 7 | 2 | 10 | 0 |
| tests/test_live_copy.py | 4 | 3 | 10 | 0 |
| tests/test_open_issues.py | 4 | 2 | 10 | 0 |
| tests/test_scan_speed.py | 4 | 2 | 10 | 0 |
| tests/test_skills_catalog.py | 1 | 1 | 9 | 0 |
| tests/test_maintain_synced.py | 12 | 1 | 8 | 0 |
| tests/test_board_command.py | 2 | 1 | 5 | 0 |
| tests/test_harness_isolation.py | 3 | 1 | 5 | 1 |
| skills/backlog/scripts/test_issue_count.py | 2 | 1 | 5 | 0 |
| tests/test_launchd_path.py | 6 | 2 | 5 | 0 |
| tests/test_relay.py | 5 | 1 | 5 | 0 |

Total candidates: 432 tests in 69 files, 2508 lines.

### Slowest test files

Seconds from the coverage runs, four modules at a time, so they run longer than a plain run. A plain sequential pass was started and stopped before it finished, so these are the figures available.

| Test file | Seconds |
|---|---|
| test_land | 54.9 |
| test_commit_msg | 31.4 |
| test_validated_push | 21.5 |
| test_owner_identifiers | 19.7 |
| test_backlog_setup | 14.4 |
| test_bootstrap_output | 13.9 |
| test_launcher_commands | 12.2 |
| test_drain_canary | 11.8 |
| test_claude_hooks | 10.0 |
| audit-test_check_skill_structure | 9.8 |

### Close-out

Removal stories are not filed yet. When they are, each takes one file group from the table above, runs the assertion check first, and names the lines it removes and the seconds it saves. The seconds are taken from the file's share of the run.

