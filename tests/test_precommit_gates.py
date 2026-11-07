"""Tests for .githooks/pre-commit — the only mechanically-enforced layer.

Each gate gets a case that MUST block and a case that MUST pass. The hook reads
staged files from git, so every test copies a template repo that already holds the hook,
stages a fixture, and runs the hook against it. Each class builds its template once.
Nothing touches this checkout.

Gates that consult the machine run against stand-ins: the workflow-auth gate and the
skill-citation check get a stub `gh` on PATH. Every `exit 1` in a gate has a test that fails when it
becomes `true`.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import ISOLATION, REPO_ROOT, git, git_env, scratch_repo

HOOK = REPO_ROOT / ".githooks" / "pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-commit"
_SAVED_GIT_ENV = {}


def setUpModule():
    # `git rebase -x` and `git bisect run` export GIT_DIR, which would aim every scratch-repo
    # git call (config, add, commit) at the real checkout. Drop them for the whole module.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        _SAVED_GIT_ENV[key] = os.environ.pop(key)
    os.environ.update(ISOLATION)


def tearDownModule():
    os.environ.update(_SAVED_GIT_ENV)


class GateHarness(unittest.TestCase):
    """Builds a scratch git repo with the hook installed."""

    HOOK_SOURCE = HOOK

    @classmethod
    def setUpClass(cls):
        cls._template_dir = Path(tempfile.mkdtemp(prefix="olivercode-gates-template-"))
        template = scratch_repo(cls._template_dir / "repo")
        hooks = template / ".githooks"
        hooks.mkdir()
        shutil.copy2(cls.HOOK_SOURCE, hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)
        cls._template = template

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._template_dir, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-gates-"))
        shutil.rmtree(self.tmp)
        shutil.copytree(self._template, self.tmp, symlinks=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(self.tmp, "add", relpath)

    def write(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def stub_gh(self, script):
        """A `gh` that runs `script` (bash, args in "$@") ahead of any real one on PATH."""
        gh = self.write("stub-bin/gh", "#!/usr/bin/env bash\n" + script)
        gh.chmod(0o755)
        return {"PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}"}

    def run_hook(self, **env_overrides):
        # validate.sh --tree exports OLIVERCODE_SCAN_TREE, and a test must check staged
        # files only.
        env = {k: v for k, v in os.environ.items() if not k.startswith("OLIVERCODE_")}
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(self.tmp / ".githooks" / "pre-commit")],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            env=env,
        )

    def assertBlocked(self, gate_hint="", **env):
        result = self.run_hook(**env)
        self.assertNotEqual(
            result.returncode, 0, f"hook should have blocked ({gate_hint}); output:\n{result.stdout}"
        )
        return result

    def assertAllowed(self, **env):
        result = self.run_hook(**env)
        self.assertEqual(
            result.returncode, 0, f"hook should have passed; output:\n{result.stdout}{result.stderr}"
        )
        return result


class TestGate1Secrets(GateHarness):
    def test_openai_style_key_blocks(self):
        self.stage("config.py", 'KEY = "sk-' + "a" * 32 + '"\n')
        self.assertBlocked("gate 1")

    def test_github_pat_blocks(self):
        self.stage("deploy.sh", "TOKEN=ghp_" + "b" * 36 + "\n")
        self.assertBlocked("gate 1")
        git(self.tmp, "rm", "-q", "--cached", "deploy.sh")
        # Current credential formats, each built at run time and staged alone.
        modern = {
            "anthropic": "sk-" + "ant-api03-" + "A1b_" * 20,
            "github fine-grained": "github" + "_pat_" + "11ABC" + "Ab3" * 20,
            "github oauth": "gh" + "o_" + "c" * 36,
            "aws secret with slashes": "aws_secret_access_key = " + "Ab/c+De" * 5 + "Ab/c+",
            "slack webhook": "https://hooks." + "slack.com/services/T0ABC/B0DEF/" + "g" * 24,
            "gitlab": "gl" + "pat-" + "h" * 20,
            "hugging face": "h" + "f_" + "i" * 34,
            "sendgrid": "S" + "G." + "j" * 22 + "." + "k" * 43,
            "webhook secret": "wh" + "sec_" + "m" * 32,
            "google oauth": "ya" + "29." + "n" * 40,
        }
        for name, value in modern.items():
            with self.subTest(name):
                self.stage("cred.txt", value + "\n")
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", "cred.txt")

    def test_private_key_header_blocks(self):
        self.stage("id.txt", "-----BEGIN RSA " + "PRIVATE KEY-----\n")
        self.assertBlocked("gate 1")

    def test_a_secret_in_a_large_file_blocks(self):
        # A pipeline that exits early fails open on big files under pipefail.
        self.stage("big.py", ('KEY = "sk-' + "d" * 32 + '"\n') * 2000)
        self.assertBlocked("gate 1")

    def test_no_path_is_exempt_and_a_placeholder_is_exempt_by_its_value_or_line(self):
        key = "sk-" + "c" * 32
        for path in ("tests/t.txt", "src/mock_client.py", ".env.example"):
            with self.subTest(path):
                self.stage(path, f'API_KEY="{key}"\n')
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", path)
        # A placeholder word elsewhere on the line does not excuse a real key.
        for line in (f'curl https://api.example.com -H "Authorization: Bearer {key}"',
                     f"OPENAI_KEY={key}  # paste your_token here"):
            with self.subTest(line):
                self.stage("run.sh", line + "\n")
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", "run.sh")
        self.stage(".env.example", 'API_KEY="sk-' + "EXAMPLE" + "0" * 20 + '"\n'
                   f'TOKEN="{key}"  # secret-scan: allow\n')
        self.assertAllowed()

    def test_ordinary_prose_passes(self):
        self.stage("notes.md", "This file mentions a token conceptually.\n")
        self.assertAllowed()


class SecretGateEveryVariant:
    """A staged fake key blocks the commit in every shipped hook. The key is built at run time."""

    def test_a_staged_fake_key_blocks_at_the_secret_gate(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        out = self.assertBlocked("gate 1").stdout
        self.assertIn("Secret scan", out)
        self.assertIn("matches secret pattern", out)
        self.assertNotIn("Gate 2/", out)  # Gate 1 stops the commit itself, before any later gate runs

    def test_a_clean_file_passes_the_secret_gate(self):
        self.stage("notes.txt", "Plain notes.\n")
        self.assertIn("Secret scan", self.assertAllowed().stdout)


class StagedContent:
    """The gates read what the commit records: the staged content, under the file's real name.

    Git prints a name with an accent or an em dash quoted, and a gate that reads the staged list as
    plain text never opens the file. A gate that reads the working copy sees only what the file holds
    now, so a value staged and then edited out of the working copy still lands in the commit.
    It runs on OliverCode's own hook: the templates are built from the same gate source, and
    build-hooks --check fails on any drift."""

    def test_a_secret_in_a_name_with_an_em_dash_blocks(self):
        self.stage("Notes \u2014 Plan.txt", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        self.assertIn("matches secret pattern", self.assertBlocked("gate 1").stdout)

    def test_a_secret_in_a_name_with_an_accent_blocks(self):
        self.stage("caf\u00e9.txt", "TOKEN=ghp_" + "b" * 36 + "\n")
        self.assertBlocked("gate 1")

    def test_a_staged_secret_blocks_after_the_working_copy_is_cleaned(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        self.write("config.py", "KEY = os.environ['KEY']\n")
        self.assertIn("matches secret pattern", self.assertBlocked("gate 1").stdout)

    def test_an_emoji_in_a_name_with_an_accent_blocks(self):
        self.stage("caf\u00e9.txt", "party \U0001F600\n")
        self.assertBlocked("gate 2")

    def test_a_staged_emoji_blocks_after_the_working_copy_is_cleaned(self):
        self.stage("notes.txt", "party \U0001F600\n")
        self.write("notes.txt", "party\n")
        self.assertBlocked("gate 2")

    def test_the_block_message_does_not_suggest_a_way_around_the_gate(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        out = self.assertBlocked("gate 1").stdout
        self.assertNotIn("rename", out)
        self.assertNotIn("skip patterns", out)

    def test_a_clean_file_with_an_em_dash_name_passes(self):
        self.stage("Notes \u2014 Clean.txt", "Plain notes.\n")
        self.assertAllowed()


class TestLiveHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    pass


class TestTemplateHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    HOOK_SOURCE = TEMPLATE_HOOK


class TestPrivateHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    HOOK_SOURCE = REPO_ROOT / "core" / "templates" / "project" / "pre-commit-private"


class TestLiveHookReadsStagedContent(StagedContent, GateHarness):
    pass


class TestGate2Emoji(GateHarness):
    def test_emoji_blocks(self):
        self.stage("readme.md", "Status: done \U0001F600\n")
        result = self.assertBlocked("gate 2")
        self.assertIn("emojis or icons", result.stdout)

    def test_plain_text_passes(self):
        self.stage("readme.md", "Status: done.\n")
        self.assertAllowed()

    def test_box_drawing_is_allowed(self):
        # The QA scripts use box-drawing characters in their banners; those are not
        # in the blocked ranges and must stay usable.
        self.stage("banner.sh", "echo \"" + "╔" + "═" * 5 + "╗\"\n")
        self.assertAllowed()

    def test_missing_perl_blocks_before_any_later_gate(self):
        # Without perl the scan finds nothing, so the gate must stop the commit itself.
        # PATH keeps every other tool, so only the guard can make this run fail.
        bin_dir = self.tmp / "no-perl-bin"
        bin_dir.mkdir()
        for entry in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(entry):
                continue
            for name in os.listdir(entry):
                target = Path(entry) / name
                if name.startswith("perl") or (bin_dir / name).exists():
                    continue
                if os.access(target, os.X_OK) and not target.is_dir():
                    (bin_dir / name).symlink_to(target)
        self.stage("readme.md", "Status: done.\n")
        result = self.assertBlocked("gate 2", PATH=str(bin_dir))
        self.assertIn("perl not found", result.stdout)
        self.assertNotIn("Gate 3/", result.stdout)


class TestGate3PII(GateHarness):
    def test_macos_home_path_blocks(self):
        self.stage("run.sh", "cd /Users/someone/projects\n")
        self.assertBlocked("gate 3")

    def test_linux_home_path_blocks(self):
        self.stage("run.sh", "cd /home/someone/projects\n")
        self.assertBlocked("gate 3")

    def test_email_blocks(self):
        self.stage("run.sh", "NOTIFY=person@example.com\n")
        self.assertBlocked("gate 3")

    def test_markdown_is_exempt(self):
        # Docs legitimately quote host paths as examples; .md is skipped by design.
        self.stage("doc.md", "Example path: /Users/someone/projects\n")
        self.assertAllowed()

    def test_placeholder_path_passes(self):
        self.stage("run.sh", "cd <vault-root>/projects\n")
        self.assertAllowed()


class TestGateWorkflowAuth(GateHarness):
    SCOPES = 'case "$1 $2" in "auth status") exit 0 ;; "api user") echo "x-oauth-scopes: {}" ;; esac\n'

    def setUp(self):
        super().setUp()
        self.stage(".github/workflows/ci.yml", "on: push\n")

    def test_a_credential_without_workflow_scope_blocks(self):
        result = self.assertBlocked("gate 4", **self.stub_gh(self.SCOPES.format("repo, gist")))
        self.assertIn("no workflow-scoped credential", result.stdout)

    def test_no_signed_in_gh_blocks(self):
        result = self.assertBlocked("gate 4", **self.stub_gh("exit 1\n"))
        self.assertIn("no workflow-scoped credential", result.stdout)

    def test_a_credential_with_workflow_scope_passes(self):
        result = self.assertAllowed(**self.stub_gh(self.SCOPES.format("repo, workflow")))
        self.assertIn("gh credential has workflow scope", result.stdout)
        self.assertIn("passed", result.stdout)


class TestGateArchivedContent(GateHarness):
    def test_an_archive_directory_blocks(self):
        self.stage("docs/Archive/plan.md", "Old plan.\n")
        self.assertIn("names an archive", self.assertBlocked("gate 5").stdout)

    def test_a_superseded_copy_name_blocks(self):
        self.stage("docs/plan-old.md", "Old plan.\n")
        self.assertIn("named as a superseded copy", self.assertBlocked("gate 5").stdout)

    def test_prose_about_legacy_systems_passes(self):
        self.stage("docs/Legacy Modernization.md", "How we replace legacy systems.\n")
        self.assertIn("passed", self.assertAllowed().stdout)

    def local_hook(self, body):
        local = self.write(".githooks/pre-commit.local", "#!/usr/bin/env bash\n" + body)
        local.chmod(0o755)

    def test_a_repo_local_hook_can_exempt_a_path_with_status_10(self):
        """The framework carries no repo-specific exemption; the repo declares its own."""
        self.local_hook('[ "${1:-}" = archive-exempt ] && case "$2" in "records/Archive/"*) exit 10 ;; esac\nexit 0\n')
        self.stage("records/Archive/week-1.md", "Done.\n")
        self.assertIn("passed", self.assertAllowed().stdout)

    def test_the_exemption_covers_only_the_path_the_hook_names(self):
        self.local_hook('[ "${1:-}" = archive-exempt ] && case "$2" in "records/Archive/"*) exit 10 ;; esac\nexit 0\n')
        self.stage("docs/Archive/plan.md", "Old plan.\n")
        self.assertIn("names an archive", self.assertBlocked("gate 5").stdout)

    def test_a_local_hook_that_exits_zero_for_everything_exempts_nothing(self):
        self.local_hook("exit 0\n")
        self.stage("docs/plan-old.md", "Old plan.\n")
        self.assertIn("named as a superseded copy", self.assertBlocked("gate 5").stdout)

    def test_without_a_local_hook_the_same_path_blocks(self):
        self.stage("records/Archive/week-1.md", "Done.\n")
        self.assertBlocked("gate 5")


class TestGateSkillCitations(GateHarness):
    """Offline: a stub `gh` that knows issues 1 and 2."""

    GH = 'case "$1 $2" in "auth status") exit 0 ;; "issue list") printf "1\\n2\\n" ;; esac\n'

    def setUp(self):
        super().setUp()
        self.env = {**self.stub_gh(self.GH)}

    def test_a_citation_to_no_real_issue_blocks(self):
        self.stage("skills/x/SKILL.md", "Fixes the parser, see #99.\n")
        result = self.assertBlocked("gate 6", **self.env)
        self.assertIn("#99", result.stdout)
        # The staged copy is judged, so cleaning the working copy after staging does not hide it.
        self.write("skills/x/SKILL.md", "Fixes the parser.\n")
        self.assertBlocked("gate 6", **self.env)

    def test_a_citation_to_a_real_issue_passes(self):
        self.stage("skills/x/SKILL.md", "Fixes the parser, see #2.\n")
        self.assertIn("passed", self.assertAllowed(**self.env).stdout)


class TestPrivateRepoLocalGate(GateHarness):
    """The private variant runs a repo's own .githooks/pre-commit.local after its gates."""

    def setUp(self):
        super().setUp()
        shutil.copy2(REPO_ROOT / "core/templates/project/pre-commit-private",
                     self.tmp / ".githooks" / "pre-commit")

    def local_gate(self, code):
        local = self.write(".githooks/pre-commit.local", f"#!/usr/bin/env bash\nexit {code}\n")
        local.chmod(0o755)
        self.stage("notes.txt", "Plain notes.\n")

    def test_a_failing_local_gate_blocks(self):
        self.local_gate(1)
        self.assertNotIn("All gates passed", self.assertBlocked("repo-local").stdout)

    def test_a_passing_local_gate_passes(self):
        self.local_gate(0)
        self.assertIn("All gates passed", self.assertAllowed().stdout)


class TestTreeScan(GateHarness):
    """A secret already committed passes a normal run, because nothing is staged, and fails a tree scan."""

    def setUp(self):
        super().setUp()
        self.stage("config.py", 'KEY = "sk-' + "d" * 32 + '"\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "x")

    def test_a_normal_run_sees_nothing_staged(self):
        self.assertEqual(0, self.run_hook().returncode)

    def test_a_tree_scan_finds_the_committed_secret(self):
        result = subprocess.run(
            ["bash", str(self.tmp / ".githooks" / "pre-commit")],
            cwd=self.tmp, capture_output=True, text=True,
            env={**os.environ, "OLIVERCODE_SCAN_TREE": "1"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret pattern", result.stdout)


class TestLinkedWorktree(unittest.TestCase):
    """A commit from a linked worktree runs every gate. Git sets GIT_DIR for a hook there,
    and `git -C .githooks rev-parse --show-toplevel` then answers with the .githooks folder,
    so the secret scan read no file at all."""

    @classmethod
    def setUpClass(cls):
        """One main repo and one linked worktree for the class; each test resets the worktree."""
        cls.tmp = Path(tempfile.mkdtemp(prefix="olivercode-worktree-"))
        cls.main = cls.tmp / "main"
        cls.wt = cls.tmp / "wt"
        scratch_repo(cls.main)
        cls.git("-C", str(cls.main), "config", "core.hooksPath", ".githooks")
        (cls.main / ".githooks").mkdir()
        shutil.copy2(HOOK, cls.main / ".githooks" / "pre-commit")
        (cls.main / ".githooks" / "pre-commit").chmod(0o755)
        cls.git("-C", str(cls.main), "add", "-A")
        cls.git("-C", str(cls.main), "commit", "-q", "--no-verify", "-m", "base")
        cls.git("-C", str(cls.main), "worktree", "add", "-q", str(cls.wt))
        cls.base = cls.git("-C", str(cls.main), "rev-parse", "HEAD").stdout.strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.git("-C", str(self.wt), "reset", "-q", "--hard", self.base)
        self.git("-C", str(self.wt), "clean", "-fdq")

    @classmethod
    def git(cls, *args, **kw):
        return subprocess.run(["git", *args], check=kw.pop("check", True),
                              capture_output=True, text=True, env=git_env(), **kw)

    @staticmethod
    def write(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def commit_in_worktree(self, rel, body):
        self.write(self.wt / rel, body)
        self.git("-C", str(self.wt), "add", rel)
        return self.git("-C", str(self.wt), "commit", "-m", "change", check=False)

    def test_a_secret_blocks(self):
        result = self.commit_in_worktree("config.py", 'KEY = "sk-' + "e" * 32 + '"\n')
        out = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, out)
        self.assertIn("secret pattern", out)


if __name__ == "__main__":
    unittest.main()
