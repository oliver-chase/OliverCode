import unittest

import catalog
from test_sweep import git_repo


class CatalogTest(unittest.TestCase):
    def test_reads_job_and_usage_from_python_shell_and_skill(self):
        self.assertEqual(catalog.script_info('#!/usr/bin/env python3\n"""Does a thing well. More.\n\nUsage:\n    run.py [repo]\n"""\n', ".py"),
                         ("Does a thing well.", "run.py [repo]"))
        self.assertEqual(catalog.script_info("#!/bin/bash\n# scripts/x.sh - Checks the thing.\n# More detail.\nset -e\n", ".sh")[0], "Checks the thing.")
        self.assertEqual(catalog.skill_info('---\nname: a\ndescription: "Does X. Trigger on y."\n---\n'), "Does X.")

    def test_a_script_with_no_docstring_gets_no_job_from_later_text(self):
        text = '#!/usr/bin/env python3\n# a comment\nimport os\nx = """not the module docstring."""\n'
        self.assertEqual("", catalog.script_info(text, ".py")[0])

    def test_check_flags_missing_description_and_stale_catalog_then_write_fixes_it(self):
        root = git_repo({"skills/a/SKILL.md": '---\nname: a\ndescription: "Does X."\n---\n',
                         "scripts/run.py": '"""Runs it."""\n', "scripts/bare.py": "x = 1\n", "config/c.json": '{"_comment": "Settings."}\n'})
        problems = catalog.check(root)
        self.assertTrue(any("bare.py has no description" in p for p in problems))
        self.assertTrue(any("missing or stale" in p for p in problems))
        (root / "scripts/bare.py").write_text('"""Bare."""\n')
        catalog.main(["catalog.py", str(root), "--write"])
        self.assertEqual(catalog.check(root), [])
        (root / "scripts/run.py").write_text('"""Changed job."""\n')
        self.assertTrue(any("stale" in p for p in catalog.check(root)))

    def test_tests_and_lockfiles_are_not_parts(self):
        rows = catalog.entries(git_repo({"tests/test_a.py": "x = 1\n", "package-lock.json": "{}\n"}))
        self.assertEqual(sum(len(v) for v in rows.values()), 0)


if __name__ == "__main__":
    unittest.main()
