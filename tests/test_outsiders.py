"""olivercode maintain queues an issue or pull request by an author outside the allowed list, once (#826)."""

import json
import unittest
from unittest import mock

from _maintain_case import Base
from lib import cmd_owner, outsiders


def item(number, author, title="An idea", state="open", pr=False):
    out = {"number": number, "title": title, "state": state, "user": {"login": author},
           "html_url": f"https://github.com/o/r/{'pull' if pr else 'issues'}/{number}"}
    return {**out, "pull_request": {}} if pr else out


class TestOutsiders(Base):
    def run_check(self, found, allowed=("owner", "bot")):
        with mock.patch.object(outsiders, "allowed", return_value=set(allowed)), \
                mock.patch.object(outsiders, "recent", return_value=found):
            outsiders.check([("Repo", "o/r")])

    def steps(self):
        return [i["step"] for i in cmd_owner.items()]

    def test_another_author_is_queued_with_number_author_and_link_and_never_the_title(self):
        self.run_check([item(720, "Outsider-a", "Add a thing", state="closed")])
        (step,) = self.steps()
        for part in ("o/r#720", "Outsider-a", "https://github.com/o/r/issues/720"):
            self.assertIn(part, step)
        self.assertNotIn("Add a thing", step)

    def test_a_pull_request_by_another_author_is_queued(self):
        self.run_check([item(9, "stranger", pr=True)])
        self.assertIn("https://github.com/o/r/pull/9", self.steps()[0])

    def test_an_allowed_author_is_ignored_whatever_the_case(self):
        self.run_check([item(1, "OWNER"), item(2, "bot")])
        self.assertEqual([], self.steps())

    def test_a_second_run_adds_nothing_even_after_the_owner_closed_the_line(self):
        self.run_check([item(720, "outsider-a")])
        self.run_check([item(720, "outsider-a")])
        self.assertEqual(1, len(self.steps()))
        cmd_owner.close(cmd_owner.items()[0]["id"])
        self.run_check([item(720, "outsider-a")])
        self.assertEqual(1, len(self.steps()))

    def test_no_allowed_authors_means_the_check_is_off(self):
        with mock.patch.object(outsiders, "recent") as recent:
            self.run_check([item(1, "x")], allowed=())
            recent.assert_not_called()
        self.assertEqual([], self.steps())

    def test_allowed_authors_come_from_the_local_config(self):
        with mock.patch.object(outsiders, "load_local", return_value={"allowedAuthors": ["A", "b"]}):
            self.assertEqual({"a", "b"}, outsiders.allowed())

    def test_recent_reads_open_and_recently_closed_through_rest(self):
        rows = [item(1, "x"), item(2, "y", state="closed")]
        with mock.patch.object(outsiders.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="\n".join(json.dumps(r) for r in rows))
            self.assertEqual([1, 2], [r["number"] for r in outsiders.recent("o/r")])
            args = run.call_args[0][0]
        self.assertNotIn("graphql", args)
        self.assertTrue(any("state=all" in a and "since=" in a for a in args))


if __name__ == "__main__":
    unittest.main()
