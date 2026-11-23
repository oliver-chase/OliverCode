"""Every com.olivercode launchd job gets a PATH that holds gh, because launchd's default PATH lacks it."""

import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib import cmd_boardsweep, cmd_ghreplay, launchd, maintain  # noqa: E402


@unittest.skipUnless(sys.platform == "darwin", "launchd exists only on macOS")
class TestJobPath(unittest.TestCase):
    def installed(self, module):
        home = Path(tempfile.mkdtemp())
        with mock.patch.object(launchd.shutil, "which", return_value="/opt/homebrew/bin/gh"), \
                mock.patch.object(launchd.subprocess, "run") as run, mock.patch.object(Path, "home", return_value=home), \
                mock.patch.dict("os.environ", {"OLIVERCODE_HOME": str(home)}):
            run.return_value.returncode = 0
            with mock.patch("builtins.print"):
                module.schedule(True)
        (plist,) = (home / "Library" / "LaunchAgents").glob("com.olivercode.*.plist")
        return plistlib.loads(plist.read_bytes())

    def test_a_job_built_by_launchd_job_runs_with_the_folder_holding_gh(self):
        self.assertEqual("/opt/homebrew/bin", self.installed(cmd_boardsweep)["EnvironmentVariables"]["PATH"].split(":")[0])

    def test_a_job_with_its_own_plist_builder_runs_with_the_folder_holding_gh(self):
        for module in (cmd_ghreplay, maintain):
            self.assertEqual("/opt/homebrew/bin", self.installed(module)["EnvironmentVariables"]["PATH"].split(":")[0])

    def test_the_path_names_the_usual_folders_when_gh_is_not_found(self):
        with mock.patch.object(launchd.shutil, "which", return_value=None):
            self.assertEqual(["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"], launchd.job_path().split(":"))


class TestSchedulingOffMac(unittest.TestCase):
    def run_schedule(self, module, on=True):
        out = []
        with mock.patch.object(launchd.sys, "platform", "linux"), mock.patch.object(launchd.subprocess, "run") as run, \
                mock.patch("builtins.print", side_effect=lambda *a: out.append(" ".join(map(str, a)))):
            code = module.schedule(on)
        self.assertFalse([c for c in run.call_args_list if c.args and c.args[0][0] == "launchctl"])
        return code, "\n".join(out)

    def test_every_schedule_prints_the_cron_line_and_exits_one_without_launchctl(self):
        code, out = self.run_schedule(cmd_boardsweep)
        self.assertEqual(1, code)
        self.assertIn("*/30 * * * * ", out)
        self.assertIn("board sync", out)

    def test_a_calendar_job_becomes_a_daily_cron_line(self):
        line = launchd.cron_line({"ProgramArguments": ["py", "oc", "x"], "StartCalendarInterval": {"Hour": 3, "Minute": 30}, "StandardOutPath": "/l/x.out"})
        self.assertEqual("30 3 * * * py oc x >> /l/x.out 2>&1", line)

    def test_unscheduling_names_the_cron_line_to_delete(self):
        code, out = self.run_schedule(cmd_boardsweep, on=False)
        self.assertEqual(1, code)
        self.assertIn("crontab -e", out)


if __name__ == "__main__":
    unittest.main()
