"""One protocol on every machine: conform compares each machine recorded in a repo with the newest version, the gates and the policy (#740)."""

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from _support import load_script, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import conform, features, machines  # noqa: E402  (load_script put scripts/ on the path)


class MachinesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-machines-")
        self.repo = self.tmp / "widgets"
        (self.repo / ".olivercode").mkdir(parents=True)
        (self.repo / ".olivercode" / "policy.json").write_text("{}")
        self.oc = self.tmp / "oc"
        self.oc.mkdir()
        (self.oc / "VERSION").write_text("1.2.0\n")

    def write(self, name, version="1.2.0", hooks=True, policy=True):
        folder = machines.folder(self.repo)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.json").write_text(json.dumps({"machine": name, "version": version, "hooks": hooks, "policy": policy}))

    def row(self):
        return conform.machines(self.repo, oc_root=self.oc)


class TestMachines(MachinesBase):
    def test_a_second_machine_a_version_behind_fails_and_is_named(self):
        self.write("studio")
        self.write("mini", version="1.1.0")
        row = self.row()
        self.assertEqual("fail", row.status)
        self.assertIn("mini runs version 1.1.0, behind 1.2.0", row.detail)
        self.assertNotIn("studio", row.detail)

    def test_a_second_machine_without_the_permission_policy_fails_and_is_named(self):
        self.write("studio")
        self.write("mini", policy=False)
        row = self.row()
        self.assertEqual("fail", row.status)
        self.assertIn("mini lacks the permission policy", row.detail)
        self.assertIn("olivercode policy init", row.fix)

    def test_a_machine_with_no_gates_fails(self):
        self.write("mini", hooks=False)
        self.assertIn("mini has no commit gates", self.row().detail)

    def test_machines_on_the_same_protocol_pass_and_a_repo_with_none_passes(self):
        self.assertEqual("pass", self.row().status)
        self.write("studio")
        self.write("mini")
        row = self.row()
        self.assertEqual(("pass", "2 machine(s) recorded"), (row.status, row.detail))

    def test_a_record_ahead_of_the_checking_machine_makes_the_checking_machine_behind_no_one_else(self):
        self.write("mini", version="1.3.0")
        self.write("studio")
        self.assertIn("studio runs version 1.2.0, behind 1.3.0", self.row().detail)

    def test_an_unreadable_record_fails_by_its_file_name(self):
        folder = machines.folder(self.repo)
        folder.mkdir(parents=True)
        (folder / "broken.json").write_text("{")
        self.assertIn("broken", self.row().detail)
        self.assertEqual("fail", self.row().status)

    def test_conform_runs_the_machines_row(self):
        self.assertIn(conform.machines, conform.CHECKS)

    def test_record_writes_this_machines_state_and_show_reports_a_difference(self):
        path = machines.record(self.repo, "mini", oc_root=self.oc, hooks=True, today=date(2026, 11, 22))
        self.assertEqual({"machine": "mini", "version": "1.2.0", "hooks": True, "policy": True, "recorded": "2026-11-22"}, json.loads(path.read_text()))
        (self.repo / ".olivercode" / "policy.json").unlink()
        machines.record(self.repo, "air", oc_root=self.oc, hooks=True)
        lines = []
        with redirect_stdout(io.StringIO()):
            rc = machines.command_machines(["show", "--repo", str(self.repo)], out=lines.append, oc_root=self.oc)
        self.assertEqual(1, rc)
        self.assertIn("[DIFFERS] air lacks the permission policy", "\n".join(lines))

    def test_the_command_refuses_unknown_input(self):
        lines = []
        self.assertEqual(1, machines.command_machines([], out=lines.append))
        self.assertEqual(1, machines.command_machines(["show", "--bogus", "x"], out=lines.append))


class TestRegisterMachineField(unittest.TestCase):
    def test_every_register_row_names_each_or_single_and_a_single_row_gives_a_reason(self):
        for row in features.load():
            self.assertIn(row.get("machine"), features.MACHINES, row["id"])
            if row["machine"] == "single":
                self.assertTrue(row.get("single_reason", "").strip(), row["id"])
        self.assertEqual({"owner-queue", "burndown"}, {r["id"] for r in features.load() if r["machine"] == "single"})

    def test_a_single_machine_row_with_no_reason_is_refused(self):
        bad = [{"id": "owner-queue", "title": "Owner queue", "check": "c", "enable": "e", "owner_only": False, "freshness": "exists", "explain": "x", "machine": "single"}]
        with self.assertRaises(ValueError) as ctx:
            features.evaluate(Path("."), rows=bad)
        self.assertIn("single_reason", str(ctx.exception))

    def test_an_unknown_machine_value_is_refused(self):
        bad = [{"id": "owner-queue", "title": "Owner queue", "check": "c", "enable": "e", "owner_only": False, "freshness": "exists", "explain": "x", "machine": "some"}]
        with self.assertRaises(ValueError):
            features.evaluate(Path("."), rows=bad)


if __name__ == "__main__":
    unittest.main()
