"""Tests for check_readme_facts.py. Run: python3 -m unittest test_check_readme_facts"""
import tempfile
import unittest
from pathlib import Path

import check_readme_facts as C

README = """# Fleet

```text
skills/
├── alpha/
│   └── alpha-tool/
└── beta/
```

## Dependency model

| Folder | Runtime dependency | Notes |
|---|---|---|
| `alpha` | None | |
| `beta` | `alpha` | |

Alpha reads `scripts/tool.py` and the `docs/` folder.
"""


def build(readme=README, requires="alpha\n", extra=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "alpha" / "alpha-tool" / "scripts").mkdir(parents=True)
    (root / "alpha" / "alpha-tool" / "scripts" / "tool.py").write_text("x", encoding="utf-8")
    (root / "beta").mkdir(parents=True)
    (root / "beta" / "_REQUIRES").write_text(requires, encoding="utf-8")
    (root / "docs").mkdir()
    for rel, text in (extra or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp, root


class ReadmeFacts(unittest.TestCase):
    def test_clean_readme_passes(self):
        tmp, root = build()
        self.assertEqual(C.check(root), [])

    def test_folder_missing_from_tree_goes_red(self):
        tmp, root = build(extra={"gamma/x.txt": "x"})
        self.assertTrue(any("gamma/ is on disk" in p for p in C.check(root)))

    def test_tree_entry_without_folder_goes_red(self):
        tmp, root = build(readme=README.replace("└── beta/", "├── beta/\n└── ghost/"))
        self.assertTrue(any("lists ghost/" in p for p in C.check(root)))

    def test_a_readme_with_no_tree_skips_the_tree_check(self):
        tmp, root = build(readme=README.split("```text")[0] + "## Dependency model\n", extra={"gamma/x.txt": "x"})
        self.assertEqual(C.check(root), [])

    def test_dependency_that_files_do_not_declare_goes_red(self):
        tmp, root = build(requires="")
        self.assertTrue(any(p.startswith("beta:") for p in C.check(root)))

    def test_dependency_row_without_a_folder_goes_red(self):
        tmp, root = build(readme=README + "\n| `ghost` | None | |\n")
        self.assertTrue(any("row ghost has no folder" in p for p in C.check(root)))

    def test_missing_path_goes_red(self):
        tmp, root = build(readme=README + "\nSee `scripts/ghost.py`.\n")
        self.assertTrue(any("scripts/ghost.py" in p for p in C.check(root)))

    def test_file_in_another_repository_is_skipped(self):
        tmp, root = build(readme=README + "\nAdd a section to each repository's `CLAUDE.md`.\n")
        self.assertEqual(C.check(root), [])

    def test_code_block_and_placeholder_names_are_skipped(self):
        readme = README + "\n```bash\npython3 scripts/ghost.py\n```\n\nUse `<family>/x.md` or `.env.local`.\n"
        tmp, root = build(readme=readme)
        self.assertEqual(C.check(root), [])


class Main(unittest.TestCase):
    def test_a_folder_with_no_readme_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(C.main([tmp]), 0)


if __name__ == "__main__":
    unittest.main()
