"""A launcher that runs from a live bot's folder.

`liveCopies` in `olivercode.local.json` maps each path a running bot reads to the agent copy of
that repo. An install or update run from the live path writes into the bot, so `conform` and
`install` refuse it and name the agent copy to use instead.
"""

from __future__ import annotations

from pathlib import Path

from lib import local_config


def live_copies() -> dict[Path, Path]:
    """Each live path (resolved) with the agent copy that stands in for it."""
    raw = local_config.load_local().get("liveCopies", {})
    return {Path(live).expanduser().resolve(): Path(agent).expanduser() for live, agent in raw.items()}


def problem(launcher: Path, copies: dict[Path, Path] | None = None) -> str:
    """The sentence naming the agent copy to use when the launcher sits in a live path, or an empty string."""
    here = Path(launcher).resolve()
    for live, agent in (live_copies() if copies is None else copies).items():
        if here == live or live in here.parents:
            return f"the launcher runs from {live}, which a running bot reads; use the agent copy at {agent}"
    return ""
