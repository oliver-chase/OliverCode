"""Run the backlog skill's own offline tests as part of the repo's smoke tests."""
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "backlog" / "scripts"


def load_tests(loader, tests, pattern):
    import sys
    sys.path.insert(0, str(SCRIPTS))
    suite = unittest.TestSuite()
    suite.addTests(loader.discover(str(SCRIPTS), pattern="test_*.py", top_level_dir=str(SCRIPTS)))
    return suite


if __name__ == "__main__":
    unittest.main()
