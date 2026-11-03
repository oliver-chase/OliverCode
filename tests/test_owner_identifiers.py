"""The owner-identifier gate (#79), run against each shipped pre-commit hook.

Offline: scratch repos from _support. The author name is built at runtime, so no real name
appears in this file.
"""

import json

from _support import REPO_ROOT, git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

CONFIG = "docs/IDENTIFIER-GATE.json"
FAKE = "zorbian" + "quill"  # a made-up one-word name, joined at runtime


def gate_config(**fields):
    return json.dumps({"configGlobs": [], "localData": [], **fields}, indent=2) + "\n"


class IdentifierSetup:
    HOOK_FILE = None

    @classmethod
    def setUpClass(cls):
        cls.HOOK_SOURCE = REPO_ROOT / cls.HOOK_FILE
        super().setUpClass()

    def setUp(self):
        super().setUp()
        git(self.tmp, "config", "user.name", f"{FAKE.capitalize()} Vantrel")
        git(self.tmp, "config", "user.email", f"{FAKE}@example.invalid")
        self.stage("seed.txt", "seed\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "seed")


class IdentifierGate(IdentifierSetup):
    """Every rule of the gate, run against OliverCode's own hook. The two templates are built from the same gate
    source (build-hooks --check fails on drift), so they get one wiring test."""

    def test_a_derived_author_name_in_a_skill_blocks_and_names_file_and_line(self):
        self.stage("skills/demo/SKILL.md", f"intro\nowned by {FAKE.capitalize()} today\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("skills/demo/SKILL.md:2", out)

    def test_markdown_and_tests_are_scanned(self):
        self.stage("docs/guide.md", f"{FAKE}\n")
        self.stage("tests/test_x.py", f"# {FAKE}\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("docs/guide.md:1", out)
        self.assertIn("tests/test_x.py:1", out)

    def test_the_email_local_part_and_a_second_name_word_count(self):
        self.stage("a.txt", "Vantrel wrote this\n")
        self.assertBlocked("owner identifier")

    def test_the_remote_owner_counts(self):
        git(self.tmp, "remote", "add", "origin", "git@github.com:acme-widgets/repo.git")
        self.stage("a.txt", "see acme-widgets here\n")
        self.assertIn("a.txt:1", self.assertBlocked("owner identifier").stdout)

    def test_matching_is_on_whole_words(self):
        self.stage("a.txt", f"{FAKE}ish and un{FAKE} are other words\n")
        self.assertIn("passed", self.assertAllowed().stdout)

    def test_matching_ignores_case(self):
        self.stage("a.txt", FAKE.upper() + "\n")
        self.assertBlocked("owner identifier")

    def test_local_data_globs_pass_with_an_identifier(self):
        self.stage(CONFIG, gate_config(localData=["fixtures/*"]))
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
        self.stage("fixtures/data.json", f"{FAKE}\n")
        self.stage("src/app.py", f"# {FAKE}\n")
        out = self.assertBlocked("owner identifier").stdout
        self.assertIn("src/app.py:1", out)
        self.assertNotIn("fixtures/data.json:", out)

    def test_config_values_for_account_keys_count(self):
        self.stage(CONFIG, gate_config(configGlobs=["shop/*.json"]))
        self.stage("shop/config.json", '{"shopName": "Daydream Prints", "other": "plainvalue"}\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "shop")
        self.stage("README.txt", "welcome to daydream prints\n")
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
        import shutil
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


class TestIdentifiersPublicTemplateHook(IdentifierWired, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit"


class TestIdentifiersPrivateTemplateHook(IdentifierWired, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"
