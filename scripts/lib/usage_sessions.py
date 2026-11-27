"""Finds the transcripts under ~/.claude/projects, for the scheduled-task spend report (#782)."""

from __future__ import annotations

from pathlib import Path

from lib.local_config import claude_dir


def transcript(cli_id: str, projects: Path | None = None) -> Path | None:
    projects = projects or claude_dir() / "projects"
    for f in projects.glob(f"*/{cli_id}.jsonl") if cli_id and projects.is_dir() else []:
        return f
    return None
