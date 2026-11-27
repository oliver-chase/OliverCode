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


if __name__ == "__main__":
    unittest.main()
