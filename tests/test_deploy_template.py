"""The deploy template ships as a template only: it deploys nothing until a repo copies and fills it."""

import re
import unittest

from _support import REPO_ROOT

TEMPLATE = REPO_ROOT / "core" / "templates" / "deploy" / "deploy.yml.tmpl"


class DeployTemplate(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def test_it_is_not_a_live_workflow_or_stamped_by_bootstrap(self):
        self.assertFalse(list((REPO_ROOT / ".github" / "workflows").glob("deploy*")))
        manifest = (REPO_ROOT / "shared" / "project-bootstrap-manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("deploy", manifest)

    def test_it_validates_then_deploys_checks_rolls_back_and_files_a_p0(self):
        for needle in ("needs: validate", "environment: production", "__ROLLBACK_COMMAND__", "gh issue create", "P0:"):
            self.assertIn(needle, self.text)

    def test_every_placeholder_is_documented_in_the_header(self):
        header = self.text.split("name: Deploy", 1)[0]
        for token in set(re.findall(r"__[A-Z_]+__", self.text)):
            self.assertIn(token, header)

    def test_actions_are_pinned_to_a_commit(self):
        for ref in re.findall(r"uses: \S+@(\S+)", self.text):
            self.assertRegex(ref, r"^[0-9a-f]{40}$")



if __name__ == "__main__":
    unittest.main()
