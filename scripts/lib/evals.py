"""Replayable tasks, a runner and a before-and-after comparison for judging a rule or skill change.

A task is a JSON file in tasks/ with an id, a prompt, the files of a starting state and a shell check
that passes with exit 0. The runner builds each starting state in a scratch folder, hands the prompt to an
agent command, runs the check and records pass or fail, gate blocks and cost to a results file.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from lib import failure_log
from lib.local_config import OC_ROOT

TASKS_DIR = OC_ROOT / "tasks"
REQUIRED = {"id": str, "description": str, "files": dict, "prompt": str, "check": str}
PRIVATE = re.compile(r"/Users/|/home/\w|@\w+\.\w")
DEFAULT_AGENT = "claude -p --output-format json"


def load_task(path: Path) -> dict:
    """A validated task. Raises ValueError naming the file and the problem."""
    task = json.loads(path.read_text(encoding="utf-8"))
    for name, kind in REQUIRED.items():
        if not isinstance(task.get(name), kind) or not task[name]:
            raise ValueError(f"{path.name}: `{name}` must be a non-empty {kind.__name__}")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in task["files"].items()):
        raise ValueError(f"{path.name}: `files` must map file names to text")
    if PRIVATE.search(json.dumps(task)):
        raise ValueError(f"{path.name}: names a private path or address")
    return task


def load_set(folder: Path = TASKS_DIR) -> list[dict]:
    return [load_task(p) for p in sorted(folder.glob("*.json"))]


def run_task(task: dict, agent: str) -> dict:
    """Run one task in a scratch folder. cost_usd is None when the agent reports none."""
    before = len(failure_log.entries())
    with tempfile.TemporaryDirectory(prefix="olivercode-eval-") as tmp:
        root = Path(tmp)
        for name, text in task["files"].items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        cost = None
        try:
            ran = subprocess.run([*shlex.split(agent), task["prompt"]], cwd=root, capture_output=True, text=True, timeout=1800)
            try:
                cost = json.loads(ran.stdout).get("total_cost_usd")
            except (ValueError, AttributeError):
                pass
        except (OSError, subprocess.TimeoutExpired):
            pass
        passed = subprocess.run(["bash", "-c", task["check"]], cwd=root, capture_output=True).returncode == 0
    return {"id": task["id"], "passed": passed, "gate_blocks": len(failure_log.entries()) - before, "cost_usd": cost}


def summarize(results: list[dict]) -> dict:
    costs = [r["cost_usd"] for r in results if r["cost_usd"] is not None]
    return {
        "pass_rate": round(sum(r["passed"] for r in results) / len(results), 3) if results else 0,
        "gate_blocks": sum(r["gate_blocks"] for r in results),
        "cost_usd": round(sum(costs), 4) if len(costs) == len(results) and results else "not measured",
    }


def compare(before: dict, after: dict) -> dict:
    """Both results files, side by side. Raises ValueError naming the tasks missing from either side."""
    b = {r["id"]: r for r in before["tasks"]}
    a = {r["id"]: r for r in after["tasks"]}
    if set(a) != set(b):
        raise ValueError("the sets differ. Missing from the after run: " + (", ".join(sorted(set(b) - set(a))) or "none")
                         + ". Missing from the before run: " + (", ".join(sorted(set(a) - set(b))) or "none"))
    changed = sorted(i for i in b if b[i]["passed"] != a[i]["passed"])
    return {"before": summarize(list(b.values())), "after": summarize(list(a.values())), "changed": changed,
            "regressed": [i for i in changed if b[i]["passed"]]}


def _take(argv: list[str], flag: str) -> tuple[str | None, list[str]]:
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1], argv[:i] + argv[i + 2:]
    return None, argv


def command_eval(argv: list[str]) -> int:
    usage = "Usage: olivercode eval list | run [--set DIR] [--agent CMD] --out FILE | compare BEFORE AFTER [--out FILE]"
    if not argv:
        print(usage)
        return 1
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        try:
            tasks = load_set()
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        for t in tasks:
            print(f"{t['id']}: {t['description']}")
        return 0
    if sub == "run":
        folder, rest = _take(rest, "--set")
        agent, rest = _take(rest, "--agent")
        out, rest = _take(rest, "--out")
        if out is None or rest:
            print(usage)
            return 1
        try:
            tasks = load_set(Path(folder) if folder else TASKS_DIR)
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        results = [run_task(t, agent or DEFAULT_AGENT) for t in tasks]
        summary = summarize(results)
        Path(out).write_text(json.dumps({"tasks": results, **summary}, indent=2) + "\n", encoding="utf-8")
        for r in results:
            print(f"  {'PASS' if r['passed'] else 'FAIL'} {r['id']}")
        cost = summary["cost_usd"]
        print(f"pass rate {summary['pass_rate']}, gate blocks {summary['gate_blocks']}, cost {cost if cost == 'not measured' else '$' + str(cost)}")
        return 0
    if sub == "compare":
        out, rest = _take(rest, "--out")
        if len(rest) != 2:
            print(usage)
            return 1
        try:
            result = compare(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in rest))
        except ValueError as e:
            print(f"Stopped: {e}")
            return 1
        for label in ("before", "after"):
            s = result[label]
            print(f"{label}: pass rate {s['pass_rate']}, gate blocks {s['gate_blocks']}, cost {s['cost_usd']}")
        print("changed: " + (", ".join(result["changed"]) or "no task"))
        if out:
            Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0
    print(usage)
    return 1
