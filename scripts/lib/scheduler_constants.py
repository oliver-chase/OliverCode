"""The scheduler's cadences, defined once for tick.py (which fires jobs) and the health check (which judges them)."""

HOUR_S = 60 * 60
DAY_S = 24 * HOUR_S

# How often each job should run, as the owner chose it.
PUSH_FLEET_CADENCE_S = 3 * HOUR_S
AUDIT_FLEET_CADENCE_S = 7 * DAY_S

# tick.py fires a little short of the true cadence so a tick never drifts to just-barely-late.
PUSH_FLEET_INTERVAL_S = PUSH_FLEET_CADENCE_S - 10 * 60       # ~3h
AUDIT_FLEET_INTERVAL_S = AUDIT_FLEET_CADENCE_S - 4 * HOUR_S  # ~6.83 days, the sibling scheduler's weekly margin
