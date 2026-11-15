import unittest

import load_guard


class LoadGuardTest(unittest.TestCase):
    def test_readers_and_mutations_step_down_as_load_passes_the_core_count_and_twice_it(self):
        for load, expected in ((2, (12, True)), (8, (12, True)), (10, (6, False)), (16, (6, False)), (17, (0, False)), (350, (0, False))):
            self.assertEqual(expected, load_guard.advice(load, 8), load)


if __name__ == "__main__":
    unittest.main()
