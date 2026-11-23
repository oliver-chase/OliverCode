import atexit
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sweep


def git_repo(files):
    root = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, root, True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


class SweepTest(unittest.TestCase):
    def test_flags_unused_and_test_only_and_oversized(self):
        root = git_repo({
            "scripts/lib/a.py": "def used():\n    pass\n\ndef dead():\n    pass\n\ndef only_tested():\n    pass\n",
            "scripts/lib/b.py": "from a import used\nused()\n" + "x = 1\n" * 401,
            "tests/test_a.py": "from a import only_tested\nonly_tested()\n",
        })
        rows = {(k, d) for k, _, d in sweep.sweep(root)}
        self.assertIn(("unused-def", "dead"), rows)
        self.assertIn(("test-only", "only_tested"), rows)
        self.assertNotIn(("unused-def", "used"), rows)
        self.assertTrue(any(k == "oversized" for k, _, _ in sweep.sweep(root)))

    def test_a_name_that_ends_another_name_does_not_rescue_an_orphan(self):
        root = git_repo({"scripts/check.py": "x = 1\n", "scripts/run_check.py": "x = 1\n", "README.md": "Run scripts/run_check.py daily.\n"})
        orphans = {w for k, w, _ in sweep.sweep(root) if k == "orphan"}
        self.assertEqual(orphans, {"scripts/check.py"})

    def test_a_def_named_only_in_prose_or_async_is_still_flagged(self):
        root = git_repo({"scripts/lib/m.py": "def helper_in_docs():\n    pass\n\nasync def run_loop():\n    pass\n",
                         "docs/notes.md": "Call helper_in_docs and run_loop.\n"})
        self.assertEqual({"helper_in_docs", "run_loop"}, {d for k, _, d in sweep.sweep(root) if k == "unused-def"})

    def test_a_module_named_only_by_an_import_is_not_an_orphan_and_production_use_is_not_test_only(self):
        root = git_repo({"scripts/lib/m.py": "def shared():\n    pass\n", "scripts/lib/n.py": "from m import shared\nshared()\n",
                         "tests/test_m.py": "from m import shared\nshared()\n", "README.md": "See scripts/lib/n.py.\n"})
        rows = sweep.sweep(root)
        self.assertEqual([], [r for r in rows if r[0] in ("orphan", "test-only", "unused-def") and "m.py" in r[1]])

    def test_a_def_used_only_inside_its_own_file_and_a_package_import_are_not_flagged(self):
        root = git_repo({"scripts/pkg/m.py": "def helper():\n    pass\n\ndef top():\n    helper()\n    return 1\n",
                         "scripts/pkg/n.py": "from scripts.pkg.m import top\ntop()\n"})
        self.assertEqual([], [r for r in sweep.sweep(root) if r[0] in ("unused-def", "orphan") and "m.py" in r[1]])

    def test_a_module_imported_only_by_an_extensionless_launcher_is_not_an_orphan(self):
        root = git_repo({"scripts/olivercode": "#!/usr/bin/env python3\nfrom lib.cmd_x import run\nfrom lib import cmd_y, cmd_z\n",
                         "scripts/lib/cmd_x.py": "x = 1\n", "scripts/lib/cmd_y.py": "x = 1\n", "scripts/lib/cmd_z.py": "x = 1\n"})
        self.assertEqual([], [w for k, w, _ in sweep.sweep(root) if k == "orphan"])

    def test_flags_an_orphan_whose_stem_is_an_everyday_word(self):
        root = git_repo({
            "scripts/word.py": "x = 1\n",
            "scripts/used.py": "x = 1\n",
            "scripts/run.sh": "python3 used.py\n",
            "README.md": "Count the word total. Start from word templates. Run scripts/run.sh.\n",
        })
        orphans = {w for k, w, _ in sweep.sweep(root) if k == "orphan"}
        self.assertEqual(orphans, {"scripts/word.py"})
