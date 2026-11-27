"""The boards `olivercode board sync` keeps in order: OliverCode, when its board has a backlog config (#982)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lib.local_config import OC_ROOT, backlog_config


def _verify(config: Path) -> None:
    """Exit when the config holds placeholders or names a repo that is not its checkout's origin."""
    sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
    import check_board_hygiene  # noqa: PLC0415
    check_board_hygiene.verify_config(json.loads(config.read_text(encoding="utf-8")), config)


def boards() -> list[tuple[str, Path]]:
    """(name, backlog config) for OliverCode, when its board has a config, one per Project."""
    repos = [("OliverCode", OC_ROOT)]
    found, seen = [], set()
    for name, path in repos:
        config = path / "docs" / "backlog-config.json"
        try:
            key = tuple(backlog_config(path)[k] for k in ("projectOwner", "projectNumber"))
            _verify(config)
        except (OSError, ValueError, KeyError, SystemExit):  # a config that names another repo's Project is never swept (#687)
            continue
        if key not in seen:
            seen.add(key)
            found.append((name, config))
    return found

