"""Fixture tests for check_dead_code.py: an unused import, an unreferenced function and an uncited
skill file fail. A used or re-exported import, a name another file uses and a cited file do not.

Run from this scripts/ folder: python3 -m unittest test_check_dead_code
"""
import tempfile
import unittest
from pathlib import Path

import check_dead_code as dc


def make(root, files):
    for rel, text in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class Fleet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make(self.root, {
            "fam/alpha/SKILL.md": "---\nname: alpha\n---\nRun `scripts/main.py`.\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def imports(self):
        return [(str(p), name) for p, _n, name in dc.find_unused_imports(dc.read_all(self.root))]

    def defs(self):
        return [name for _p, _n, name in dc.find_unreferenced_defs(dc.read_all(self.root))]

    def files(self):
        return [str(p) for _s, p in dc.find_unreferenced_files(self.root, dc.read_all(self.root))]


class Tracked(unittest.TestCase):
    def test_a_tracked_file_deleted_from_disk_is_not_read(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {"keep.md": "x\n", "gone.md": "y\n"})
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            (Path(tmp) / "gone.md").unlink()
            self.assertEqual([str(p) for p in dc.tracked(tmp)], ["keep.md"])


class Imports(Fleet):
    def test_an_unused_import_fails(self):
        make(self.root, {"fam/alpha/scripts/main.py": "import os\nprint(1)\n"})
        self.assertEqual(self.imports(), [("fam/alpha/scripts/main.py", "os")])

    def test_a_used_import_passes(self):
        make(self.root, {"fam/alpha/scripts/main.py": "import os\nprint(os.sep)\n"})
        self.assertEqual(self.imports(), [])

    def test_an_import_another_file_reads_as_an_attribute_passes(self):
        make(self.root, {"fam/alpha/scripts/main.py": "from base import ROOT\n",
                         "fam/alpha/scripts/use.py": "import main\nprint(main.ROOT)\n"})
        self.assertEqual(self.imports(), [])

    def test_a_try_import_a_noqa_line_and_a_test_file_are_skipped(self):
        make(self.root, {"fam/alpha/scripts/main.py": "try:\n    import yaml\nexcept ImportError:\n    yaml = None\nimport sys  # noqa\n",
                         "fam/alpha/scripts/test_main.py": "import os\n"})
        self.assertEqual(self.imports(), [])


class Defs(Fleet):
    def test_a_function_nothing_names_fails(self):
        make(self.root, {"fam/alpha/scripts/main.py": "def lonely():\n    return 1\n"})
        self.assertEqual(self.defs(), ["lonely"])

    def test_a_function_only_a_test_calls_still_fails(self):
        make(self.root, {"fam/alpha/scripts/main.py": "def helper():\n    return 1\n",
                         "fam/alpha/scripts/test_main.py": "from main import helper\nhelper()\n"})
        self.assertEqual(self.defs(), ["helper"])

    def test_a_function_another_script_or_doc_names_passes(self):
        make(self.root, {"fam/alpha/scripts/main.py": "def used():\n    return 1\n\ndef documented():\n    return 2\n",
                         "fam/alpha/scripts/other.py": "from main import used\nused()\n",
                         "fam/alpha/references/notes.md": "Call `documented` first.\n"})
        self.assertEqual(self.defs(), [])

    def test_a_skill_directly_under_the_root_is_scanned(self):
        make(self.root, {"solo/SKILL.md": "---\nname: solo\n---\n", "solo/references/old.md": "Old.\n"})
        self.assertEqual(self.files(), ["references/old.md"])


class Files(Fleet):
    def test_a_file_nothing_cites_fails(self):
        make(self.root, {"fam/alpha/references/old.md": "Old notes.\n"})
        self.assertEqual(self.files(), ["references/old.md"])

    def test_a_file_cited_by_stem_passes(self):
        make(self.root, {"fam/alpha/scripts/main.py": "import helper\n", "fam/alpha/scripts/helper.py": "X = 1\n"})
        self.assertEqual(self.files(), [])

    def test_a_sample_file_is_cited_by_its_folder(self):
        make(self.root, {"fam/alpha/SKILL.md": "See `example/...`.\n", "fam/alpha/example/Sheet.md": "Sample.\n"})
        self.assertEqual(self.files(), [])


if __name__ == "__main__":
    unittest.main()
