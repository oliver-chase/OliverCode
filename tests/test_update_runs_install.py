"""`olivercode update` re-runs install after the pull.

A pull can add a skill or a Claude Code hook, and only install links those into ~/.claude.
Before update ran install, a second device pulled four new skills and had no link to them.
"""

import unittest
from unittest import mock

from _support import load_script

launcher = load_script("scripts/olivercode", "olivercode_update")


class UpdateRunsInstall(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("lib.update_state.rewritten", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_update(self, dashboard_changed=False, city_url="", failures=None):
        calls = []
        failures = failures or {}

        def fake_run(argv, **kwargs):
            if argv[0] == "git":
                step = "pull" if argv[3] == "pull" else "dashboard-diff"
            else:
                step = argv[-1]
            calls.append(step)
            code = failures.get(step, 0)
            if step == "dashboard-diff" and dashboard_changed:
                code = 1
            return mock.Mock(returncode=code)

        import io
        from contextlib import redirect_stdout
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch("lib.cmd_fleet.status_report.city_url", return_value=city_url), \
                mock.patch.object(launcher.subprocess, "run", side_effect=fake_run), \
                redirect_stdout(io.StringIO()) as stream:
            result = launcher.command_update()
        return result, calls, stream.getvalue()

    def test_a_pull_is_followed_by_install_hook_sync_and_fleet_conform(self):
        code, calls, _ = self.run_update()
        self.assertEqual((code, calls), (0, ["pull", "dashboard-diff", "install", "sync-hooks", "conform"]))

    def test_dashboard_renderer_change_refreshes_local_page_and_reminds_about_artifact(self):
        code, calls, output = self.run_update(dashboard_changed=True, city_url="https://claude.ai/artifact/example")
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], "page")
        self.assertIn("local status page was refreshed", output)
        self.assertIn("olivercode status publish", output)
        self.assertIn("Nothing was published automatically", output)

    def test_dashboard_renderer_change_refreshes_local_page_without_artifact(self):
        code, calls, output = self.run_update(dashboard_changed=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], "page")
        self.assertIn("No City Artifact is configured", output)

    def test_content_only_update_does_not_refresh_or_remind(self):
        code, calls, output = self.run_update()
        self.assertEqual(code, 0)
        self.assertNotIn("page", calls)
        self.assertNotIn("publish", output)

    def test_a_conform_failure_fails_the_update(self):
        code, calls, _ = self.run_update(failures={"conform": 1})
        self.assertEqual((code, calls[-1]), (1, "conform"))

    def test_install_and_sync_run_the_launcher_the_pull_updated(self):
        argvs = []
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch("lib.cmd_fleet.status_report.city_url", return_value=""), \
                mock.patch.object(launcher.subprocess, "run",
                                  side_effect=lambda argv, **kw: argvs.append(argv) or mock.Mock(returncode=0)):
            launcher.command_update()
        launcher_calls = [a for a in argvs if a[0] != "git"]
        self.assertTrue(all(a[1].endswith("scripts/olivercode") for a in launcher_calls), argvs)

    def test_a_story_makes_the_hook_sync_commit(self):
        argvs = []
        with mock.patch("lib.update_state.problem", return_value=None), \
                mock.patch("lib.cmd_fleet.status_report.city_url", return_value=""), \
                mock.patch.object(launcher.subprocess, "run",
                                  side_effect=lambda argv, **kw: argvs.append(argv) or mock.Mock(returncode=0)):
            launcher.command_update(story="848")
        sync = next(a for a in argvs if "sync-hooks" in a)
        self.assertEqual(sync[-3:], ["--commit", "--story", "848"])

    def test_a_failed_pull_installs_nothing(self):
        code, calls, _ = self.run_update(failures={"pull": 1})
        self.assertEqual((code, calls), (1, ["pull"]))

    def test_a_failed_install_does_not_refresh_dashboard(self):
        code, calls, _ = self.run_update(dashboard_changed=True, failures={"install": 1})
        self.assertEqual(code, 1)
        self.assertNotIn("page", calls)
