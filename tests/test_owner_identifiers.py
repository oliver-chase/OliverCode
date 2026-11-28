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


NAME = f"{FAKE.capitalize()} Vantrel"
SHOP = gate_config(configGlobs=["shop/*.json"])


def row(staged, blocks=(), user=(), author=None, remote=None, committed=None, absent=()):
    """One case: who committed (`user` sets the git identity, `author` adds a commit by someone else), the
    origin, files committed first, files staged, and the `file:line` the gate must name (none means it passes)."""
    return dict(staged=staged, blocks=blocks, user=user, author=author, remote=remote, committed=committed or {}, absent=absent)


TABLE = [
    row({"skills/demo/SKILL.md": f"intro\nowned by {FAKE.capitalize()} today\n"}, ["skills/demo/SKILL.md:2"], absent=[FAKE]),
    *[row({"docs/who.md": prose + "\n"}, ["docs/who.md:1"], user=["Zorbquill Kesh-Vantrel <anon@example.invalid>"])
      for prose in ("by Zorbquill Kesh-Vantrel.", "by Zorbquill Kesh Vantrel", "by zorbquill kesh\u2019vantrel")],
    row({"docs/who.md": "written by Jos\u00e9 Garc\u00eda Vantrel\n"}, ["docs/who.md:1"], user=["Jos\u00e9 Garc\u00eda-Vantrel <anon@example.invalid>"]),
    row({"docs/guide.md": f"{FAKE}\n", "tests/test_x.py": f"# {FAKE}\n"}, ["docs/guide.md:1", "tests/test_x.py:1"]),
    # The full name and an email local part count, a single name word does not, and matching is on whole words in any case.
    row({"a.txt": f"{NAME} wrote this\n"}, ["a.txt:1"]),
    row({"c.txt": "Vantrel wrote this\n"}),
    row({"b.txt": "quillomarr\n"}, ["b.txt:1"], author="Ola Pen <quillomarr@example.invalid>"),
    row({"a.txt": f"{FAKE}ish and un{FAKE} are other words\n"}),
    row({"a.txt": FAKE.upper() + "\n"}, ["a.txt:1"]),
    # The remote owner counts, and the project may name its own remote path, package and spaced repo name.
    row({"a.txt": "see acme-widgets here\n"}, ["a.txt:1"], remote="git@github.com:acme-widgets/repo.git"),
    row({"package.json": '{"name": "@acme-widgets/widget-core"}\n',
         "README.md": "npm i github:acme-widgets/widget-lib and import @acme-widgets/widget-core\n"},
        remote="https://github.com/acme-widgets/widget-lib.git"),
    row({"README.md": "github:acme-widgets/widget-lib is maintained by acme-widgets staff\n"}, ["README.md:1"],
        remote="https://github.com/acme-widgets/widget-lib.git"),
    *[row({"README.md": text}, blocks, author="Widget Library <wl@example.invalid>",
          remote="https://github.com/acme-widgets/widget-library.git")
      for text, blocks in (("The widget library docs live here.\n", ()), ("Ask acme-widgets about the widget library.\n", ["README.md:1"]))],
    row({"docs/who.md": f"by {NAME}\n"}, ["docs/who.md:1"], remote=f"https://github.com/{FAKE}/{FAKE}.git"),
    # An author name of ordinary words blocks only the phrase.
    *[row({"a.txt": text}, blocks, author="Scratch Person <sp@example.invalid>")
      for text, blocks in (("Each person reads the scratch file.\n", ()), ("Written by Scratch Person.\n", ["a.txt:1"]))],
    # Local data passes: a committed glob, the built-in folders and the gate's own config; a file outside still blocks.
    row({"fixtures/data.json": f'{{"who": "{FAKE}"}}\n'}, committed={CONFIG: gate_config(localData=["fixtures/*"])}),
    row({path: f"{FAKE}\n" for path in ("scratch/n.txt", ".secrets/k.txt", "docs/backlog-config.json")}),
    row({CONFIG: gate_config(localDataReasons={FAKE: "the owner"})}),
    row({"fixtures/data.json": f"{FAKE}\n", "src/app.py": f"# {FAKE}\n"}, ["src/app.py:1"],
        committed={CONFIG: gate_config(localData=["fixtures/*"])}, absent=["fixtures/data.json:"]),
    # Account keys in a config glob count; numeric, hex and role values and a regex character do not switch anything off.
    row({"README.txt": "welcome to alphawidgets\n"}, ["README.txt:1"],
        committed={CONFIG: SHOP, "shop/config.json": '{"accountName": "alphawidgets", "shopName": "betastore"}\n'}),
    *[row({"README.txt": text}, blocks, committed={CONFIG: SHOP, "shop/config.json": '{"shopName": "Acme Prints", "other": "plainvalue"}\n'})
      for text, blocks in (("welcome to acme prints\n", ["README.txt:1"]), ("the word plainvalue is fine\n", ()))],
    row({"README.txt": "by ace2024\n"}, ["README.txt:1"], user=["Ace2024 Vantrel <anon@example.invalid>"],
        committed={CONFIG: SHOP, "shop/config.json": '{"shopName": "ace2024"}\n'}),
    row({"README.txt": f"by {NAME}\n"}, ["README.txt:1"], committed={CONFIG: SHOP, "shop/config.json": '{"shopName": "Studio (Etsy"}\n'}),
    row({"README.txt": "colors #00ff88 id 1234567 write to support\n"},
        committed={CONFIG: SHOP, "shop/config.json": '{"brandColor": "#00ff88", "shopId": "1234567", "ownerMail": "support"}\n'}),
    # Generic and Anthropic session authors add no words (#133).
    row({"a.txt": "Claude dependabot github anthropic noreply\n"},
        user=["Claude <noreply@anthropic.com>", "dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>"]),
    row({"a.txt": "A session tracker. Run olivercode conform here.\n"}, user=["claude-session <noreply@anthropic.com>"]),
]


class IdentifierSetup:
    def setUp(self):
        super().setUp()
        git(self.tmp, "config", "user.name", NAME)
        git(self.tmp, "config", "user.email", f"{FAKE}@example.invalid")
        self.stage("seed.txt", "seed\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "seed")


class TestIdentifiersOliverCodeHook(IdentifierSetup, GateHarness):
    """Every rule of the gate, run against OliverCode's own hook. The two templates are built from the same gate
    source by build-hooks.py, so the private one gets one wiring test."""

    HOOK_FILE = ".githooks/pre-commit"

    def test_each_identifier_case_gets_its_verdict(self):
        for case in TABLE:
            with self.subTest(staged=sorted(case["staged"]), user=case["user"], author=case["author"], remote=case["remote"]):
                self.tearDown()
                self.setUp()
                for n, who in enumerate(case["user"]):
                    name, email = who[:-1].split(" <")
                    git(self.tmp, "config", "user.name", name)
                    git(self.tmp, "config", "user.email", email)
                    git(self.tmp, "commit", "-q", "--no-verify", "--allow-empty", "-m", f"author {n}")
                if case["author"]:
                    git(self.tmp, "commit", "-q", "--no-verify", "--allow-empty", "-m", "other author", "--author", case["author"])
                if case["remote"]:
                    git(self.tmp, "remote", "add", "origin", case["remote"])
                for rel, body in case["committed"].items():
                    self.stage(rel, body)
                if case["committed"]:
                    git(self.tmp, "commit", "-q", "--no-verify", "-m", "config")
                for rel, body in case["staged"].items():
                    self.stage(rel, body)
                out = (self.assertBlocked("owner identifier") if case["blocks"] else self.assertAllowed()).stdout
                for word in case["blocks"]:
                    self.assertIn(word, out)
                for word in case["absent"]:
                    self.assertNotIn(word, out.lower())

    def test_a_missing_python_blocks_because_the_scan_could_not_run(self):
        self.stage("a.txt", "plain\n")
        result = self.assertBlocked("owner identifier", PATH=self.path_without("python"))
        self.assertIn("python3 is needed", result.stdout)

    def test_nothing_derivable_skips_with_a_note(self):
        shutil.rmtree(self.tmp / ".git" / "refs" / "heads", ignore_errors=True)
        (self.tmp / ".git" / "refs" / "heads").mkdir()
        (self.tmp / ".git" / "packed-refs").unlink(missing_ok=True)
        self.stage("a.txt", f"{FAKE}\n")
        self.assertIn("skipped", self.assertAllowed().stdout)


class TestIdentifiersPrivateTemplateHook(IdentifierSetup, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"

    def test_a_derived_author_name_blocks(self):
        self.stage("skills/demo/SKILL.md", f"owned by {FAKE.capitalize()} today\n")
        self.assertIn("skills/demo/SKILL.md:1", self.assertBlocked("owner identifier").stdout)
