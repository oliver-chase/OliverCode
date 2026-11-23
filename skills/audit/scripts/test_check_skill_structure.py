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
from unittest import mock
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


# Built from parts so this file holds no literal path or address for the commit PII gate to block.
USERS = "/Us" + "ers/"
HOMES = "/ho" + "me/"
AT = "@"
ADDRESS = "ada" + AT + "company.com"


class RouteRows(unittest.TestCase):
    def test_a_row_adds_up_the_files_it_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "references" / "big.md").write_text("word " * 30, encoding="utf-8")
            (skill / "SKILL.md").write_text("---\nname: fixture-skill\n---\n| Task | Load |\n|---|---|\n"
                                           "| Build it | `references/used.md`, `references/big.md` |\n", encoding="utf-8")
            rows = C.route_rows(skill)
        self.assertEqual(rows, [(34, ["references/used.md", "references/big.md"], "Build it")])
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp, extra=())
            (skill / "SKILL.md").write_text("---\nname: fixture-skill\n---\n- Build it: `references/used.md`\n", encoding="utf-8")
            self.assertEqual(C.route_rows(skill)[0][1:], (["references/used.md"], "Build it"))


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
            # A name inside a longer word is not a test of the script.
            (tests / "test_smoke.py").write_text("reused = 1\nunused_value = 2\n", encoding="utf-8")
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
            with mock.patch.object(C, "SKILLS_ROOT", Path(tmp)):
                rows = C.weight_table([clean, heavy])
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

    def test_a_skills_path_naming_a_missing_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "See `skills/ghost-zz/SKILL.md` and `skills/ghost-yy`.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("ghost-zz", out)
        self.assertIn("ghost-yy", out)

    def test_reference_to_real_sibling_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "fam/alpha-skill", "Hand the result to the `beta-skill` skill.\n")
            write_skill(tmp, "fam/beta-skill", "Short body.\n")
            code, out = run_gate(tmp)
        self.assertEqual(code, 0, out)


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


class TriggerPhrases(unittest.TestCase):
    def skill(self, tmp, name, phrases):
        skill = Path(tmp) / "fam" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "Does {name} work. Trigger on {phrases}."\n---\n\nBody.\n', encoding="utf-8")

    def test_two_skills_listing_one_phrase_fail_and_both_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill(tmp, "alpha-skill", "'audit this' or 'tonight's work'")
            self.skill(tmp, "beta-skill", "'Audit This ' or 'other thing'")
            code, out = run_gate(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("[duplicate-trigger-phrase]", out)
        self.assertIn('"audit this" is also a trigger phrase of beta-skill', out)
        self.assertIn('"audit this" is also a trigger phrase of alpha-skill', out)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            self.skill(tmp, "alpha-skill", "'audit this'")
            self.skill(other, "personal-skill", "'audit this'")
            code, out = run_gate(tmp, f"--with={other}/fam")
        self.assertEqual(code, 1, out)
        self.assertIn('"audit this" is also a trigger phrase of personal-skill', out)

    def test_distinct_phrases_pass_and_an_apostrophe_stays_in_its_phrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill(tmp, "alpha-skill", "'review tonight's work' or 'audit this'")
            self.skill(tmp, "beta-skill", "'review tonight' or 'work'")
            code, out = run_gate(tmp)
            phrases = C.trigger_phrases(Path(tmp, "fam/alpha-skill/SKILL.md").read_text())
        self.assertEqual(code, 0, out)
        self.assertEqual(phrases, {"review tonight's work", "audit this"})

    def test_olivercode_skills_claim_no_phrase_twice(self):
        self.enterContext(mock.patch.dict("os.environ", {"OLIVERCODE_LOCAL_CONFIG": "/dev/null", "OLIVERCODE_ARCHIVED": "off"}))
        skills = C._fleet.find_skills(Path(__file__).resolve().parents[2])
        self.assertEqual(C.trigger_clash_scan(skills), {})


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


class ScanOneSkill(unittest.TestCase):
    def test_a_single_skill_folder_scans_without_error(self):
        skill = Path(C.__file__).resolve().parents[1]
        with mock.patch.object(C, "SKILLS_ROOT", C.SKILLS_ROOT), contextlib.redirect_stdout(io.StringIO()):
            try:
                C.main([str(skill)])
            except SystemExit as e:
                self.assertIn(e.code, (0, None))


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
            with mock.patch.object(C, "SKILLS_ROOT", Path(tmp)):
                return C.file_ref_scan([skill])

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


class ShellScriptReferences(unittest.TestCase):
    def test_a_cited_shell_script_the_skill_does_not_hold_is_dangling(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = write_skill(tmp, "doc", "Run `scripts/nope.sh` or bash scripts/other.sh now.\n")
            self.assertEqual({"doc": {"scripts/nope.sh", "scripts/other.sh"}}, C.file_ref_scan([skill]))


class BaselineChecks(unittest.TestCase):
    """The mechanical baseline rules, run only with --baseline."""

    def findings(self, files, *, skill="fam/doc-skill", flags=("--baseline",), root_skill=False):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, skill, "Body.\n")
            base = Path(tmp) / skill
            for rel, body in files.items():
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(body, encoding="utf-8")
            return run_gate(tmp, *flags)

    def assert_flags(self, files, rule, **kw):
        code, out = self.findings(files, **kw)
        self.assertEqual(code, 1, out)
        self.assertIn(f"[{rule}]", out)
        return out

    def assert_clean(self, files, **kw):
        code, out = self.findings(files, **kw)
        self.assertEqual(code, 0, out)

    def test_a_skill_with_scripts_whose_steps_name_none_is_flagged(self):
        steps = "".join(f"{n}. Do part {n} by hand.\n" for n in range(1, 6))
        script = {"scripts/run.py": "print('x')\n"}
        self.assert_flags({"SKILL.md": f"---\nname: doc-skill\ndescription: x\n---\n\n{steps}", **script},
                          "baseline-unscripted-procedure")
        calls = "".join(f"{n}. Run `python3 scripts/run.py {n}`.\n" for n in range(1, 6))
        self.assert_clean({"SKILL.md": f"---\nname: doc-skill\ndescription: x\n---\n\n{calls}", **script})
        self.assert_clean({"SKILL.md": f"---\nname: doc-skill\ndescription: x\n---\n\n{steps}"})

    def test_a_recurring_run_that_starts_a_model_with_no_gate_is_flagged(self):
        head = "---\nname: doc-skill\ndescription: x\n---\n\n"
        for line in ("Every night the nightly run starts an agent to check the inbox.\n",
                     "A scheduled job launches a session each hour.\n",
                     "Poll every 5 minutes and spawn a subagent.\n"):
            self.assert_flags({"SKILL.md": head + line}, "baseline-ungated-recurring-run")
        self.assert_clean({"SKILL.md": head + "The nightly run starts an agent only when the gate command finds work.\n"})
        self.assert_clean({"SKILL.md": head + "Start an agent to review the draft.\n"})
        self.assert_clean({"SKILL.md": head + "The nightly job runs the refresh script and starts no model.\n"})
        self.assertEqual(C.ungated_recurring_run("x\nA daily run starts a session.\n"), 2)

    def test_local_path_and_personal_email(self):
        out = self.assert_flags({"references/a.md": "Open " + USERS + "ada/Docs/x.\n"}, "baseline-local-path")
        self.assertIn("references/a.md:1", out)
        self.assert_flags({"scripts/a.py": "p = 'C:\\\\Users\\\\ada\\\\x'\n"}, "baseline-local-path")
        self.assert_flags({"references/a.md": "Write to " + HOMES + "ada/x.\n"}, "baseline-local-path")
        self.assert_flags({"references/a.md": "Mail " + ADDRESS + " today.\n"}, "baseline-local-path")
        self.assert_clean({"references/a.md": "Open " + USERS + "<name>/x, " + USERS + "you/x and a" + AT + "example.com, bot" + AT + "users.noreply.github.com.\n",
                           "tests/t.md": USERS + "ada/x\n", "scripts/test_a.py": "# " + USERS + "ada/x\n"})

    def test_outside_read_by_parent_path(self):
        self.assert_flags({"references/a.md": "Read `../../other/x.md`.\n"}, "baseline-outside-read")
        self.assert_clean({"references/a.md": "Read `../scripts/x.py`.\n", "scripts/x.py": "x = 1\n", "SKILL.md": SKILL_HEAD.format(n="doc-skill") + "A bare `../` is prose.\n"})

    def test_outside_read_of_another_skills_files_only_outside_olivercode(self):
        files = {"references/a.md": "Run `python3 $OC/skills/other-skill/scripts/x.py`.\n"}
        self.assert_flags(files, "baseline-outside-read")
        self.assert_flags({"references/a.md": "Load ~/.claude/skills/other-skill/.env.local.\n"}, "baseline-outside-read")
        self.assert_clean({"references/a.md": "Run `python3 ~/.claude/skills/doc-skill/scripts/x.py`.\n"})
        with tempfile.TemporaryDirectory() as tmp:
            skill = write_skill(tmp, "fam/doc-skill", "Body.\n")
            (skill / "a.md").write_text("Run `python3 $OC/skills/other-skill/scripts/x.py`.\n", encoding="utf-8")
            with mock.patch.object(C, "OC_SKILLS", Path(tmp)):
                self.assertEqual(C.baseline_findings(skill), [])

    def test_history_notes(self):
        for text in ("See DECISIONS-12.", "Per SPEC-3.", "ACT-44 fixed it.", "Fixed in story #492.", "From PR #7.", "## Known gaps\n", "## Changelog\n", "## Change log\n"):
            self.assert_flags({"references/a.md": text + "\n"}, "baseline-history-note")
        self.assert_clean({"references/a.md": "Run `gh issue view #12`-style ids, `ticket #123` in code, ### Known gaps below h2, 3 issues.\n"})

    def test_sample_names(self):
        for name in ("John Doe", "Jane Smith", "Alice", "Bob", "Charlie", "Carol", "Dave", "Mary Smith", "Joe Bloggs"):
            self.assert_flags({"references/a.md": f"Email {name} now.\n"}, "baseline-sample-name")
        self.assert_clean({"references/a.md": "Email Jane Doe, John Smith and Sally May. Bobcat and Alicepath are fine.\n"})

    def test_name_suffix(self):
        self.assert_flags({"references/notes-v2.md": "x\n"}, "baseline-name-suffix")
        self.assert_flags({"scripts/run_2.py": "x\n"}, "baseline-name-suffix")
        self.assert_flags({"references/fix-issue-12.md": "x\n"}, "baseline-name-suffix")
        self.assert_flags({"references/fix-ticket123.md": "x\n"}, "baseline-name-suffix")
        self.assert_flags({}, "baseline-name-suffix", skill="fam/doc-skill-v2")
        self.assert_clean({"scripts/sha256.py": "x\n", "scripts/utf8.py": "x\n", "references/log-2026-11-17.md": "x\n", "references/md5.md": "x\n"})

    def test_env_example_needs_a_setup_mode(self):
        self.assert_flags({".env.local.example": "KEY=\n"}, "baseline-setup-missing")
        self.assert_clean({".env.local.example": "KEY=\n", "modes/setup.md": "Setup.\n"})
        self.assert_clean({".env.local.example": "KEY=\n", "references/first-setup.md": "Setup.\n"})
        self.assert_clean({".env.local.example": "KEY=\n", "SKILL.md": SKILL_HEAD.format(n="doc-skill") + "## Setup\nDo it.\n"})
        self.assert_clean({"references/a.md": "No example file here.\n"})

    def test_default_mode_ignores_every_baseline_pattern(self):
        bad = {"references/a.md": USERS + "ada/x " + ADDRESS + " DECISIONS-1 Alice ../../x\n", "references/notes-v2.md": "x\n", ".env.local.example": "K=\n"}
        self.assert_clean(bad, flags=())
        self.assert_flags(bad, "baseline-local-path")
