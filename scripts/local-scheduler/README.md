# OliverCode local scheduler

Runs `olivercode audit-fleet` and `olivercode push-fleet` on their own schedule, from a
Mac, via `launchd`. Mirrors a product repo's own `scripts/local-scheduler/` exactly --
same one-real-scheduler discipline, after that one already hit and fixed the failure mode
of two independent schedulers (`launchd` plus a separate `crontab` job) running the same
work with no lock between them.

## Set up on this Mac (or any Mac)

```bash
bash scripts/local-scheduler/install.sh
```

That's it. Needs `python3` on your `PATH` -- if `python3 scripts/olivercode --help` already
works, this works.

## What it does

One `launchd` agent fires `tick.py` every 15 minutes, plus once immediately on load (which
also covers "the Mac just woke up"). `tick.py` itself decides what's actually due by
checking marker files' elapsed time, not by exact-minute alignment -- a tick missed while
the Mac sleeps just means the next one catches up, instead of silently skipping the way
plain `cron` does.

- `push-fleet` -- every ~3 hours (see `tick.py`'s `JOBS` list for the exact number).
  Flushes already-committed work for the vault + OliverCode. Never commits.
- `audit-fleet` -- weekly. Runs `skill-governance/skill-fleet-audit`'s 3 static checks against the
  vault's skills and OliverCode's own, writes findings to a log, never fixes anything.

A failed job's marker is deliberately left untouched, so it stays "due" and the next tick
(15 minutes later) retries, instead of waiting a full interval.

## Moving to a new Mac

1. Clone this repo (and the vault, if `push-fleet`/`audit-fleet` should cover it too).
2. `bash scripts/local-scheduler/install.sh`.

Nothing else -- no machine-specific state to migrate.

## Retiring / moving off this Mac permanently

```bash
bash scripts/local-scheduler/uninstall.sh
```

Removes the `launchd` agent. State and logs under
`~/Library/Application Support/olivercode-scheduler/` are left in place -- delete that
folder by hand for a clean slate.

## Checking on it

```bash
launchctl list | grep olivercode
tail -f ~/Library/Application\ Support/olivercode-scheduler/logs/scheduler.log
python3 scripts/local-scheduler/tick.py   # force a tick right now
```
