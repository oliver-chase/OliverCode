import unittest

import load_guard


class LoadGuardTest(unittest.TestCase):
    def test_an_idle_machine_gets_every_reader_and_mutations(self):
        self.assertEqual(load_guard.advice(2, 8), (12, True))

    def test_a_busy_machine_gets_fewer_readers_and_no_mutations(self):
        self.assertEqual(load_guard.advice(10, 8), (6, False))

    def test_an_overloaded_machine_waits(self):
        self.assertEqual(load_guard.advice(350, 8), (0, False))


if __name__ == "__main__":
    unittest.main()
