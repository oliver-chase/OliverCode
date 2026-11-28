"""The secret gate (Gate 1) of the pre-commit hook in every variant.

One table of file and content against the verdict. The gate prints one `BLOCKED: <file>` line per offending
file, so the clean files run once on their own to prove the exit code, and then beside every secret in one run
that must name each secret file and no clean one.
"""

from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401
__all__ = ["setUpModule", "tearDownModule"]  # unittest runs them from this module


KEY = "sk-" + "c" * 32
MIXED = "Ab3" * 8
CREDENTIALS = {
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
    "openai-project": "sk-" + "proj-" + "Ab1_" * 12,
    "password-in-url": "postgres://app:" + "hunter2hunter2" + "@db.internal:5432/app",
}
SECRETS = {
    **{f"cred-{name}.txt": value + "\n" for name, value in CREDENTIALS.items()},
    "deploy.sh": "TOKEN=ghp_" + "b" * 36 + "\n",
    "db.env": 'DB_PASSWORD="Abc!' + "defghijk" * 3 + '"\n',  # a symbol early in the value
    "id.txt": "-----BEGIN RSA " + "PRIVATE KEY-----\n",
    # A pipeline that exits early fails open on big files under pipefail, so the secret leads
    # more than a pipe buffer (64 KB) of clean lines.
    "big.py": 'KEY = "sk-' + "d" * 32 + '"\n' + "value = 1  # an ordinary line\n" * 3000,
    # No path is exempt and a placeholder word does not excuse a real key.
    **{path: f'API_KEY="{KEY}"\n' for path in ("tests/t.txt", "src/mock_client.py", "sub/.env.example")},
    "run1.sh": f'curl https://api.example.com -H "Authorization: Bearer {KEY}"\n',
    "run2.sh": f"OPENAI_KEY={KEY}  # paste your_token here\n",
    # A UUID or a hyphenated passphrase after a key name, mixed-case names, and .gitignore.
    "uuid.py": 'api_' + 'key = "' + "123e4567-e89b-12d3-a456-426614174000" + '"\n',
    "pass.py": 'pass' + 'word = "correct-horse-battery"\n',
    "a.py": f'Password = "{MIXED}"\n', "b.py": f'apiKey: "{MIXED}"\n', "c.py": f'Token="{MIXED}"\n',
    ".gitignore": f'secret = "{MIXED}"\n',
    # A real-looking secret beside a slug still blocks, and a value only partly made of x is not a run of x.
    "catalog2.json": '{"key": "my-asset-name-5x7", "api_' + 'key": "' + "Ab3dE9fGh1" + "Jk5mNp7QrS2tUv4" + '"}\n',
    "bad.py": 'api_key = "' + "Ab3" * 4 + "x" * 9 + "Cd4" * 3 + '"\n',
}
CLEAN = {
    ".env.example": 'API_KEY="sk-' + "EXAMPLE" + "0" * 20 + '"\n' f'TOKEN="{KEY}"  # secret-scan: allow\n',
    "catalog.json": '{"key": "my-asset-name-5x7", "name": "Wildflower"}\n',
    "notes.md": "This file mentions a token conceptually.\n",
    "ok.py": 'api_key = "' + "x" * 24 + '"\n',
    "clean.txt": "nothing secret here\n",
}


class TestGate1Secrets(GateHarness):
    def stage_all(self, files):
        for path, content in files.items():
            self.stage(path, content)

    def assertEachBlocked(self, out, paths):
        for path in paths:
            self.assertIn(f"BLOCKED: {path} matches secret pattern", out, f"{path} was not blocked; output:\n{out}")

    def test_clean_files_pass(self):
        self.stage_all(CLEAN)
        self.assertAllowed()

    def test_each_secret_file_and_no_clean_file_is_named(self):
        self.stage_all({**CLEAN, **SECRETS})
        out = self.assertBlocked("gate 1").stdout
        self.assertEachBlocked(out, SECRETS)
        for path in CLEAN:
            self.assertNotIn(f"BLOCKED: {path}", out)
