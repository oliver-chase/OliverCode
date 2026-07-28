"""Tests for the fleet-name leak check.

The three-layer design keeps real fleet data in gitignored `local/` so the framework
stays shareable. The registries honoured that from the start and the leak came through
prose instead: BACKLOG entries naming the repos that needed a re-sync, and one real repo
name used as a test fixture. Neither the reference gate nor the PII gate could see it,
because both look for paths and email addresses and a bare repo name is neither.

The check derives the names to look for from the operator's own gitignored profile, so
there is no hardcoded list of what to hide. A hardcoded list would be the leak.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "cc", REPO_ROOT / "scripts" / "lib" / "consistency_check.py"
)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

FLEET = ("acme-api", "acme-web")


def _sandbox(dest: Path, profiles: dict | None, extra: str = "") -> Path:
    """A tracked-file copy of this repo, with a synthetic local/ fleet config."""
    dest.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.split("\0")
    for rel in filter(None, listing):
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(src.read_bytes())
    if extra:
        (dest / "docs" / "BACKLOG.md").write_text(
            (dest / "docs" / "BACKLOG.md").read_text() + extra, encoding="utf-8"
        )
    if profiles is not None:
        (dest / "local").mkdir(exist_ok=True)
        (dest / "local" / "repo-profiles.json").write_text(
            json.dumps({"profiles": profiles}), encoding="utf-8"
        )
    subprocess.run(["git", "init", "-q", "."], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, capture_output=True, check=True)
    return dest


class TestFleetLeak(unittest.TestCase):
    def test_shipped_tree_is_clean(self):
        self.assertEqual(cc.check_no_fleet_names_in_tracked_files(REPO_ROOT), [])

    def test_catches_a_real_repo_name_in_a_tracked_doc(self):
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(
                Path(tmp) / "oc",
                {n: {} for n in FLEET},
                extra="\n\nRe-sync acme-api next week.\n",
            )
            found = cc.check_no_fleet_names_in_tracked_files(work)
            self.assertTrue(found, "a real fleet name in a tracked doc was not caught")
            self.assertIn("acme-api", found[0])

    def test_a_fork_without_local_config_skips(self):
        """No local/ and no sibling repos means no names to compare — must not fail.

        (The sandbox's parent holds only the copy itself, so sibling detection
        contributes nothing here; the sibling case has its own test below.)"""
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "oc", None, extra="\n\nRe-sync acme-api next week.\n")
            self.assertEqual(cc.check_no_fleet_names_in_tracked_files(work), [])

    def test_the_framework_repo_name_is_not_fleet_data(self):
        """OliverCode names itself constantly; that is not a leak."""
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "oc", {"OliverCode": {}, "olivercode": {}})
            self.assertEqual(cc.check_no_fleet_names_in_tracked_files(work), [])

    def test_a_name_colliding_with_the_repo_vocabulary_does_not_flag_everything(self):
        """A profile named after a directory in this repo must not fire on every file.

        First cut used only a length guard, so a profile named "core" produced 86
        findings across the tree. A check that noisy gets switched off, which is the
        failure mode falsifiability_check.py exists to prevent.
        """
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "oc", {"core": {}, "docs": {}, "scripts": {}})
            self.assertEqual(cc.check_no_fleet_names_in_tracked_files(work), [])

    def test_a_reserved_name_does_not_suppress_a_real_one(self):
        """Skipping an unsearchable name must not disable the check for the others."""
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(
                Path(tmp) / "oc", {"core": {}, "acme-api": {}},
                extra="\n\nRe-sync acme-api next week.\n",
            )
            found = cc.check_no_fleet_names_in_tracked_files(work)
            self.assertTrue(found)
            self.assertTrue(all("acme-api" in f for f in found))


    def test_placeholder_names_from_the_tracked_example_are_not_leaks(self):
        """`init` seeds local/ from the tracked example, so a fresh fork's whole
        "fleet" is placeholders that are supposed to appear in tracked files. Treating
        them as real broke the fork-usability sandbox."""
        example = json.loads(
            (REPO_ROOT / "shared" / "repo-profiles.example.json").read_text(encoding="utf-8")
        )["profiles"]
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "oc", example)
            self.assertEqual(cc.check_no_fleet_names_in_tracked_files(work), [])


    def test_a_sibling_repo_name_is_caught_without_registration(self):
        """The operator's projects leak by name whether or not they are registered
        fleet. A contract shipped naming an unregistered sibling three times and the
        profiles-only gate never fired. Names now also derive from sibling git repos."""
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "parent" / "oc", None,
                            extra="\n\nReference implementation lives in acme-crawl.\n")
            sib = work.parent / "acme-crawl"
            (sib / ".git").mkdir(parents=True)
            found = cc.check_no_fleet_names_in_tracked_files(work)
            self.assertTrue(found, "unregistered sibling repo name was not caught")
            self.assertIn("acme-crawl", found[0])


    def test_a_leak_in_an_extensionless_or_yml_file_is_caught(self):
        """The hooks have no extension and workflows are .yml; an extension-list scan
        skipped both, so a name there shipped to every fork unexamined."""
        with tempfile.TemporaryDirectory(prefix="olivercode-leak-") as tmp:
            work = _sandbox(Path(tmp) / "oc", {"acme-api": {}})
            hook = work / ".githooks" / "pre-commit"
            hook.write_text(hook.read_text() + "\n# acme-api needs re-sync\n")
            subprocess.run(["git", "add", "-A"], cwd=work, capture_output=True, check=True)
            found = cc.check_no_fleet_names_in_tracked_files(work)
            self.assertTrue(found, "leak in an extensionless tracked file was not caught")
            self.assertIn(".githooks/pre-commit", found[0])


if __name__ == "__main__":
    unittest.main()
