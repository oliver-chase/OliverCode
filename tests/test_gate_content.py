"""The emoji, PII, workflow-auth, archived-content and skill-citation gates of the pre-commit hook, split from test_precommit_gates so the gate tests run in parallel."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import ISOLATION, REPO_ROOT, git, git_env, scratch_repo
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

HOOK = REPO_ROOT / ".githooks" / "pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-commit"


class TestGate2Emoji(GateHarness):
    def test_emoji_blocks(self):
        self.stage("readme.md", "Status: done \U0001F600\n")
        result = self.assertBlocked("gate 2")
        self.assertIn("emojis or icons", result.stdout)

    def test_a_caption_ledger_under_data_may_hold_emojis(self):
        self.stage("data/items.csv", "clips,caption\nx,first move \U0001F393\n")
        self.assertAllowed()

    def test_the_exemption_stops_at_data_ledgers(self):
        self.stage("docs/items.csv", "clips,caption\nx,first move \U0001F393\n")
        self.assertBlocked("gate 2")

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


if __name__ == "__main__":
    unittest.main()
