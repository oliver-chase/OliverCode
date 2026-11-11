"""Tests for check_skill_structure.py: the weight pass (SKILL-WEIGHT-1) and the two findings
dangling-skill-reference and dangling-file-reference.

Run from this scripts/ folder: python3 -m unittest test_check_skill_structure
Each test builds a fixture in a temp folder. The weight fixture holds one referenced file,
one unreferenced reference, one called script, and one uncalled script. The finding tests run
the script as a subprocess on a fixture fleet: a bad fixture exits 1 with the finding, a clean
one exits 0.
"""

import subprocess
import sys
import tempfile
import contextlib
import io
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_skill_structure as C  # noqa: E402


def make_skill(root, *, extra=None):
    skill = Path(root) / "fixture-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: >\n  Builds a fixture. Two words more.\n---\n\n"
        "Load `references/used.md`. Run `scripts/used.py`.\n", encoding="utf-8")
    (skill / "references" / "used.md").write_text("Used by a step.\n", encoding="utf-8")
    (skill / "scripts" / "used.py").write_text("print('used')\n", encoding="utf-8")
    if extra is None or "orphan" in extra:
        (skill / "references" / "orphan.md").write_text("No step loads this.\n", encoding="utf-8")
    if extra is None or "uncalled" in extra:
        (skill / "scripts" / "uncalled.py").write_text("print('nothing runs this')\n", encoding="utf-8")
    return skill


class RouteRows(unittest.TestCase):
    def test_a_row_adds_up_the_files_it_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "references" / "big.md").write_text("word " * 30, encoding="utf-8")
            (skill / "SKILL.md").write_text("---\nname: fixture-skill\n---\n| Task | Load |\n|---|---|\n"
                                           "| Build it | `references/used.md`, `references/big.md` |\n", encoding="utf-8")
            rows = C.route_rows(skill)
        self.assertEqual(rows, [(34, ["references/used.md", "references/big.md"], "Build it")])


class WeightRow(unittest.TestCase):
    def test_bad_fixture_flags_the_orphan_and_the_uncalled_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = C.weight_row(make_skill(tmp))
        self.assertEqual(sorted(row["unref"]), ["references/orphan.md", "scripts/uncalled.py"])
        self.assertEqual(row["uncalled"], ["scripts/uncalled.py"])
        self.assertEqual(row["unloaded"], ["references/orphan.md"])

    def test_a_script_named_only_by_an_import_is_untested(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            tests = skill.parent / "tests" / skill.name
            tests.mkdir(parents=True)
            (tests / "test_smoke.py").write_text("import used\n", encoding="utf-8")
            self.assertEqual(C.weight_row(skill)["untested"], ["scripts/used.py"])
            (tests / "test_smoke.py").write_text("import used\nassert used.run() == 1\n", encoding="utf-8")
            self.assertEqual(C.weight_row(skill)["untested"], [])
            # A module imported under another name is exercised through that name.
            (tests / "test_smoke.py").write_text("import used as U\nassert U.run() == 1\n", encoding="utf-8")
            self.assertEqual(C.weight_row(skill)["untested"], [])
            (tests / "test_smoke.py").write_text("import used as U\n", encoding="utf-8")
            self.assertEqual(C.weight_row(skill)["untested"], ["scripts/used.py"])

    def test_counts_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = C.weight_row(make_skill(tmp, extra=()))
        self.assertEqual(row["files"], 3)
        self.assertEqual(row["desc_words"], 6)
        self.assertGreater(row["skill_lines"], 3)

    def test_script_imported_by_module_stem_is_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "scripts" / "helper.py").write_text("X = 1\n", encoding="utf-8")
            (skill / "scripts" / "used.py").write_text("import helper\n", encoding="utf-8")
            row = C.weight_row(skill)
        self.assertEqual(row["uncalled"], [])

    def test_a_file_loaded_by_folder_pattern_is_named(self):
        # Guards the router that loads `modes/<mode>.md` by pattern from reading as unreferenced.
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "modes").mkdir()
            (skill / "modes" / "extract.md").write_text("Mode.\n", encoding="utf-8")
            (skill / "SKILL.md").write_text(
                (skill / "SKILL.md").read_text(encoding="utf-8") + "Load `modes/<mode>.md` for the ask.\n", encoding="utf-8")
            row = C.weight_row(skill)
        self.assertEqual(row["unref"], [])

    def test_a_component_named_without_its_extension_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "Tile.jsx").write_text("export default 1;\n", encoding="utf-8")
            (skill / "references" / "used.md").write_text("Use the Tile component.\n", encoding="utf-8")
            row = C.weight_row(skill)
        self.assertEqual(row["unref"], [])

    def test_dist_folder_is_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "dist").mkdir()
            (skill / "dist" / "build.zip").write_bytes(b"zip")
            row = C.weight_row(skill)
        self.assertEqual((row["files"], row["unref"]), (3, []))

    def test_exempt_names_never_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            for name in ("README.md", "DECISIONS.md", "test_used.py"):
                (skill / name).write_text("x\n", encoding="utf-8")
            row = C.weight_row(skill)
        self.assertEqual(row["unref"], [])


class WeightTable(unittest.TestCase):
    def test_most_unreferenced_ranks_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            heavy = make_skill(Path(tmp) / "a")
            clean = make_skill(Path(tmp) / "b", extra=())
            saved, C.SKILLS_ROOT = C.SKILLS_ROOT, Path(tmp)
            try:
                rows = C.weight_table([clean, heavy])
            finally:
                C.SKILLS_ROOT = saved
        self.assertEqual([len(r["unref"]) for r in rows], [2, 0])


SCRIPT = Path(__file__).resolve().parent / "check_skill_structure.py"
SKILL_HEAD = "---\nname: {n}\ndescription: Does {n} work.\n---\n\n"


def write_skill(root, rel, body, name=None, refs=None):
    skill = Path(root) / rel
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL_HEAD.format(n=name or skill.name) + body, encoding="utf-8")
    for fname, text in (refs or {}).items():
        (skill / "references").mkdir(exist_ok=True)
        (skill / "references" / fname).write_text(text, encoding="utf-8")
    return skill


def run_gate(root, *flags):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(root), *flags], capture_output=True, text=True)
    return proc.returncode, proc.stdout


class DanglingSkillReferenceFinding(unittest.TestCase):
    def test_reference_to_missing_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "Hand the result to the `ghost-skill-zz` skill.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("[dangling-skill-reference]", out)
        self.assertIn("ghost-skill-zz", out)
        # A single-word skill name is a skill name too.
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "Hand the result to the `ghost` skill.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("ghost", out)

    def test_reference_to_real_sibling_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "Hand the result to the `beta-skill` skill.\n")
            write_skill(tmp, "fam/beta-skill", "Short body.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 0, out)
        self.assertIn("1 in-family", out)

    def test_verb_shape_never_flags_an_unknown_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "Run `force-set` to reset.\n")
            self.assertEqual(run_gate(tmp)[0], 0)


class DescriptionCap(unittest.TestCase):
    def long_skill(self, tmp, words):
        skill = Path(tmp) / "fam" / "wordy-skill"
        skill.mkdir(parents=True)
        desc = " ".join(["word"] * words)
        (skill / "SKILL.md").write_text(f'---\nname: wordy-skill\ndescription: "{desc}"\n---\n\nBody.\n', encoding="utf-8")

    def test_a_151_word_description_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.long_skill(tmp, 151)
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("[description-over-cap]", out)
        self.assertIn("151 words", out)

    def test_a_150_word_description_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.long_skill(tmp, 150)
            code, out = run_gate(tmp)
        self.assertEqual(code, 0, out)


class DanglingFileReferenceFinding(unittest.TestCase):
    SCOPE = "fam/doc-builder"

    def test_reference_to_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, self.SCOPE, "Load `voice-missing.md` first.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("[dangling-file-reference]", out)
        self.assertIn("voice-missing.md", out)

    def test_reference_to_shipped_file_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, self.SCOPE, "Load `voice-core.md` first.\n", refs={"voice-core.md": "Voice.\n"})
            code, out = run_gate(tmp)
        self.assertEqual(code, 0, out)

    def test_every_skill_is_scanned_including_one_directly_under_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "solo-skill", "Load `voice-missing.md` first.\n")
            self.assertEqual(run_gate(tmp)[0], 1)


class FamilyOf(unittest.TestCase):
    def test_a_family_skill_and_a_root_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("fam/a", "solo"):
                (Path(tmp) / rel).mkdir(parents=True)
            saved, C.SKILLS_ROOT = C.SKILLS_ROOT, Path(tmp)
            try:
                self.assertEqual(C.family_of(Path(tmp) / "fam" / "a"), "fam")
                self.assertEqual(C.family_of(Path(tmp) / "solo"), "")
            finally:
                C.SKILLS_ROOT = saved


class ScanOneSkill(unittest.TestCase):
    def test_a_single_skill_folder_scans_without_error(self):
        # Guards family_of() reading an empty path when the scan root is the skill folder itself.
        skill = Path(C.__file__).resolve().parents[1]
        saved = C.SKILLS_ROOT
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    C.main([str(skill)])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
        finally:
            C.SKILLS_ROOT = saved


class FileRefScan(unittest.TestCase):
    """SKILL-FILE-REF-1: a file name must resolve inside the citing skill's own folder."""

    def scan(self, skill_text, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "fam" / "doc"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(skill_text, encoding="utf-8")
            for rel, body in (extra or {}).items():
                (skill / rel).parent.mkdir(parents=True, exist_ok=True)
                (skill / rel).write_text(body, encoding="utf-8")
            (Path(tmp) / "fam" / "other").mkdir()
            (Path(tmp) / "fam" / "other" / "elsewhere.md").write_text("x")
            saved = C.SKILLS_ROOT
            C.SKILLS_ROOT = Path(tmp)
            try:
                return C.file_ref_scan([skill])
            finally:
                C.SKILLS_ROOT = saved

    def test_a_file_held_only_outside_the_skill_is_dangling(self):
        self.assertEqual({"doc": {"elsewhere.md"}}, self.scan("Read `elsewhere.md`.\n"))

    def test_a_file_inside_the_skill_resolves(self):
        self.assertEqual({}, self.scan("Read `voice/a.md`.\n", {"voice/a.md": "x"}))

    def test_the_family_ledger_and_the_fleet_readme_are_not_dangling(self):
        self.assertEqual({}, self.scan("Reasons live in `DECISIONS.md`. Rows live in `README.md`.\n"))

    def test_files_of_the_repo_the_skill_works_on_are_not_dangling(self):
        self.assertEqual({}, self.scan("Read `docs/backlog-config.json`, `docs/VOICE.md` and `CLAUDE.md`.\n"))

    def test_a_missing_file_in_the_skills_own_folders_is_dangling(self):
        self.assertEqual({"doc": {"references/other.md"}}, self.scan("Read `references/other.md`.\n"))
        self.assertEqual({"doc": {"notes/x.md"}}, self.scan("Read `notes/x.md`.\n", {"notes/y.md": "y"}))

    def test_a_run_command_names_a_script_the_skill_must_hold(self):
        self.assertEqual({"doc": {"scripts/check_pages.py"}}, self.scan('python3 "$S/check_pages.py" out.docx\n'))
        self.assertEqual({}, self.scan('python3 "$S/check_pages.py" out.docx\n', {"scripts/check_pages.py": "x"}))


if __name__ == "__main__":
    unittest.main()
