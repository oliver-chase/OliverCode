"""Regression evals: replay fixed scenarios through the real hooks and compare each verdict with the expected one.

A scenario file in scripts/hooks/evals/ holds one guard's scenarios as JSON. Each scenario names its payload (the hook
stdin, or the commit message for the commit-msg gate), the fixture it needs and the expected verdict: allow, deny or ask,
with an optional substring of the reason. The hook runs as a subprocess in a temp OLIVERCODE_HOME with temp git repos,
so no scenario touches the machine's own state or the network.

    {"guard": "commit_guard", "entry": "pretool_guard.py",
     "scenarios": [{"name": "...", "repo": "gated", "payload": {"tool_name": "Bash", "tool_input": {"command": "..."}, "cwd": "{repo}"},
                    "expect": "deny", "reason": "--no-verify"}]}

Placeholders in any string: {repo} the scenario's checkout, {root} the repoRoot, {home} OLIVERCODE_HOME and {tmp} the scenario's folder, {wt} the linked worktree that the worktree fixture (clean or dirty) makes, and {at} an at sign, which keeps an address out of the tracked file.
A string "@now+N" becomes the current time plus N seconds. Fixture keys: repo (gated, unhooked or plain), worktree, origin, policy,
home_files, env, stage, history and voice. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lib.local_config import OC_ROOT

EVAL_DIR = OC_ROOT / "scripts" / "hooks" / "evals"
HOOKS = OC_ROOT / "scripts" / "hooks"
TEMPLATES = OC_ROOT / "core" / "templates" / "project"
VERDICTS = ("allow", "deny", "ask")
MESSAGE_LIMIT = 200  # a deny or ask message is one line that costs little context on every later call, and names the doc that explains it
WORKERS = 6
GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def load(guard: str | None = None, folder: Path | None = None) -> list[dict]:
    """Every scenario as a dict that also names its guard and entry."""
    found = []
    for path in sorted((folder or EVAL_DIR).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if guard and data["guard"] != guard:
            continue
        for sc in data["scenarios"]:
            if sc.get("expect") not in VERDICTS and "commits_added" not in sc:
                raise ValueError(f"{path.name}: scenario {sc.get('name')!r} has no allow, deny or ask expectation")
            found.append({"guard": data["guard"], "entry": data.get("entry", "pretool_guard.py"), **sc})
    return found


def guards(folder: Path | None = None) -> list[str]:
    return [json.loads(p.read_text(encoding="utf-8"))["guard"] for p in sorted((folder or EVAL_DIR).glob("*.json"))]


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, **GIT_ISOLATION}
    subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, capture_output=True)


def _template_repo(path: Path, kind: str) -> None:
    """A repo with one commit. gated ships .githooks/pre-commit and points git at it, unhooked ships it with hooksPath unset, plain ships none."""
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    for key, value in (("user.email", "eval" + "@" + "example.invalid"), ("user.name", "Eval"), ("maintenance.auto", "false"), ("gc.auto", "0")):
        _git(path, "config", key, value)
    if kind != "plain":
        (path / ".githooks").mkdir()
        hook = path / ".githooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
    if kind == "gated":
        _git(path, "config", "core.hooksPath", ".githooks")
    (path / "README").write_text("eval\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "first")


def _fill(value, ctx: dict):
    """Placeholders in every string of a JSON value, and "@now+N" as a number."""
    if isinstance(value, str):
        match = re.fullmatch(r"@now(?:\+(\d+))?", value)
        if match:
            return time.time() + int(match.group(1) or 0)
        for key, text in ctx.items():
            value = value.replace("{" + key + "}", text)
        return value
    if isinstance(value, list):
        return [_fill(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ctx) for k, v in value.items()}
    return value


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _setup(sc: dict, work: Path, templates: dict[str, Path]) -> tuple[dict, dict]:
    """Build the scenario's folders and return (placeholders, environment for the hook)."""
    root = work / "Repos"
    home = work / "oc-home"
    root.mkdir()
    home.mkdir()
    repo = root / "repo"
    ctx = {"repo": str(repo), "root": str(root.resolve()), "home": str(home.resolve()), "tmp": str(work.resolve()), "at": "@"}
    kind = sc.get("repo", "gated")
    shutil.copytree(templates[kind], repo, symlinks=True)
    ctx["repo"] = str(repo.resolve())
    if sc.get("origin"):
        _git(repo, "remote", "add", "origin", sc["origin"])
    if sc.get("worktree"):  # a linked worktree on a story branch; "dirty" leaves a tracked file modified
        wt = root / "_worktrees" / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "story/1", str(wt))
        ctx["wt"] = str(wt.resolve())
        if sc["worktree"] == "dirty":
            (wt / "README").write_text("changed\n", encoding="utf-8")
    for name, content in (sc.get("files") or {}).items():
        _write(repo / name, _fill(content, ctx))
    if sc.get("policy") is not None:
        _write(repo / ".olivercode" / "policy.json", _fill(sc["policy"], ctx))
    for name, content in (sc.get("home_files") or {}).items():
        _write(home / name, _fill(content, ctx))
    local = work / "local.json"
    _write(local, {"repoRoot": ctx["root"], "watchRoots": []})
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "OLIVERCODE_"))}
    env.update(GIT_ISOLATION)
    env.update({"HOME": ctx["tmp"], "OLIVERCODE_HOME": ctx["home"], "OLIVERCODE_LOCAL_CONFIG": str(local),
                "OLIVERCODE_ARCHIVED": "off", "OLIVERCODE_GH_POINTS_FLOOR": "0"})
    env.update(_fill(sc.get("env") or {}, ctx))
    return ctx, env


def _hook_verdict(sc: dict, ctx: dict, env: dict) -> tuple[str, str]:
    payload = json.dumps(_fill(sc["payload"], ctx))
    ran = subprocess.run([sys.executable, str(HOOKS / sc["entry"])], input=payload, capture_output=True, text=True,
                         env=env, cwd=ctx["tmp"], timeout=60)
    if ran.returncode or not ran.stdout.strip():
        return ("error" if ran.returncode else "allow"), ran.stderr
    out = json.loads(ran.stdout)["hookSpecificOutput"]
    return out.get("permissionDecision", "allow"), out.get("permissionDecisionReason", "")  # advice alone is an allow


def _commit_msg_verdict(sc: dict, ctx: dict, env: dict) -> tuple[str, str]:
    """The commit-msg gate in a repo with its history and staged files. Exit 0 is allow and exit 1 is deny."""
    repo = Path(ctx["repo"])
    shutil.copy2(TEMPLATES / "commit-msg", repo / ".githooks" / "commit-msg")
    if sc.get("history") is False:
        shutil.rmtree(repo / ".git")
        _git(repo, "init", "-q")
    for name, content in (sc.get("stage") or {}).items():
        _write(repo / name, _fill(content, ctx))
    if sc.get("stage"):
        _git(repo, "add", "--", *sc["stage"])
    msg = Path(ctx["tmp"]) / "MSG"
    msg.write_text(_fill(sc["message"], ctx), encoding="utf-8")
    ran = subprocess.run(["bash", str(repo / ".githooks" / "commit-msg"), str(msg)], capture_output=True, text=True,
                         env=env, cwd=repo, timeout=60)
    return ("allow" if ran.returncode == 0 else "deny"), ran.stdout + ran.stderr


def run_scenario(sc: dict, templates: dict[str, Path]) -> str:
    """One mismatch line, or '' when the verdict and the reason match."""
    with tempfile.TemporaryDirectory(prefix="olivercode-eval-") as tmp:
        try:
            ctx, env = _setup(sc, Path(tmp), templates)
            verdict, reason = (_commit_msg_verdict if sc["entry"] == "commit-msg" else _hook_verdict)(sc, ctx, env)
        except Exception as exc:  # noqa: BLE001 -- a scenario that cannot run is a mismatch, never a crash of the others
            return f"{sc['guard']}: {sc['name']}: could not run ({type(exc).__name__}: {exc})"
    if verdict != sc["expect"]:
        return f"{sc['guard']}: {sc['name']}: expected {sc['expect']}, got {verdict}" + (f" ({reason.strip()[:120]})" if reason.strip() else "")
    if sc.get("reason") and sc["reason"] not in reason:
        return f"{sc['guard']}: {sc['name']}: the reason lacks {sc['reason']!r}: {reason.strip()[:120]!r}"
    if verdict in ("deny", "ask") and reason.strip() and sc["entry"] != "commit-msg":  # the commit-message gate is story #881's
        message = reason.strip()
        if len(message) > MESSAGE_LIMIT:
            return f"{sc['guard']}: {sc['name']}: the message is {len(message)} characters, over {MESSAGE_LIMIT}"
        if "docs/" not in message:
            return f"{sc['guard']}: {sc['name']}: the message names no docs/ section"
    return ""


def run_offline(scenarios: list[dict]) -> list[str]:
    """Every mismatch, in scenario order."""
    if not scenarios:
        return []
    if any(sc["entry"] == "commit-msg" for sc in scenarios):
        subprocess.run([sys.executable, str(OC_ROOT / "scripts" / "build-hooks.py")], check=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix="olivercode-eval-templates-") as tmp:
        templates = {}
        for kind in ("gated", "unhooked", "plain"):
            templates[kind] = Path(tmp) / kind
            _template_repo(templates[kind], kind)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            lines = list(pool.map(lambda sc: run_scenario(sc, templates), scenarios))
    return [line for line in lines if line]


def command_eval(argv: list[str]) -> int:
    rest = list(argv)
    guard = None
    if rest[:1] == ["--guard"] and len(rest) == 2:
        guard = rest[1]
    elif rest:
        print("Usage: olivercode eval [--guard NAME]")
        return 1
    if guard and guard not in guards():
        print(f"Error: no scenarios for {guard}. Known guards: {', '.join(guards())}.")
        return 1
    started = time.time()
    scenarios = load(guard)
    lines = run_offline(scenarios)
    total = len(scenarios)
    for line in lines:
        print(f"MISMATCH {line}")
    print(f"{total - len(lines)} of {total} scenarios match ({time.time() - started:.1f}s).")
    return 1 if lines else 0
