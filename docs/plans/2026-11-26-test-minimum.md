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
