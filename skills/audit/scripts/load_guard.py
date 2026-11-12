#!/usr/bin/env python3
"""How much work the machine can take right now: readers to start and whether mutation checks may run.

Usage:
    load_guard.py   # prints `readers: N` and `mutations: yes|no`; exit 2 and `wait:` when overloaded
The audit runs it before it starts readers. Readers only read. Test runs and mutation checks belong to the
lead, one at a time, and only while this prints `mutations: yes`. Tests: python3 -m unittest test_load_guard
"""

import os
import sys

MAX_READERS = 12


def advice(load, cores):
    """(readers, mutations_allowed) for a one-minute load average on `cores` cores."""
    if load > 2 * cores:
        return 0, False
    if load > cores:
        return max(1, MAX_READERS // 2), False
    return MAX_READERS, True


def main():
    load, cores = os.getloadavg()[0], os.cpu_count() or 1
    readers, mutations = advice(load, cores)
    if readers == 0:
        print(f"wait: load {load:.0f} on {cores} cores. Start nothing heavy and ask again in five minutes.")
        return 2
    print(f"readers: {readers}\nmutations: {'yes' if mutations else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
