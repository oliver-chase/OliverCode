"""The secret gate (Gate 1) of the pre-commit hook in every variant, split from test_precommit_gates so the gate tests run in parallel.

Each blocking test stages every case under its own file name and runs the hook once. The gate prints one
`BLOCKED: <file>` line per offending file, so each case is still checked on its own while the suite pays for one hook run.
"""

import unittest

from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401


class TestGate1Secrets(GateHarness):
    def assertEachBlocked(self, cases):
        """Stage {path: content}, run the hook once and require a BLOCKED line for every path."""
        for path, content in cases.items():
            self.stage(path, content)
        out = self.assertBlocked("gate 1").stdout
        for path in cases:
            self.assertIn(f"BLOCKED: {path} matches secret pattern", out, f"{path} was not blocked; output:\n{out}")

    def test_each_credential_shape_blocks(self):
        modern = {
            "anthropic": "sk-" + "ant-api03-" + "A1b_" * 20,
            "github-fine-grained": "github" + "_pat_" + "11ABC" + "Ab3" * 20,
            "github-oauth": "gh" + "o_" + "c" * 36,
            "aws-secret-with-slashes": "aws_secret_access_key = " + "Ab/c+De" * 5 + "Ab/c+",
            "slack-webhook": "https://hooks." + "slack.com/services/T0ABC/B0DEF/" + "g" * 24,
            "gitlab": "gl" + "pat-" + "h" * 20,
            "hugging-face": "h" + "f_" + "i" * 34,
            "sendgrid": "S" + "G." + "j" * 22 + "." + "k" * 43,
            "webhook-secret": "wh" + "sec_" + "m" * 32,
            "google-oauth": "ya" + "29." + "n" * 40,
        }
        cases = {f"cred-{name}.txt": value + "\n" for name, value in modern.items()}
        cases["deploy.sh"] = "TOKEN=ghp_" + "b" * 36 + "\n"
        cases["id.txt"] = "-----BEGIN RSA " + "PRIVATE KEY-----\n"
        # A pipeline that exits early fails open on big files under pipefail.
        cases["big.py"] = ('KEY = "sk-' + "d" * 32 + '"\n') * 2000
        self.assertEachBlocked(cases)

    def test_no_path_is_exempt_and_a_placeholder_word_does_not_excuse_a_real_key(self):
        key = "sk-" + "c" * 32
        cases = {path: f'API_KEY="{key}"\n' for path in ("tests/t.txt", "src/mock_client.py", ".env.example")}
        cases["run1.sh"] = f'curl https://api.example.com -H "Authorization: Bearer {key}"\n'
        cases["run2.sh"] = f"OPENAI_KEY={key}  # paste your_token here\n"
        self.assertEachBlocked(cases)

    def test_only_the_files_that_carry_a_secret_are_named(self):
        # The combined prefilter skips a file that matches no pattern, so a clean neighbour is never named.
        self.stage("clean.txt", "nothing secret here\n")
        self.stage("dirty.txt", "TOKEN=ghp_" + "b" * 36 + "\n")
        out = self.assertBlocked("gate 1").stdout
        self.assertIn("BLOCKED: dirty.txt", out)
        self.assertNotIn("BLOCKED: clean.txt", out)

    def test_a_placeholder_value_or_an_allow_line_passes(self):
        key = "sk-" + "c" * 32
        self.stage(".env.example", 'API_KEY="sk-' + "EXAMPLE" + "0" * 20 + '"\n'
                   f'TOKEN="{key}"  # secret-scan: allow\n')
        self.assertAllowed()

    def test_ordinary_prose_passes(self):
        self.stage("notes.md", "This file mentions a token conceptually.\n")
        self.assertAllowed()


if __name__ == "__main__":
    unittest.main()


class TestGateSecretsNames(GateHarness):
    def test_mixed_case_names_and_gitignore_are_scanned(self):
        value = "Ab3" * 8
        cases = {"a.py": f'Password = "{value}"\n', "b.py": f'apiKey: "{value}"\n',
                 "c.py": f'Token="{value}"\n', ".gitignore": f'secret = "{value}"\n'}
        for path, content in cases.items():
            self.stage(path, content)
        out = self.assertBlocked("gate 1").stdout
        for path in cases:
            self.assertIn(f"BLOCKED: {path} matches secret pattern", out)

    def test_a_run_of_x_exempts_only_a_value_made_of_x(self):
        self.stage("ok.py", 'api_key = "' + "x" * 24 + '"\n')
        self.assertAllowed()
        self.stage("bad.py", 'api_key = "' + "Ab3" * 4 + "x" * 9 + "Cd4" * 3 + '"\n')
        self.assertBlocked("gate 1")
