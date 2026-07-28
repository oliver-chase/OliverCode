"""Tests for the comment-budget gate.

It is fatal in six repos and had no test anywhere. A QA pass found the
correspondence half nearly inert -- `^` anchored to a joined block that always
starts with a comment marker, so it could never match, and the canonical return
claims all passed a function returning nothing. The same pass found it failing
FATALLY on correct destructured JSDoc.

Every case below is a regression from that pass. They run the real script
against a real throwaway git repo, because the script reads `git ls-files`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "templates" / "project" / "scripts" / "check-comment-budget.mjs"


def _node() -> str | None:
    return shutil.which("node")


class CommentBudgetGateTests(unittest.TestCase):
    """Each test writes fixtures into a throwaway repo and runs the gate on it."""

    def setUp(self) -> None:
        if not _node():
            self.skipTest("node not available")
        self.tmp = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gate(self, *args: str) -> subprocess.CompletedProcess:
        subprocess.run(["git", "add", "-A"], cwd=self.tmp, capture_output=True)
        return subprocess.run(
            ["node", str(SCRIPT), *args], cwd=self.tmp, capture_output=True, text=True
        )

    def write(self, name: str, body: str) -> None:
        (Path(self.tmp) / name).write_text(body, encoding="utf-8")

    # ── correspondence: the half that was inert ──────────────────────────────

    def test_return_claim_on_its_own_line_is_caught(self):
        self.write("a.js", "// Returns true when the token was stored.\nfunction hide(x) { x.hidden = true; }\n")
        self.assertIn("comment states a return value", self.run_gate().stdout)

    def test_return_claim_in_a_one_line_jsdoc_is_caught(self):
        self.write("b.js", "/** Returns the parsed body. */\nfunction hide(x) { x.hidden = true; }\n")
        self.assertIn("comment states a return value", self.run_gate().stdout)

    def test_return_claim_on_a_jsdoc_continuation_line_is_caught(self):
        self.write("c.js", "/**\n * Does a thing.\n * Returns true when it worked.\n */\nfunction hide(x) { x.hidden = true; }\n")
        self.assertIn("comment states a return value", self.run_gate().stdout)

    def test_a_function_that_returns_is_left_alone(self):
        self.write("d.js", "/** Returns the sum. */\nfunction add(a, b) { return a + b; }\n")
        self.assertIn("OK:", self.run_gate().stdout)

    def test_a_lower_case_returns_describes_something_else(self):
        # "a destructive command returns a confirm card" is about the server, not
        # this function. Capitalisation is what separates the two.
        self.write("e.js", "// A destructive command returns a confirm card.\nfunction hide(x) { x.hidden = true; }\n")
        self.assertIn("OK:", self.run_gate().stdout)

    # ── correspondence: the fatal false positive ─────────────────────────────

    def test_destructured_params_are_not_reported_as_missing(self):
        self.write("f.js", "/**\n * Plan it.\n * @param url the url\n * @param retries how many\n */\nfunction plan({ url, retries }) { return url + retries; }\n")
        self.assertIn("OK:", self.run_gate().stdout)

    def test_a_genuinely_wrong_param_is_still_reported(self):
        # Ablates the fix above: the destructuring tolerance must not blind it.
        self.write("g.js", "/**\n * Plan it.\n * @param nosuch nope\n */\nfunction plan({ url }) { return url; }\n")
        self.assertIn("@param nosuch is not a parameter", self.run_gate().stdout)

    # ── fail-open ────────────────────────────────────────────────────────────

    def test_a_flag_with_no_value_exits_nonzero(self):
        # `--max` with nothing after it yielded NaN, and every comparison against
        # NaN is false, so the gate announced "over NaN lines" and exited 0.
        self.write("h.js", "// x\n" * 30 + "const a = 1;\n")
        result = self.run_gate("--quiet", "--max")
        self.assertEqual(result.returncode, 2)

    def test_malformed_config_exits_nonzero_with_a_readable_message(self):
        self.write("i.js", "const a = 1;\n")
        self.write(".comment-budget.json", "{ not json")
        result = self.run_gate("--quiet")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not valid JSON", result.stderr)

    def test_exempt_must_be_a_list(self):
        self.write("j.js", "const a = 1;\n")
        self.write(".comment-budget.json", json.dumps({"exempt": "src/x.ts"}))
        result = self.run_gate("--quiet")
        self.assertEqual(result.returncode, 2)

    # ── Python docstrings ────────────────────────────────────────────────────

    def assert_flagged(self, name: str) -> None:
        # Asserted on the exit code and the block marker, never on the phrase
        # "over 20 lines": the PASS line reads "no comment block over 20 lines",
        # so matching that substring passes on success and tests nothing.
        result = self.run_gate("--quiet")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("[BLOCK", result.stdout)
        self.assertIn(name, result.stdout)

    def test_a_module_docstring_counts_against_the_cap(self):
        self.write("m.py", '"""\n' + "narrative\n" * 25 + '"""\nx = 1\n')
        self.assert_flagged("m.py:1")

    def test_a_shebang_does_not_hide_the_module_docstring(self):
        # Counting the shebang as code put the docstring past its own position,
        # and a real 44-line one went unseen.
        self.write("n.py", '#!/usr/bin/env python3\n"""\n' + "narrative\n" * 25 + '"""\nx = 1\n')
        self.assert_flagged("n.py:2")

    def test_a_function_docstring_counts(self):
        self.write("o.py", 'def f():\n    """\n' + "    narrative\n" * 25 + '    """\n    return 1\n')
        self.assert_flagged("o.py:2")

    def test_triple_quoted_sql_is_code_not_documentation(self):
        self.write("p.py", 'cur.execute(\n    """\n' + "    SELECT 1,\n" * 25 + '    """,\n    (),\n)\n')
        self.assertIn("OK:", self.run_gate("--quiet").stdout)

    def test_a_closing_delimiter_does_not_open_a_new_region(self):
        # Lines are trimmed, so a lone closing `"""` looks exactly like an
        # opening one. Reading it as an opener made every later line comment.
        self.write("q.py", 'SQL = """\nSELECT 1\n"""\n' + "x = 1\n" * 40)
        self.assertIn("OK:", self.run_gate("--quiet", "--top", "1").stdout)

    def test_a_docstring_position_inside_a_data_string_is_still_data(self):
        # Only pairing settles this one. The `"""` on line 3 closes the template;
        # read independently it sits right after `def g():`, which is a docstring
        # position, so it would open a prose region and swallow the file.
        self.write("r.py", 'TEMPLATE = """\ndef g():\n    """\n' + "x = 1\n" * 40)
        self.assertIn("OK:", self.run_gate("--quiet", "--top", "1").stdout)

    # ── template literals ────────────────────────────────────────────────────

    def test_a_block_opener_inside_a_template_literal_is_data(self):
        # `/*` in a template literal opened a block that never closed, so every
        # line to the end of the file counted as one comment.
        self.write("t.js", "const t = `\n/* not a comment, just text\n`;\n" + "const x = 1;\n" * 40)
        self.assertIn("OK:", self.run_gate("--quiet", "--top", "1").stdout)

    def test_a_real_block_after_a_template_literal_is_still_caught(self):
        # Ablates the fix above: template tracking must not swallow real comments.
        self.write("u.js", "const t = `x`;\n" + "// narrative\n" * 25 + "const y = 1;\n")
        self.assertEqual(self.run_gate("--quiet").returncode, 1)

    # ── block length, the original rule ──────────────────────────────────────

    def test_a_block_over_the_cap_fails(self):
        self.write("k.js", "// prose\n" * 25 + "const a = 1;\n")
        result = self.run_gate("--quiet")
        self.assertEqual(result.returncode, 1)
        self.assertIn("over 20 lines", result.stdout)


if __name__ == "__main__":
    unittest.main()
