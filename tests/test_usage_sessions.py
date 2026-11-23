import json
import sys
import time
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import usage_sessions  # noqa: E402

NOW = 1_800_000_000.0


class TestPeriodUsage(unittest.TestCase):
    def test_a_message_logged_twice_keeps_the_largest_of_each_count_not_the_largest_row(self):
        path, day = temp_dir(self) / "t.jsonl", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW))
        rows = [{"input_tokens": 9, "output_tokens": 1}, {"input_tokens": 2, "output_tokens": 50}]
        path.write_text("".join(json.dumps({"timestamp": day, "message": {"id": "m", "usage": u}}) + "\n" for u in rows), encoding="utf-8")
        self.assertEqual((9, 50, 0), usage_sessions.period_usage(path, NOW - 60))


if __name__ == "__main__":
    unittest.main()
