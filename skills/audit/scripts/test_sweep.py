import subprocess
import tempfile
import unittest
from pathlib import Path

import sweep


def git_repo(files):
    root = Path(tempfile.mkdtemp())
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

    def test_flags_an_orphan_whose_stem_is_an_everyday_word(self):
        root = git_repo({
            "scripts/word.py": "x = 1\n",
            "scripts/used.py": "x = 1\n",
            "scripts/run.sh": "python3 used.py\n",
            "README.md": "Count the word total. Run scripts/run.sh.\n",
        })
        orphans = {w for k, w, _ in sweep.sweep(root) if k == "orphan"}
        self.assertEqual(orphans, {"scripts/word.py"})


if __name__ == "__main__":
    unittest.main()
