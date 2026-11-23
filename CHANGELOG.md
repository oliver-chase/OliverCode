# Changelog

Each section is one release, cut by `olivercode version-cut` from the rules in `docs/VERSIONING.md`.

## 2.0.0 - 2026-11-22

This release covers 15 to 23 November. One entry per capability describes what it does now.

### Commit gates
Every commit passes the secret, PII, owner-identifier, story-reference, version-file and voice gates, and `olivercode commit-check` runs the message gate on a draft before the commit. The hooks are written in `core/hooks/` and built by `scripts/build-hooks.py`.

### Hook guards
Session guards check each tool call for placement, policy, memory, model, reset, archived content and GitHub use. Each guard has an eval file with passing and failing cases, and every denial and hook run is logged so `olivercode cutlist` can name a guard that never fires.

### Limits and versions
`docs/LIMITS.json` holds one limit per file kind, and a file over its limit raises a warning. `olivercode version-cut` sets `VERSION` and writes the changelog once per day of activity, from the rules in `docs/VERSIONING.md`.

### Validation queue
`scripts/validate.sh` runs its checks through a queue, records how long each takes and reuses results already validated for the same tree, so a repeat run and a push cost little.

### Landing
`olivercode land` puts a story on main from its own worktree. Push approval, saved work in progress and the main-checkout guard protect unlanded work, and an update keeps local learning and user state.

### Owner queue
Steps only the owner can take, recorded decisions and activity from outside authors reach one queue that `olivercode owner` shows.

### Headless runner
`olivercode run`, `dispatch` and `drain` work queued stories in agent loops with a chosen model, review the result, sweep for gaps and drain the queue on a schedule.

### Board and story outbox
`olivercode board`, `groom`, `boardsweep` and `burndown` keep the backlog current from one shared local copy of the board. Story writes wait in an outbox while GitHub is busy and go out when it frees, and automatic filers write candidates for the owner to promote, so no scheduled job or hook files a story directly.

### Lessons and owner rules
Lessons are captured, checked for coverage and flagged when a rule has no gate. Owner rules carry the gate or skill that enforces them and decide what the queue accepts.

### Audit and backlog skills
The audit skill reads findings, modes and ledgers and checks the docs against the code. The backlog skill counts open stories, checks each story for its evidence and sweeps the board for gaps.

### Fleet and private split
`olivercode fleet`, `fleet-sync`, `init-fleet` and `install` register and update fleet repos from templates. Owner data stays in a private home, and the leak scan, name checks and engine-only checks keep the engine free of it.

### Health, status and schedules
`olivercode health`, `maintain`, `status` and `conform` report each machine, the open story count and the landing rate. Launchd schedules run the nightly jobs and `olivercode usage` reports their spend.

### Launcher and CI
`scripts/olivercode` registers every command, and framework CI runs the checks on each push.

### Docs
`README.md`, `CLAUDE.md` and the documents under `docs/` describe the system as it now stands, with the rules in `docs/RULES.md`, the gates in `docs/GATES.md` and the versions in `docs/VERSIONING.md`.
