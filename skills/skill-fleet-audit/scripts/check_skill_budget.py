#!/usr/bin/env python3
"""SKILL-BUDGET-1: fails when a budgeted skill carries more words than its budget.

A skill that grows by thousands of words with no step loading them costs every session that loads
it, and nothing else flags the jump. A skill opts in with a row in the fleet's `.fleet-audit/skill-budgets.json`.
The count is every word in the skill folder's text files, tests excluded.

A skill with no row is not checked. A row for a skill that is not in the fleet fails, so a deleted
skill leaves no stale number. To raise a budget, edit the row in the same commit that adds the words.

Usage:
    check_skill_budget.py            # check every budgeted skill
    check_skill_budget.py --measure  # print each skill's words and a budget 10% above it, to paste
Exit 1 on any finding.
Tests: python3 -m unittest test_check_skill_budget   (from this scripts/ folder)
"""
import json
import math
import sys
from pathlib import Path

import _fleet

BUDGET_FILE = _fleet.fleet_data("skill-budgets.json")
TEXT_SUFFIXES = {".md", ".json", ".py", ".js", ".jsx", ".sh", ".txt", ".html", ".yml", ".yaml", ".example"}
SKIP_DIRS = {"__pycache__", "node_modules", "vendor", ".pytest_cache", "tests"}
HEADROOM = 1.10


def shipped_words(folder):
    total = 0
    for path in Path(folder).rglob("*"):
        rel = path.relative_to(folder)
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not SKIP_DIRS & set(rel.parts) and not path.name.startswith("test_"):
            total += len(path.read_text(encoding="utf-8", errors="ignore").split())
    return total


def suggested(words):
    return math.ceil(words * HEADROOM / 100) * 100


def load_budgets(path=BUDGET_FILE):
    return json.loads(_fleet.read_fleet_data(path))["skills"]


def find_problems(root, budgets):
    skills = {folder.name: folder for folder in _fleet.find_skills(Path(root))}
    problems = []
    for name, limit in sorted(budgets.items()):
        if name not in skills:
            problems.append(f"{name} has a budget row and is not in the fleet; delete the row")
            continue
        words = shipped_words(skills[name])
        if words > limit:
            problems.append(f"{name} carries {words} words, over its budget of {limit}. Cut the words, or raise the row in the same commit")
    return problems


def main():
    if "--measure" in sys.argv[1:]:
        rows = {folder.name: suggested(shipped_words(folder)) for folder in _fleet.find_skills(_fleet.FLEET_ROOT)}
        print(json.dumps({"skills": dict(sorted(rows.items()))}, indent=2))
        return 0
    problems = find_problems(_fleet.FLEET_ROOT, load_budgets())
    for line in problems:
        print(" -", line)
    print(f"{len(problems)} skill budget finding(s)." if problems else "Every budgeted skill is within its word budget.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
