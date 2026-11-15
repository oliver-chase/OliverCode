"""`olivercode backlog-setup` and the board part of `olivercode conform`, offline.

A fake GitHub answers the GraphQL calls `lib/backlog_setup.py` makes, so no test reaches the network. The fake
can behave like the real API (an option sent with its id keeps its item values) or like the destructive case
(an update clears every value), which is how the snapshot and restore path gets tested.
"""

import contextlib
import io
import itertools
import json
import re
import unittest

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir

backlog_setup = load_script("scripts/lib/backlog_setup.py")
launcher = load_script("scripts/olivercode", "olivercode_launcher_setup")
kanban = backlog_setup.kanban

OPTION = re.compile(r'\{(?:id:"([^"]*)",)?name:"((?:[^"\\]|\\.)*)",color:(\w+),description:"((?:[^"\\]|\\.)*)"\}')
SET_VALUE = re.compile(r'updateProjectV2ItemFieldValue\(input:\{projectId:"([^"]+)",itemId:"([^"]+)",fieldId:"([^"]+)",'
                       r'value:\{singleSelectOptionId:"([^"]+)"\}')


class FakeGitHub:
    """The slice of GitHub Projects the setup command uses."""

    def __init__(self, preserve_ids=True, refuse_sets=False, rate_limit_after=None):
        self.projects = {}
        self.counter = itertools.count(1)
        self.preserve_ids = preserve_ids
        self.refuse_sets = refuse_sets
        self.rate_limit_after = rate_limit_after
        self.log = []
        self.writes = []

    def uid(self, prefix):
        return f"{prefix}{next(self.counter):04d}"

    def add_project(self, title="Board", owner="acme", statuses=("Todo", "In Progress", "Done")):
        pid = self.uid("PVT_")
        project = {"id": pid, "number": len(self.projects) + 1, "title": title, "owner": owner, "fields": [], "items": []}
        project["fields"].append({"id": self.uid("PVTF_"), "name": "Title", "type": "ProjectV2Field", "options": []})
        self.add_field(project, "Status", statuses)
        self.projects[pid] = project
        return project

    def add_field(self, project, name, options):
        field = {"id": self.uid("PVTSSF_"), "name": name, "type": "ProjectV2SingleSelectField",
                 "options": [{"id": self.uid("opt"), "name": n, "color": "GRAY", "description": ""} for n in options]}
        project["fields"].append(field)
        return field

    def field(self, project, name):
        return next(f for f in project["fields"] if f["name"] == name)

    def add_item(self, project, title, **values):
        item = {"id": self.uid("PVTI_"), "title": title, "number": len(project["items"]) + 1, "values": {}}
        for name, option in values.items():
            self.set_value(project, item, self.field(project, name.replace("_", " ")), option)
        project["items"].append(item)
        return item

    def set_value(self, project, item, field, option_name):
        item["values"][field["id"]] = next(o["id"] for o in field["options"] if o["name"] == option_name)

    def value_names(self, project):
        out = {}
        for it in project["items"]:
            out[it["title"]] = {}
            for f in project["fields"]:
                if f["id"] in it["values"]:
                    out[it["title"]][f["name"]] = next(o["name"] for o in f["options"] if o["id"] == it["values"][f["id"]])
        return out

    # the runner the Api calls
    def runner(self, args, stdin=None):
        variables = {args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1] for i in range(2, len(args) - 1, 2)}
        query = args[3].split("=", 1)[1]
        self.log.append(query)
        if self.rate_limit_after is not None and len(self.log) > self.rate_limit_after:
            return 1, json.dumps({"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}), ""
        try:
            return 0, json.dumps({"data": self.handle(query, variables)}), ""
        except KeyError as exc:
            return 1, json.dumps({"errors": [{"message": f"not found: {exc}"}]}), ""

    def handle(self, q, v):
        if q.startswith("mutation"):
            self.writes.append(q)
            return self.mutate(q, v)
        if "projectsV2(" in q:
            nodes = [{"id": p["id"], "number": p["number"], "title": p["title"], "closed": p.get("closed", False)}
                     for p in self.projects.values() if v["t"].lower() in p["title"].lower()]
            return {"repositoryOwner": {"projectsV2": {"nodes": nodes}}}
        if "repositoryOwner(login" in q:
            return {"repositoryOwner": {"id": "OWNER1"}}
        if "repository(owner" in q:
            return {"repository": {"id": "REPO1"}}
        project = self.projects.get(v["p"])
        if "fields(first:100)" in q:
            if not project:
                return {"node": None}
            return {"node": {"id": project["id"], "title": project["title"], "number": project["number"],
                             "owner": {"login": project["owner"]},
                             "fields": {"nodes": [{"__typename": f["type"], "id": f["id"], "name": f["name"],
                                                   "dataType": "SINGLE_SELECT", **({"options": f["options"]} if f["options"] else {})}
                                                  for f in project["fields"]]}}}
        if "items(first:100" in q:
            nodes = []
            for it in project["items"]:
                values = []
                for f in project["fields"]:
                    if f["id"] in it["values"]:
                        o = next(o for o in f["options"] if o["id"] == it["values"][f["id"]])
                        values.append({"optionId": o["id"], "name": o["name"], "field": {"id": f["id"], "name": f["name"]}})
                nodes.append({"id": it["id"], "content": {"number": it["number"], "title": it["title"]},
                              "fieldValues": {"nodes": values}})
            return {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}
        raise KeyError(q[:60])

    def mutate(self, q, v):
        if "createProjectV2(" in q:
            project = self.add_project(title=v["t"], owner="acme")
            return {"createProjectV2": {"projectV2": {"id": project["id"], "number": project["number"], "title": project["title"]}}}
        if "linkProjectV2ToRepository" in q:
            return {"linkProjectV2ToRepository": {"repository": {"id": "REPO1"}}}
        if "createProjectV2Field(" in q:
            project = self.projects[re.search(r'projectId:"([^"]+)"', q).group(1)]
            name = re.search(r'name:"([^"]+)",singleSelectOptions', q).group(1)
            self.add_field(project, name, [m[1] for m in OPTION.findall(q)])
            return {}
        if "updateProjectV2Field(" in q:
            field = next(f for p in self.projects.values() for f in p["fields"] if f["id"] == re.search(r'fieldId:"([^"]+)"', q).group(1))
            project = next(p for p in self.projects.values() if field in p["fields"])
            new = []
            for oid, name, color, desc in OPTION.findall(q):
                keep = oid and self.preserve_ids
                new.append({"id": oid if keep else self.uid("opt"), "name": name, "color": color, "description": desc})
            kept = {o["id"] for o in new}
            for it in project["items"]:
                if field["id"] in it["values"] and it["values"][field["id"]] not in kept:
                    del it["values"][field["id"]]
            field["options"] = new
            return {}
        if "updateProjectV2ItemFieldValue" in q:
            for pid, item_id, field_id, option_id in SET_VALUE.findall(q):
                if self.refuse_sets:
                    continue
                item = next(i for i in self.projects[pid]["items"] if i["id"] == item_id)
                item["values"][field_id] = option_id
            return {}
        raise KeyError(q[:60])


class SetupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-setup-")
        self.repo = scratch_repo(self.tmp / "widgets")
        git(self.repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
        self.fake = FakeGitHub()
        self.lines = []

    def run_setup(self, apply=True, fake=None, **kw):
        fake = fake or self.fake
        self.lines = []
        code = backlog_setup.run_setup(self.repo, apply, backlog_setup.Api(fake.runner), out=self.lines.append, **kw)
        return code

    @property
    def text(self):
        return "\n".join(self.lines)

    def config(self):
        return json.loads((self.repo / "docs" / "backlog-config.json").read_text())

    def seed_existing_board(self):
        project = self.fake.add_project(title="widgets")
        priority = self.fake.add_field(project, "Priority", ["P0", "P1", "P2"])
        size = self.fake.add_field(project, "Size", ["XS", "S", "M", "L", "XL"])
        self.fake.add_field(project, "Work Type", ["Epic", "Story"])
        self.fake.add_item(project, "one", Status="Todo", Priority="P0", Size="XL", Work_Type="Epic")
        self.fake.add_item(project, "two", Status="In Progress", Priority="P1", Size="S", Work_Type="Story")
        self.fake.add_item(project, "three", Status="Done", Priority="P2", Size="M", Work_Type="Story")
        self.fake.add_item(project, "four", Status="Todo")
        (self.repo / "docs").mkdir()
        backlog_setup.write_config(self.repo / "docs" / "backlog-config.json",
                                   backlog_setup.config_from_board(self.fake.projects[project["id"]] | {"owner": "acme"}, "acme", "widgets", None))
        return project


class TestNewRepo(SetupCase):
    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        self.assertEqual(0, self.run_setup(apply=False))
        self.assertEqual({}, self.fake.projects)
        self.assertEqual([], self.fake.writes)
        self.assertFalse((self.repo / "docs" / "backlog-config.json").exists())
        self.assertFalse((self.repo / ".githooks" / "commit-msg").exists())
        self.assertIn("widgets", self.text)
        self.assertIn("commit-msg", self.text)
        self.assertIn("--apply", self.text)

    def test_apply_builds_everything_and_the_baseline_passes(self):
        self.assertEqual(0, self.run_setup())
        project = next(iter(self.fake.projects.values()))
        self.assertEqual("widgets", project["title"])
        self.assertEqual([], kanban.check_baseline(backlog_setup.gh_field_list(project), kanban.load_baseline(), self.config()))
        config = self.config()
        self.assertEqual(project["id"], config["projectId"])
        status = self.fake.field(project, "Status")
        self.assertEqual({o["name"]: o["id"] for o in status["options"]}, config["fields"]["status"]["options"])
        self.assertEqual(["Backlog", "Ready", "In Progress", "QA", "Complete"], [o["name"] for o in status["options"]])
        self.assertEqual([], backlog_setup.config_problems(config, backlog_setup.read_board(backlog_setup.Api(self.fake.runner), project["id"])))
        self.assertIn("The board matches", self.text)

    def test_apply_installs_the_hook(self):
        self.run_setup()
        self.assertEqual("", backlog_setup.commit_msg_problem(self.repo, REPO_ROOT))
        self.assertEqual(".githooks", git(self.repo, "config", "--get", "core.hooksPath").stdout.strip())

    def test_a_second_run_changes_nothing_and_says_so(self):
        self.run_setup()
        before = {p.name: p.read_bytes() for p in self.repo.rglob("*") if p.is_file() and ".git/" not in str(p)}
        writes = len(self.fake.writes)
        self.assertEqual(0, self.run_setup())
        self.assertIn("Nothing to change", self.text)
        self.assertEqual(writes, len(self.fake.writes))
        self.assertEqual(1, len(self.fake.projects))
        after = {p.name: p.read_bytes() for p in self.repo.rglob("*") if p.is_file() and ".git/" not in str(p)}
        self.assertEqual(before, after)
        self.assertEqual(0, self.run_setup(apply=False))
        self.assertIn("Nothing to change", self.text)

    def test_a_project_created_before_a_stop_is_found_again(self):
        flaky = FakeGitHub(rate_limit_after=4)
        self.assertEqual(1, self.run_setup(fake=flaky))
        self.assertIn("rate limit", self.text)
        self.assertEqual(1, len(flaky.projects))
        flaky.rate_limit_after = None
        self.assertEqual(0, self.run_setup(fake=flaky))
        self.assertEqual(1, len(flaky.projects))


class TestProjectAlreadyExists(SetupCase):
    def seed(self, **extra):
        project = self.fake.add_project(title="widgets")
        project.update(extra)
        return project

    def test_a_dry_run_plans_the_config_for_the_existing_project_and_no_second_one(self):
        self.seed()
        self.assertEqual(0, self.run_setup(apply=False))
        self.assertIn("existing 'widgets'", self.text)
        self.assertNotIn("create the Project", self.text)
        self.assertIn("write docs/backlog-config.json for the existing Project", self.text)
        self.assertEqual([], self.fake.writes)

    def test_apply_writes_the_config_for_that_project_and_creates_nothing(self):
        project = self.seed()
        self.run_setup()
        self.assertEqual(1, len(self.fake.projects))
        self.assertEqual(project["id"], self.config()["projectId"])

    def test_a_closed_project_with_the_name_is_not_reused(self):
        self.seed(closed=True)
        self.run_setup(apply=False)
        self.assertIn("create the Project 'widgets'", self.text)

    def test_two_open_projects_with_the_name_stop_for_the_owner(self):
        self.seed()
        self.seed()
        self.assertEqual(1, self.run_setup(apply=False))
        self.assertIn("2 open Projects named 'widgets'", self.text)


class TestExistingBoard(SetupCase):
    def test_repair_keeps_every_value_and_option_id(self):
        project = self.seed_existing_board()
        ids_before = {o["name"]: o["id"] for o in self.fake.field(project, "Status")["options"]}
        self.assertEqual(0, self.run_setup())
        names = self.fake.value_names(project)
        self.assertEqual({"Status": "Backlog", "Priority": "P0", "Size": "XL", "Work Type": "Epic"}, names["one"])
        self.assertEqual({"Status": "In Progress", "Priority": "P1", "Size": "S", "Work Type": "Story"}, names["two"])
        self.assertEqual("Complete", names["three"]["Status"])
        self.assertEqual({"Status": "Backlog"}, names["four"])
        status = {o["name"]: o["id"] for o in self.fake.field(project, "Status")["options"]}
        self.assertEqual(ids_before["Todo"], status["Backlog"])
        self.assertEqual(ids_before["Done"], status["Complete"])
        self.assertEqual([], kanban.check_baseline(backlog_setup.gh_field_list(project), kanban.load_baseline(), self.config()))
        self.assertEqual(0, self.run_setup())
        self.assertIn("Nothing to change", self.text)

    def test_snapshot_is_written_before_the_change(self):
        project = self.seed_existing_board()
        self.run_setup()
        files = list((self.repo / "scratch" / "backlog-backups").glob("backlog-snapshot-*.json"))
        self.assertEqual(1, len(files))
        snap = json.loads(files[0].read_text())
        self.assertEqual(4, snap["itemCount"])
        self.assertEqual({"Todo": 2, "In Progress": 1, "Done": 1}, snap["counts"]["status"])
        self.assertEqual({"P0": 1, "P1": 1, "P2": 1}, snap["counts"]["priority"])
        self.assertEqual({"Epic": 1, "Story": 2}, snap["counts"]["workType"])
        self.assertEqual("one", snap["items"][0]["title"])

    def test_a_destructive_update_is_restored_from_the_snapshot(self):
        self.fake.preserve_ids = False
        project = self.seed_existing_board()
        self.assertEqual(0, self.run_setup())
        names = self.fake.value_names(project)
        self.assertEqual({"Status": "Backlog", "Priority": "P0", "Size": "XL", "Work Type": "Epic"}, names["one"])
        self.assertEqual("Complete", names["three"]["Status"])
        self.assertIn("restored", self.text)
        self.assertEqual([], backlog_setup.config_problems(self.config(), backlog_setup.read_board(backlog_setup.Api(self.fake.runner), project["id"])))

    def test_a_restore_that_does_not_hold_exits_non_zero(self):
        self.fake.preserve_ids = False
        self.fake.refuse_sets = True
        self.seed_existing_board()
        self.assertEqual(1, self.run_setup())
        self.assertIn("do not match the snapshot", self.text)
        self.assertIn("backlog-snapshot-", self.text)

    def test_an_option_outside_the_baseline_is_kept_and_reported(self):
        project = self.seed_existing_board()
        self.fake.field(project, "Status")["options"].append({"id": "optX", "name": "In Review", "color": "GRAY", "description": ""})
        self.fake.add_item(project, "five", Status="In Review")
        self.assertEqual(1, self.run_setup())
        self.assertIn("In Review", self.text)
        self.assertEqual("In Review", self.fake.value_names(project)["five"]["Status"])

    def test_another_repos_config_is_refused(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps(
            {"repoOwner": "other-owner", "repoName": "other-repo", "projectOwner": "other-owner", "projectNumber": 15,
             "projectId": "PVT_x", "fields": {}}))
        self.assertEqual(1, self.run_setup())
        self.assertIn("another repo's config", self.text)
        self.assertEqual([], self.fake.log)

    def test_a_missing_origin_stops_with_the_fix(self):
        git(self.repo, "remote", "remove", "origin")
        self.assertEqual(1, self.run_setup())
        self.assertIn("no origin remote", self.text)


class TestPlanning(unittest.TestCase):
    def test_existing_options_keep_their_ids_and_colors(self):
        existing = [{"id": "a", "name": "Todo", "color": "RED", "description": "d"}, {"id": "b", "name": "Done", "color": "BLUE", "description": ""}]
        plan = backlog_setup.plan_options(existing, ["Backlog", "Ready", "Complete"], backlog_setup.DEFAULT_STATUS_MAP)
        self.assertEqual(["a", None, "b"], [o.get("id") for o in plan["final"]])
        self.assertEqual("RED", plan["final"][0]["color"])
        self.assertEqual([("Todo", "Backlog"), ("Done", "Complete")], plan["renamed"])
        self.assertEqual(["Ready"], plan["added"])

    def test_a_mapped_option_merges_into_an_existing_target(self):
        existing = [{"id": "a", "name": "Backlog"}, {"id": "b", "name": "Todo"}]
        plan = backlog_setup.plan_options(existing, ["Backlog"], backlog_setup.DEFAULT_STATUS_MAP)
        self.assertEqual(["Todo"], plan["dropped"])
        self.assertEqual({"Todo": "Backlog"}, plan["remap"])
        self.assertEqual(["a"], [o["id"] for o in plan["final"]])



class TestHealth(SetupCase):
    def health(self):
        lines = []
        result = backlog_setup.boards_health([("widgets", self.repo)], backlog_setup.Api(self.fake.runner), REPO_ROOT, out=lines.append)
        return result, "\n".join(lines)

    def test_a_checkout_with_no_origin_remote_skips_the_board_check(self):
        self.run_setup()
        git(self.repo, "remote", "remove", "origin")
        (passed, failed, skipped), text = self.health()
        self.assertEqual((0, 0, 1), (passed, failed, skipped))
        self.assertIn("[WARN] widgets: board check skipped", text)
        self.assertIn("no origin remote", text)

    def test_a_fork_whose_origin_differs_from_the_config_still_fails(self):
        self.run_setup()
        git(self.repo, "remote", "set-url", "origin", "https://github.com/someone/fork.git")
        (passed, failed, skipped), text = self.health()
        self.assertEqual(1, failed)
        self.assertIn("names another repo's Project", text)

    def test_a_bare_file_name_in_prose_does_not_hide_the_real_config_path(self):
        self.run_setup()
        (self.repo / "CLAUDE.md").write_text("A repo that names a `backlog-config.json` files stories.\nThe board is `docs/backlog-config.json`.\n")
        self.assertEqual(self.repo / "docs" / "backlog-config.json", backlog_setup.config_path(self.repo))

    def test_a_repo_with_no_config_fails_with_the_fix_command(self):
        (passed, failed, skipped), text = self.health()
        self.assertEqual(1, failed)
        self.assertIn("no usable backlog config", text)
        self.assertIn(f"Fix: olivercode backlog-setup {self.repo} --apply", text)

    def test_a_repo_off_the_baseline_is_listed(self):
        self.seed_existing_board()
        (passed, failed, skipped), text = self.health()
        self.assertEqual(1, failed)
        self.assertIn("missing option", text)
        self.assertIn("no commit-msg hook", text)
        self.assertIn("backlog-setup", text)

    def test_a_set_up_repo_passes(self):
        self.run_setup()
        (passed, failed, skipped), text = self.health()
        self.assertEqual((1, 0, 0), (passed, failed, skipped))
        self.assertIn("[OK]", text)

    def test_an_unreadable_board_is_a_warning(self):
        self.run_setup()
        down = FakeGitHub(rate_limit_after=0)
        lines = []
        result = backlog_setup.boards_health([("widgets", self.repo)], backlog_setup.Api(down.runner), REPO_ROOT, out=lines.append)
        self.assertEqual((0, 0, 1), result)
        self.assertIn("board not read", "\n".join(lines))


class TestLauncher(SetupCase):
    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = launcher.command_backlog_setup(list(argv))
        return code, buf.getvalue()

    def test_unknown_directory_and_flags_are_rejected(self):
        self.assertEqual(1, self.call(str(self.tmp / "nope"))[0])
        self.assertEqual(1, self.call(str(self.repo), "--bogus")[0])



class PagingAndConfigChecks(unittest.TestCase):
    """read_items follows every page, and config_problems names each kind of mismatch."""

    def test_read_items_reads_every_page(self):
        pages = {None: ("c1", True, 1), "c1": (None, False, 2)}

        class Api:
            def graphql(self, query, **kw):
                cursor, more, n = pages[kw["c"]]
                return {"node": {"items": {"pageInfo": {"hasNextPage": more, "endCursor": cursor},
                                           "nodes": [{"id": f"I{n}", "content": {"number": n}}]}}}
        self.assertEqual([1, 2], [i["number"] for i in backlog_setup.read_items(Api(), "P")])

    def test_config_problems_names_each_mismatch(self):
        board = {"id": "P", "fields": [{"id": "F", "options": [{"name": "Ready", "id": "R"}, {"name": "QA", "id": "Q"}]}]}
        good = {"projectId": "P", "fields": {"status": {"id": "F", "options": {"Ready": "R", "QA": "Q"}}}}
        self.assertEqual([], backlog_setup.config_problems(good, board))
        cases = {
            "projectId differs": {**good, "projectId": "X"},
            "is not on the board": {**good, "fields": {"status": {"id": "G", "options": {}}}},
            "option Ready id does not match": {**good, "fields": {"status": {"id": "F", "options": {"Ready": "Z", "QA": "Q"}}}},
            "board option QA is missing": {**good, "fields": {"status": {"id": "F", "options": {"Ready": "R"}}}},
        }
        for words, config in cases.items():
            with self.subTest(words):
                self.assertTrue(any(words in p for p in backlog_setup.config_problems(config, board)))


if __name__ == "__main__":
    unittest.main()
