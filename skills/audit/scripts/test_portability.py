import atexit
import contextlib
import io
import shutil
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
    atexit.register(shutil.rmtree, root, True)
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

    def test_the_accepted_rows_file_may_name_an_address_and_no_other_file_may(self):
        quiet = repo({"README.md": "# T\n", "LICENSE": "x\n", "docs/AUDIT-ACCEPTED.md": f"Accepted: personal-email {PERSONAL} - kept\n"})
        self.assertNotIn("owner-identity", kinds(quiet))
        loud = repo({"README.md": "# T\n", "LICENSE": "x\n", "docs/NOTES.md": f"{PERSONAL}\n"})
        self.assertIn("owner-identity", kinds(loud))

    def test_a_gitignore_must_ignore_dot_env_itself(self):
        for line, ignored in ((".env.local", False), (".env", True), ("/.env", True), (".env*", True)):
            with self.subTest(line):
                root = repo({"README.md": "# T\n", "LICENSE": "x\n", ".gitignore": line + "\n"}, email=NOREPLY)
                self.assertEqual(not ignored, ("missing", ".gitignore") in {(k, w) for k, w, _ in portability.scan(root)[0]})

    def test_a_token_file_is_a_secret_and_a_tokenizer_file_is_not(self):
        for name, secret in (("gmail-token.json", True), ("credentials.json", True), ("tokenizer.json", False)):
            with self.subTest(name):
                root = repo({"README.md": "# T\n", "LICENSE": "x\n", ".gitignore": ".env\n", name: "{}\n"}, email=NOREPLY)
                self.assertEqual(secret, "secret-file" in kinds(root))

    def test_a_path_with_a_space_prints_quoted_and_a_public_key_is_not_a_secret(self):
        root = repo({"README.md": "# T\n", "LICENSE": "x\n", ".gitignore": ".env\n", "id_rsa.pub": "ssh-rsa A\n",
                     "my dir/notes.md": "cd /" + "Users/realperson/work\n"}, email=NOREPLY)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            portability.main(["portability.py", str(root)])
        self.assertIn('home-path       "my dir/notes.md"', out.getvalue())
        self.assertNotIn("secret-file", out.getvalue())

    def test_an_example_env_file_with_a_middle_word_is_not_a_secret(self):
        root = repo({"README.md": "# T\n", "LICENSE": "x\n", ".gitignore": ".env\n", ".env.local.example": "A=\n"}, email=NOREPLY)
        self.assertNotIn("secret-file", kinds(root))

    def test_a_repo_with_no_gitignore_is_missing_one(self):
        root = repo({"README.md": "# T\n", "LICENSE": "x\n"}, email=NOREPLY)
        self.assertIn((".gitignore"), {w for k, w, _ in portability.scan(root)[0] if k == "missing"})

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

    def test_history_secrets_match_any_case_and_unquoted_and_count_every_commit(self):
        files = {"README.md": "# T\n", "LICENSE": "x\n"}
        root = repo(files, email=NOREPLY)
        env = dict(ENV, GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
        for i in range(12):
            (root / "c.env").write_text("Api" + "Key=" + chr(97 + i) * 24 + "\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", str(i)], check=True, capture_output=True, env=env)
        rows = [r for r in portability.scan(root)[0] if r[0] == "history-secret"]
        self.assertEqual([("history-secret", "12-commits")], [r[:2] for r in rows])

    def test_a_branch_other_than_the_checked_out_one_is_scanned(self):
        root = repo({"README.md": "# T\n", "LICENSE": "x\n"}, email=NOREPLY)
        env = dict(ENV, GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
        run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=env)
        run("checkout", "-qb", "side")
        (root / "c.env").write_text("Api" + "Key=" + "q" * 24 + "\n")
        run("add", ".")
        run("commit", "-qm", "side")
        run("checkout", "-q", "-")
        self.assertIn("history-secret", kinds(root))

    def test_the_output_holds_no_address_secret_or_commit_hash_in_any_mode(self):
        secret = "Api" + "Key=" + "z" * 24
        root = repo({"README.md": "Contact " + PERSONAL + "\n", "LICENSE": "x\n", "c.env": secret + "\n"})
        env = dict(ENV)
        subprocess.run(["git", "-C", str(root), "rm", "-qf", "c.env"], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "drop"], check=True, capture_output=True, env=env)
        hashes = subprocess.run(["git", "-C", str(root), "log", "--all", "--format=%H"], check=True, capture_output=True, text=True).stdout.split()
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            portability.main(["portability.py", str(root)])
        self.assertIn("personal-email", shown.getvalue())
        for argv in ([str(root)], ["--time", str(root)], ["--all", str(root)], ["--help"]):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                portability.main(["portability.py", *argv])
            text = out.getvalue() + err.getvalue()
            for leak in (PERSONAL, "z" * 24, *hashes, *(h[:7] for h in hashes)):
                self.assertNotIn(leak, text, (argv, leak))

    def test_signals_name_personal_account_terms(self):
        root = repo({"README.md": "Reads Apple Notes and iCloud.\n", "LICENSE": "x\n"}, email=NOREPLY)
        self.assertIn("apple notes", portability.scan(root)[1])
