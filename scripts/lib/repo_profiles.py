"""Repo-profiles loader: local overlay if present, else the tracked example.

`local/repo-profiles.json` is gitignored — it holds the real fleet (repo
names, validation commands, keepalive config) for whoever's machine this is.
`shared/repo-profiles.example.json` is tracked and ships with placeholder
data only, so a stranger clone has something to load and a template to
copy from. Never both real data in one tracked file.
"""

import json


def load_repo_profiles(repo_root):
    """Return (profiles: dict, source_path: Path)."""
    local_path = repo_root / "local" / "repo-profiles.json"
    example_path = repo_root / "shared" / "repo-profiles.example.json"
    path = local_path if local_path.exists() else example_path
    with open(path) as f:
        data = json.load(f)
    return data.get("profiles", {}), path
