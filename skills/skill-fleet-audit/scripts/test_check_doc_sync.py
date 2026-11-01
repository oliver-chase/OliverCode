"""Fixture tests for check_doc_sync.py: a skill with no README row, a stale README row, and a
missing or misresolving symlink each go red; a fully synced fixture goes green. The dependency-graph
section is not read as skill rows. README and symlink roots are pointed at a temp folder, so no real
vault or home folder is read.

Run from this scripts/ folder: python3 -m unittest test_check_doc_sync
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_doc_sync as ds

SKILL = "---\nname: x\ndescription: d\n---\n"


def run_gate(skills, readme="", links="all", scoped=None, readme_present=True):
    """skills: names (each a fam/<name>/SKILL.md). links: 'all' links each skill, 'none' links
    nothing, or a dict name -> target name for a misresolving link."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        fleet = tmp / "fleet"
        for n in skills:
            (fleet / "fam" / n).mkdir(parents=True)
            (fleet / "fam" / n / "SKILL.md").write_text(SKILL)
        (fleet / "fam" / "other").mkdir(parents=True, exist_ok=True)
        sym = tmp / "links"
        sym.mkdir()
        if links == "all":
            for n in skills:
                (sym / n).symlink_to(fleet / "fam" / n)
        elif isinstance(links, dict):
            for n, target in links.items():
                (sym / n).symlink_to(fleet / "fam" / target)
        readme_file = tmp / "README.md"
        if readme_present:
            readme_file.write_text(readme)
        saved = (ds.SKILLS_ROOT, ds.FLEET_ROOT, ds.README_FILE, ds.SYMLINK_ROOT)
        ds.SKILLS_ROOT = scoped(fleet) if scoped else fleet
        ds.FLEET_ROOT, ds.README_FILE, ds.SYMLINK_ROOT = fleet, readme_file, sym
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                try:
                    ds.main([])
                    code = 0
                except SystemExit as e:
                    code = e.code
        finally:
            ds.SKILLS_ROOT, ds.FLEET_ROOT, ds.README_FILE, ds.SYMLINK_ROOT = saved
    return code, out.getvalue()


ROW = "| `alpha` | Does work |\n"


class DocSync(unittest.TestCase):
    def test_synced_fixture_is_green(self):
        code, out = run_gate(["alpha"], readme=ROW)
        self.assertEqual(code, 0, out)
        self.assertIn("Doc-sync clean", out)

    def test_missing_readme_row_goes_red(self):
        code, out = run_gate(["alpha"], readme="")
        self.assertEqual(code, 1, out)
        self.assertIn("alpha: on disk, no `alpha` table row", out)

    def test_stale_readme_row_goes_red(self):
        code, out = run_gate(["alpha"], readme=ROW + "| `ghost` | gone |\n")
        self.assertEqual(code, 1, out)
        self.assertIn("README.md names `ghost`", out)

    def test_stale_row_ignored_on_scoped_run(self):
        code, out = run_gate(["alpha"], readme=ROW + "| `ghost` | gone |\n",
                             scoped=lambda f: f / "fam")
        self.assertEqual(code, 0, out)

    def test_dependency_graph_rows_are_not_skills(self):
        readme = ROW + "\n## Dependency graph\n\n| `fam` | needs x |\n\n## Next\n"
        code, out = run_gate(["alpha"], readme=readme)
        self.assertEqual(code, 0, out)

    def test_dependency_model_rows_are_not_skills(self):
        readme = ROW + "\n## Dependency model\n\n| `fam` | needs x |\n\n## Next\n"
        code, out = run_gate(["alpha"], readme=readme)
        self.assertEqual(code, 0, out)

    def test_row_after_dependency_graph_section_counts(self):
        readme = "## Dependency graph\n| `fam` | x |\n\n## Skills\n" + ROW
        code, out = run_gate(["alpha"], readme=readme)
        self.assertEqual(code, 0, out)

    def test_missing_symlink_goes_red(self):
        code, out = run_gate(["alpha"], readme=ROW, links="none")
        self.assertEqual(code, 1, out)
        self.assertIn("alpha: no symlink", out)

    def test_misresolving_symlink_goes_red(self):
        code, out = run_gate(["alpha", "beta"], readme=ROW + "| `beta` | x |\n",
                             links={"alpha": "beta", "beta": "beta"})
        self.assertEqual(code, 1, out)
        self.assertIn("alpha: ", out)
        self.assertIn("resolves to", out)

    def test_missing_readme_is_skipped_not_failed(self):
        code, out = run_gate(["alpha"], readme_present=False)
        self.assertEqual(code, 0, out)
        self.assertIn("skipping README-row check", out)


if __name__ == "__main__":
    unittest.main()
