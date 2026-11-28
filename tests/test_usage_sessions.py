import json
import sys
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import usage_sessions  # noqa: E402


class TestTranscript(unittest.TestCase):
    def test_finds_the_session_file_under_any_project_and_none_when_absent(self):
        projects = temp_dir(self)
        (projects / "p").mkdir()
        (projects / "p" / "abc.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertEqual(projects / "p" / "abc.jsonl", usage_sessions.transcript("abc", projects))
        self.assertIsNone(usage_sessions.transcript("zzz", projects))


def _msg(at, mid, tokens, model="m", kind="assistant"):
    usage = {"input_tokens": tokens, "output_tokens": 1, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3}
    return json.dumps({"type": kind, "timestamp": f"2026-01-01T00:00:{at:02d}Z", "message": {"id": mid, "model": model, "usage": usage}})


class TestUsageBetween(unittest.TestCase):
    def test_sums_the_window_once_per_message_id(self):
        path = temp_dir(self) / "t.jsonl"
        path.write_text("\n".join([_msg(5, "a", 100), _msg(20, "b", 10, "x"), _msg(20, "b", 10, "x"), _msg(21, "c", 1, kind="user"), "junk", _msg(50, "d", 1000)]), encoding="utf-8")
        start = 1767225600  # 2026-01-01T00:00:00Z
        got = usage_sessions.usage_between(path, start + 10, start + 30)
        self.assertEqual({"input": 10, "output": 1, "cache_read": 2, "cache_write": 3, "model": "x"}, got)
        self.assertEqual("", usage_sessions.usage_between(path, start + 60, start + 70)["model"])
        self.assertEqual(0, usage_sessions.usage_between(path / "none", 0, 1e12)["input"])

    def test_a_row_with_no_runner_reads_as_drain(self):
        self.assertEqual("drain", usage_sessions.runner({"story": "story-1"}))
        self.assertEqual("thread", usage_sessions.runner({"runner": "thread"}))


if __name__ == "__main__":
    unittest.main()
