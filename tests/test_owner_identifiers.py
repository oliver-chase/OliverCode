"""The owner-identifier gate (#79), run against each shipped pre-commit hook.

Offline: scratch repos from _support. The author name is built at runtime, so no real name
appears in this file.
"""

import json
import shutil

from _support import git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401
__all__ = ["setUpModule", "tearDownModule"]  # unittest runs them from this module

CONFIG = "docs/IDENTIFIER-GATE.json"
FAKE = "zorbian" + "quill"  # a made-up one-word name, joined at runtime


def gate_config(**fields):
    return json.dumps({"configGlobs": [], "localData": [], **fields}, indent=2) + "\n"


class IdentifierSetup:
    def setUp(self):
        super().setUp()
        git(self.tmp, "config", "user.name", f"{FAKE.capitalize()} Vantrel")
        git(self.tmp, "config", "user.email", f"{FAKE}@example.invalid")
        self.stage("seed.txt", "seed\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "seed")


class IdentifierGate(IdentifierSetup):
    """Every rule of the gate, run against OliverCode's own hook. The two templates are built from the same gate
    source by build-hooks.py, so they get one wiring test."""

    def test_a_derived_author_name_in_a_skill_blocks_and_names_file_and_line(self):
        self.stage("skills/demo/SKILL.md", f"intro\nowned by {FAKE.capitalize()} today\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("skills/demo/SKILL.md:2", out)
        self.assertNotIn(FAKE, out.lower())

    def test_a_name_with_a_hyphen_or_apostrophe_blocks_as_written(self):
        git(self.tmp, "config", "user.name", "Zorbquill Kesh-Vantrel")
        git(self.tmp, "config", "user.email", "anon@example.invalid")
        self.stage("two.txt", "two\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "second")
        for prose in ("by Zorbquill Kesh-Vantrel.", "by Zorbquill Kesh Vantrel", "by zorbquill kesh\u2019vantrel"):
            with self.subTest(prose):
                self.stage("docs/who.md", prose + "\n")
                self.assertIn("docs/who.md:1", self.assertBlocked("owner identifier").stdout)

    def test_an_author_name_with_accented_letters_blocks(self):
        git(self.tmp, "config", "user.name", "Jos\u00e9 Garc\u00eda-Vantrel")
        git(self.tmp, "config", "user.email", "anon@example.invalid")
        self.stage("two.txt", "two\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "second")
        self.stage("docs/who.md", "written by Jos\u00e9 Garc\u00eda Vantrel\n")
        self.assertIn("docs/who.md:1", self.assertBlocked("owner identifier").stdout)

    def test_a_missing_python_blocks_because_the_scan_could_not_run(self):
        self.stage("a.txt", "plain\n")
        result = self.assertBlocked("owner identifier", PATH=self.path_without("python"))
        self.assertIn("python3 is needed", result.stdout)

    def test_markdown_and_tests_are_scanned(self):
        self.stage("docs/guide.md", f"{FAKE}\n")
        self.stage("tests/test_x.py", f"# {FAKE}\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("docs/guide.md:1", out)
        self.assertIn("tests/test_x.py:1", out)

    def test_the_full_name_and_the_email_local_part_count_and_a_single_name_word_does_not(self):
        self.stage("a.txt", f"{FAKE.capitalize()} Vantrel wrote this\n")
        self.assertBlocked("owner identifier")
        git(self.tmp, "rm", "-q", "--cached", "a.txt")
        self.stage("c.txt", "Vantrel wrote this\n")
        self.assertIn("passed", self.assertAllowed().stdout)
        git(self.tmp, "rm", "-q", "--cached", "c.txt")
        # A local part that matches no name counts on its own.
        git(self.tmp, "commit", "-q", "--no-verify", "--allow-empty", "-m", "other author",
            "--author", "Ola Pen <quillomarr@example.invalid>")
        self.stage("b.txt", "quillomarr\n")
        self.assertBlocked("owner identifier")

    def test_the_remote_owner_counts(self):
        git(self.tmp, "remote", "add", "origin", "git@github.com:acme-widgets/repo.git")
        self.stage("a.txt", "see acme-widgets here\n")
        self.assertIn("a.txt:1", self.assertBlocked("owner identifier").stdout)

    def test_a_project_may_name_its_own_remote_path_and_package(self):
        git(self.tmp, "remote", "add", "origin", "https://github.com/acme-widgets/widget-lib.git")
        self.stage("package.json", '{"name": "@acme-widgets/widget-core"}\n')
        self.stage("README.md", "npm i github:acme-widgets/widget-lib and import @acme-widgets/widget-core\n")
        self.assertIn("passed", self.assertAllowed().stdout)

    def test_the_spaced_repo_name_is_the_project_and_the_owner_still_blocks(self):
        git(self.tmp, "remote", "add", "origin", "https://github.com/acme-widgets/widget-library.git")
        git(self.tmp, "commit", "-q", "--no-verify", "--allow-empty", "-m", "other author",
            "--author", "Widget Library <wl@example.invalid>")
        self.stage("README.md", "The widget library docs live here.\n")
        self.assertIn("passed", self.assertAllowed().stdout)
        self.stage("NOTES.md", "Ask acme-widgets about the widget library.\n")
        self.assertIn("NOTES.md:1", self.assertBlocked("owner identifier").stdout)

    def test_the_owner_name_beside_the_project_name_still_blocks(self):
        git(self.tmp, "remote", "add", "origin", "https://github.com/acme-widgets/widget-lib.git")
        self.stage("README.md", "github:acme-widgets/widget-lib is maintained by acme-widgets staff\n")
        self.assertIn("README.md:1", self.assertBlocked("owner identifier").stdout)

    def test_an_author_name_made_of_ordinary_words_blocks_only_the_phrase(self):
        git(self.tmp, "commit", "-q", "--no-verify", "--allow-empty", "-m", "other author",
            "--author", "Scratch Person <sp@example.invalid>")
        self.stage("a.txt", "Each person reads the scratch file.\n")
        self.assertIn("passed", self.assertAllowed().stdout)
        self.stage("b.txt", "Written by Scratch Person.\n")
        self.assertIn("b.txt:1", self.assertBlocked("owner identifier").stdout)

    def test_matching_is_on_whole_words(self):
        self.stage("a.txt", f"{FAKE}ish and un{FAKE} are other words\n")
        self.assertIn("passed", self.assertAllowed().stdout)

    def test_matching_ignores_case(self):
        self.stage("a.txt", FAKE.upper() + "\n")
        self.assertBlocked("owner identifier")

    def test_local_data_globs_pass_with_an_identifier(self):
        self.stage(CONFIG, gate_config(localData=["fixtures/*"]))
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "gate config")
        self.stage("fixtures/data.json", f'{{"who": "{FAKE}"}}\n')
        self.assertAllowed()

    def test_built_in_local_data_passes(self):
        for path in ("scratch/n.txt", ".secrets/k.txt", "docs/backlog-config.json"):
            self.stage(path, f"{FAKE}\n")
        self.assertAllowed()

    def test_the_gates_own_config_may_name_an_identifier(self):
        self.stage(CONFIG, gate_config(localDataReasons={FAKE: "the owner"}))
        self.assertAllowed()

    def test_a_file_outside_local_data_still_blocks_beside_one_inside(self):
        self.stage(CONFIG, gate_config(localData=["fixtures/*"]))
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "gate config")
        self.stage("fixtures/data.json", f"{FAKE}\n")
        self.stage("src/app.py", f"# {FAKE}\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("src/app.py:1", out)
        self.assertNotIn("fixtures/data.json:", out)

    def test_every_account_key_on_one_config_line_counts(self):
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"accountName": "alphawidgets", "shopName": "betastore"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", "welcome to alphawidgets\n")
        self.assertBlocked("owner identifier")

    def test_an_author_name_made_of_hex_letters_and_a_digit_still_blocks(self):
        git(self.tmp, "config", "user.name", "Ace2024 Vantrel")
        git(self.tmp, "config", "user.email", "anon@example.invalid")
        self.stage("two.txt", "two\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "second")
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"shopName": "ace2024"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", "by ace2024\n")
        self.assertBlocked("owner identifier")

    def test_a_repo_named_like_its_owner_still_blocks_the_authors_name(self):
        git(self.tmp, "remote", "add", "origin", f"https://github.com/{FAKE}/{FAKE}.git")
        self.stage("docs/who.md", f"by {FAKE.capitalize()} Vantrel\n")
        self.assertIn("docs/who.md:1", self.assertBlocked("owner identifier").stdout)

    def test_a_config_value_with_a_regex_character_does_not_switch_the_gate_off(self):
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"shopName": "Studio (Etsy"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", f"by {FAKE.capitalize()} Vantrel\n")
        self.assertBlocked("owner identifier")

    def test_numeric_hex_and_role_values_are_not_identifiers(self):
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"brandColor": "#00ff88", "shopId": "1234567", "ownerMail": "support"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", "colors #00ff88 id 1234567 write to support\n")
        self.assertAllowed()

    def test_config_values_for_account_keys_count(self):
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"shopName": "Acme Prints", "other": "plainvalue"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", "welcome to acme prints\n")
        self.assertIn("README.txt:1", self.assertBlocked("owner identifier").stdout)
        self.stage("README.txt", "the word plainvalue is fine\n")
        self.assertAllowed()

    def test_generic_authors_are_ignored(self):
        git(self.tmp, "config", "user.name", "Claude")
        git(self.tmp, "config", "user.email", "noreply@anthropic.com")
        self.write("seed.txt", "seed2\n")
        git(self.tmp, "add", "seed.txt")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "second")
        git(self.tmp, "config", "user.name", "dependabot[bot]")
        git(self.tmp, "config", "user.email", "49699333+dependabot[bot]@users.noreply.github.com")
        self.write("seed.txt", "seed3\n")
        git(self.tmp, "add", "seed.txt")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "third")
        self.stage("a.txt", "Claude dependabot github anthropic noreply\n")
        self.assertAllowed()

    def test_an_anthropic_session_author_name_adds_no_words(self):
        """A session commit is authored with a name like claude-session or conform-bot and the Anthropic
        noreply email. Splitting the name made 'session' and 'conform' owner identifiers, which blocked
        every later commit that staged CLAUDE.md or QUALITY_BASELINE.md (#133)."""
        git(self.tmp, "config", "user.name", "claude-session")
        git(self.tmp, "config", "user.email", "noreply@anthropic.com")
        self.write("seed.txt", "seed2\n")
        git(self.tmp, "add", "seed.txt")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "second")
        self.stage("a.txt", "A session tracker. Run olivercode conform here.\n")
        self.assertAllowed()

    def test_nothing_derivable_skips_with_a_note(self):
        shutil.rmtree(self.tmp / ".git" / "refs" / "heads", ignore_errors=True)
        (self.tmp / ".git" / "refs" / "heads").mkdir()
        (self.tmp / ".git" / "packed-refs").unlink(missing_ok=True)
        self.stage("a.txt", f"{FAKE}\n")
        out = self.assertAllowed().stdout
        self.assertIn("skipped", out)


class TestIdentifiersOliverCodeHook(IdentifierGate, GateHarness):
    HOOK_FILE = ".githooks/pre-commit"


class IdentifierWired(IdentifierSetup):
    def test_a_derived_author_name_blocks(self):
        self.stage("skills/demo/SKILL.md", f"owned by {FAKE.capitalize()} today\n")
        self.assertIn("skills/demo/SKILL.md:1", self.assertBlocked("owner identifier").stdout)


class TestIdentifiersPrivateTemplateHook(IdentifierWired, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"
