"""Owner-facing local report for builder lifecycle telemetry."""
from __future__ import annotations

from lib import builder_telemetry


def command_telemetry(argv: list[str]) -> int:
    hours = 24.0
    if len(argv) == 2 and argv[0] == "--hours":
        try:
            hours = float(argv[1])
        except ValueError:
            hours = 0
        if not 0 < hours <= 24 * 365:
            print("Usage: olivercode telemetry [--hours N] (N must be greater than 0 and no more than 8760)")
            return 2
    elif argv:
        print("Usage: olivercode telemetry [--hours N]")
        return 2

    data = builder_telemetry.summarize(hours)
    print(f"Builder telemetry · last {hours:g} hours")
    print(f"Builder starts: {data['builder_starts']}")
    print(f"Completed: {data['completed']} · held or interrupted: {data['not_landed']}")
    if data["average_active"] is None:
        print("Average active builders: not enough complete lifecycle records yet.")
        print("Peak overlap: not recorded.")
    else:
        print(f"Average active builders: {data['average_active']:.2f}")
        print(f"Peak overlap: {data['peak_active']}")
    if data["average_queue_wait_s"] is None:
        print("Average claim-to-start wait: not recorded.")
    else:
        print(f"Average claim-to-start wait: {data['average_queue_wait_s']:.1f}s")
    print(f"Unmatched starts: {data['unmatched_starts']} · unmatched finishes: {data['unmatched_ends']} · malformed events: {data['malformed_events']}")
    print("Source: ~/.olivercode/builder-events.jsonl. Model-session details remain in model-sessions.jsonl.")
    return 0
