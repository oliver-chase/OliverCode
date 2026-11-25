"""The one model-call layer: every model call OliverCode makes runs Claude Code headless (`claude -p`) through `run_cli`.

OliverCode holds no API key and makes no paid API call. The model, its tools and its hooks are the owner's signed-in Claude Code, so a call
is covered by the same subscription as an interactive session. Standard library only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from lib import claude_settings

TIMEOUT = 900
ALLOWED_TOOLS = "Read,Edit,Write,Bash,Grep,Glob"
EMPTY_MCP = '{"mcpServers":{}}'  # with --strict-mcp-config, no connector loads into a headless run (#878)
PROJECT_ENV = "OLIVERCODE_PROJECT_SETTINGS"  # unset or "1" runs each headless call with the project's settings and OliverCode's hooks only (#911, #1016); "0" loads the owner's current setup
HEADLESS_ENV = "OLIVERCODE_HEADLESS"  # "1" in every headless call's environment; session_check reads it and skips the placement scan (#911)


STDERR_TAIL = 800  # characters of the CLI's stderr a result keeps (#877)


class ModelError(RuntimeError):
    """A call the layer refused or could not complete. The message says why and what to do."""


class ModelTimeout(ModelError):
    """The call ran past its timeout and was stopped. `session_id` names the Claude Code session it was running, so a caller can resume it (#877)."""

    def __init__(self, message: str, session_id: str = ""):
        super().__init__(message)
        self.session_id = session_id


def available() -> bool:
    return bool(shutil.which("claude"))


def user_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def project_settings() -> str:
    """The `--settings` JSON a project-only run takes: only OliverCode's hook entries from the owner's settings file, so the gates and guards still run (#911).
    Raises ModelError when that file gives none, because a run without them would commit with no gate."""
    path = user_settings()
    try:
        hooks = claude_settings.managed_hooks(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        hooks = {}
    if not hooks:
        raise ModelError(f"A project-only run needs OliverCode's hooks in {path}, and that file has none. Run `scripts/olivercode install`.")
    return json.dumps({"hooks": hooks})


def run_cli(prompt: str, cwd: str, allowed_tools: str = ALLOWED_TOOLS, max_turns: int = 8, timeout: int = TIMEOUT, session: str = "",
            system: str = "", model: str = "", resume: str = "", project_only: bool | None = None) -> dict:
    """Run `claude -p` once in a directory: {'code', 'text', 'tokens', 'session_id', 'usage', 'cost_usd', 'stop', 'stderr', 'settings'}. `resume` continues an earlier Claude Code session.
    `stop` is the CLI's own stop reason: its `terminal_reason` ('max_turns' when the turn cap ended the session), else its result subtype, and '' when it gave none (#877).
    `stderr` is the last STDERR_TAIL characters of what the CLI wrote to stderr.
    `project_only` runs the session with the project's settings and OliverCode's own hooks, with the owner's ~/.claude settings left out (#911). None reads PROJECT_ENV, which is project-only unless it is "0" (#1016), and
    `settings` names which setup ran: 'project' or 'current'. The installed OliverCode hooks run on every tool the call uses, because Claude Code loads them from ~/.claude.
    `--tools` narrows the built-in set the CLI makes available, not only what `--allowedTools` pre-approves, so a call never carries the agent listing or the deferred-tool listing for a tool it cannot use (#1146).
    `--disable-slash-commands` drops the skill listing, because a headless call never runs one by name."""
    if not available():
        raise ModelError("The claude command is not on PATH. Install Claude Code and sign in with `claude`.")
    if project_only is None:
        project_only = os.environ.get(PROJECT_ENV) != "0"
    argv = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", str(max_turns)]
    argv += ["--strict-mcp-config", "--mcp-config", EMPTY_MCP]
    argv += ["--disable-slash-commands"]
    if project_only:
        argv += ["--setting-sources", "project,local", "--settings", project_settings()]
    if allowed_tools:
        argv += ["--tools", allowed_tools, "--allowedTools", allowed_tools]
    if system:
        argv += ["--append-system-prompt", system]
    if model:
        argv += ["--model", model]
    if resume:
        argv += ["--resume", resume]
        known = resume
    else:
        known = str(uuid.uuid4())  # a session id we chose, so a run that times out can still be resumed
        argv += ["--session-id", known]
    env = {**os.environ, HEADLESS_ENV: "1"}
    try:
        ran = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ModelTimeout(f"claude -p ran past {timeout} seconds and was stopped.", known) from exc
    out = {"code": ran.returncode, "text": ran.stdout, "tokens": 0, "session_id": "", "stop": "", "stderr": (ran.stderr or "").strip()[-STDERR_TAIL:],
           "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "cost_usd": None,
           "settings": "project" if project_only else "current", "is_error": False}
    try:
        data = json.loads(ran.stdout)
        out["text"] = str(data.get("result") or "")
        out["session_id"] = str(data.get("session_id") or "")
        out["stop"] = str(data.get("terminal_reason") or data.get("subtype") or "")
        out["is_error"] = bool(data.get("is_error"))
        if not out["text"] and data.get("errors"):
            out["text"] = "; ".join(str(e) for e in data["errors"])
        usage = data.get("usage") or {}
        ints = {k: v for k, v in usage.items() if isinstance(v, int) and k.endswith("tokens")}
        out["tokens"] = sum(v for k, v in ints.items() if "cache_read" not in k)
        out["usage"] = {"input": ints.get("input_tokens", 0), "output": ints.get("output_tokens", 0),
                        "cache_read": ints.get("cache_read_input_tokens", 0), "cache_write": ints.get("cache_creation_input_tokens", 0)}
        cost = data.get("total_cost_usd")
        out["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None
    except (ValueError, AttributeError):
        pass
    return out
