"""The boards `olivercode board groom` keeps in order: OliverCode and every cloned fleet repo whose board has a backlog config (#982).

The nightly board sweep and its launchd job are gone. Groom does the sweep's work: it moves a closed story's card to Complete, adds an
open story with no card, and runs the intake check and the repeated-blocker check after the boards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lib.local_config import OC_ROOT, backlog_config
from lib.repo_profiles import iter_fleet, load_repo_profiles


def _verify(config: Path) -> None:
    """Exit when the config holds placeholders or names a repo that is not its checkout's origin."""
    sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
    import check_board_hygiene  # noqa: PLC0415
    check_board_hygiene.verify_config(json.loads(config.read_text(encoding="utf-8")), config)


def boards() -> list[tuple[str, Path]]:
    """(name, backlog config) for OliverCode and every cloned fleet repo whose board has a config, one per Project."""
    repos = [("OliverCode", OC_ROOT)]
    try:
        profiles, _ = load_repo_profiles(OC_ROOT)
        repos += [(name, path) for name, _, path in iter_fleet(profiles, OC_ROOT.parent) if (path / ".git").exists()]
    except (OSError, ValueError):
        pass
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


def repos(board_list=boards) -> list[tuple[str, str, int]]:
    """(name, owner/repo, epic number) for each board, for the intake check. The epic is the Epic line the repo's stories carry."""
    out = []
    for name, config in board_list():
        try:
            cfg = json.loads(config.read_text(encoding="utf-8"))
            out.append((name, f"{cfg['repoOwner']}/{cfg['repoName']}", int(cfg.get("epic") or 1)))
        except (OSError, ValueError, KeyError):
            continue
    return out
