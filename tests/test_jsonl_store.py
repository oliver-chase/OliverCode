"""The shared JSONL store (#1207) that candidates.py and story_outbox.py both read, save and lock through."""

import sys
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import jsonl_store  # noqa: E402


class TestJsonlStore(unittest.TestCase):
    def path(self):
        return temp_dir(self) / "list.jsonl"

    def test_read_of_a_missing_file_is_empty(self):
        self.assertEqual([], jsonl_store.read(self.path()))

    def test_save_then_read_round_trips_and_a_bad_line_is_skipped(self):
        p = self.path()
        jsonl_store.save(p, [{"repo": "o/r", "title": "One"}, {"repo": "o/r", "title": "Two"}])
        p.write_text(p.read_text() + "not json\n" + '{"repo": "o/r"}\n')
        self.assertEqual(["One", "Two"], [i["title"] for i in jsonl_store.read(p)])

    def test_saving_an_empty_list_removes_the_file(self):
        p = self.path()
        jsonl_store.save(p, [{"repo": "o/r", "title": "One"}])
        jsonl_store.save(p, [])
        self.assertFalse(p.exists())

    def test_the_lock_file_sits_beside_the_store_with_the_same_stem(self):
        p = self.path()
        with jsonl_store.locked(p):
            self.assertTrue(p.with_suffix(".lock").is_file())

    def test_two_adds_of_the_same_title_under_the_lock_hold_it_once(self):
        p = self.path()

        def add(title):
            with jsonl_store.locked(p):
                rows = jsonl_store.read(p)
                if any(r["title"] == title for r in rows):
                    return
                jsonl_store.save(p, rows + [{"repo": "o/r", "title": title}])

        add("Dup")
        add("Dup")
        self.assertEqual(["Dup"], [r["title"] for r in jsonl_store.read(p)])


if __name__ == "__main__":
    unittest.main()
