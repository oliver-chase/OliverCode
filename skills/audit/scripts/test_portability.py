import subprocess
import tempfile
import unittest
from pathlib import Path

import portability

AT = "@"
NOREPLY = "1+pat" + AT + "users.noreply.github.com"
PERSONAL = "pat" + AT + "personalmail.test2.org"

ENV = {"GIT_AUTHOR_NAME": "Pat Example", "GIT_COMMITTER_NAME": "Pat Example",
       "GIT_AUTHOR_EMAIL": PERSONAL, "GIT_COMMITTER_EMAIL": PERSONAL,
       "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def repo(files, email=None):
    root = Path(tempfile.mkdtemp())
    env = dict(ENV)
    if email:
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = email
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=env)
    run("init", "-q")
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
    run("add", ".")
    run("commit", "-qm", "init")
    return root


def kinds(root):
    return {k for k, _, _ in portability.scan(root)[0]}


class PortabilityTest(unittest.TestCase):
    def test_a_clean_shareable_repo_has_no_blockers(self):
        root = repo({"README.md": "# T\n", "LICENSE": "MIT\n", ".gitignore": ".env\n", "a.py": "x = 1\n"},
                    email=NOREPLY)
        self.assertEqual(portability.scan(root)[0], [])

    def test_finds_secret_file_home_path_and_missing_parts(self):
        root = repo({".env": "A=1\n", "a.sh": "cd /" + "Users/realperson/work\n", ".gitignore": "node_modules\n"},
                    email=NOREPLY)
        got = kinds(root)
        self.assertTrue({"secret-file", "home-path", "missing"} <= got)
        # A key file by name, and a private key that only the history holds.
        keyed = repo({"deploy/id_rsa": "x\n", "README.md": "-----BEGIN RSA " + "PRIVATE KEY-----\n"}, email=NOREPLY)
        (keyed / "README.md").write_text("# T\n")
        subprocess.run(["git", "-C", str(keyed), "commit", "-qam", "drop"], check=True, capture_output=True, env={**ENV, "GIT_AUTHOR_EMAIL": NOREPLY, "GIT_COMMITTER_EMAIL": NOREPLY})
        self.assertTrue({"secret-file", "history-secret"} <= kinds(keyed))

    def test_placeholder_home_paths_and_example_env_pass(self):
        root = repo({"README.md": "cd /" + "Users/you/repo\n", ".env.example": "A=\n", "LICENSE": "x\n"},
                    email=NOREPLY)
        self.assertNotIn("home-path", kinds(root))
        self.assertNotIn("secret-file", kinds(root))

    def test_personal_email_and_owner_identity_in_the_tree(self):
        root = repo({"README.md": "Contact " + PERSONAL + "\n", "LICENSE": "x\n"})
        got = kinds(root)
        self.assertIn("personal-email", got)
        self.assertIn("owner-identity", got)

    def test_license_file_may_name_the_author(self):
        root = repo({"README.md": "# T\n", "LICENSE": "Copyright Pat Example\n"}, email=NOREPLY)
        self.assertNotIn("owner-identity", kinds(root))

    def test_a_secret_added_in_history_is_found_even_after_removal(self):
        root = repo({"README.md": "# T\n", "LICENSE": "x\n", "c.py": "api" + "_key" + ' = "' + "abcdefghij" * 2 + '"\n'},
                    email=NOREPLY)
        env = dict(ENV, GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
        (root / "c.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(root), "commit", "-qam", "remove"], check=True, capture_output=True, env=env)
        self.assertIn("history-secret", kinds(root))

    def test_history_secrets_match_any_case_and_unquoted_and_past_ten_commits(self):
        files = {"README.md": "# T\n", "LICENSE": "x\n"}
        root = repo(files, email=NOREPLY)
        env = dict(ENV, GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
        for i in range(12):
            (root / "c.env").write_text("Api" + "Key=" + chr(97 + i) * 24 + "\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", str(i)], check=True, capture_output=True, env=env)
        rows = [r for r in portability.scan(root)[0] if r[0] == "history-secret"]
        self.assertEqual(10, len(rows))
        self.assertIn("12 commits", rows[0][2])

    def test_signals_name_personal_account_terms(self):
        root = repo({"README.md": "Reads Apple Notes and iCloud.\n", "LICENSE": "x\n"}, email=NOREPLY)
        self.assertIn("apple notes", portability.scan(root)[1])


if __name__ == "__main__":
    unittest.main()
