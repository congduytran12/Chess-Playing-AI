# tools/hint_match.py: the statistics behind its verdicts, and how a match picks its games
import os
import sys
import unittest

import support  # noqa: F401  (puts game/ on the path)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import hint_match  # noqa: E402


class HintMatchStatsTest(unittest.TestCase):
    def test_wilson_interval(self):
        low, high = hint_match.wilson(1, 10)
        self.assertAlmostEqual(low, 0.0179, places=3)
        self.assertAlmostEqual(high, 0.4042, places=3)
        low, high = hint_match.wilson(0, 0)
        self.assertEqual((low, high), (0.0, 1.0), "no games: anything is possible")
        low, high = hint_match.wilson(40, 64)
        self.assertGreater(low, 0.5, "40 wins of 64 is more than half with 95% confidence")

    def test_sequential_test_on_wins(self):
        self.assertEqual(hint_match.sprt(0, 0)[1], None)
        self.assertEqual(hint_match.sprt(1, 10)[1], 'H0', "the old hint (about one win in ten) is rejected quickly")
        self.assertEqual(hint_match.sprt(12, 12)[1], 'H1', "twelve wins in a row is enough")
        llr, verdict = hint_match.sprt(30, 50)
        self.assertIsNone(verdict, "60% of 50 games doesn't decide between 50% and 65% yet")
        self.assertAlmostEqual(llr, 30 * 0.26236 + 20 * -0.35667, places=3)

    def test_mcnemar_on_paired_games(self):
        self.assertEqual(hint_match.mcnemar(0, 0), 1.0)
        self.assertAlmostEqual(hint_match.mcnemar(10, 0), 2 / 1024, places=6)
        self.assertAlmostEqual(hint_match.mcnemar(5, 5), 1.0)
        self.assertLess(hint_match.mcnemar(12, 2), 0.05)

    def test_tally(self):
        games = [{'hintScore': 1.0}, {'hintScore': 0.5}, {'hintScore': 0.5}, {'hintScore': 0.0}]
        self.assertEqual(hint_match.tally(games), (1, 2, 1))


class HintMatchJobsTest(unittest.TestCase):
    def test_each_opening_is_played_with_both_colours(self):
        suite = hint_match.openingSuite('book6')
        self.assertGreaterEqual(len(suite), 30)
        self.assertTrue(all(len(line) == hint_match.OPENING_PLIES for _, line in suite))
        jobs = hint_match.jobsFor(suite, 64)
        self.assertEqual(len(jobs), 64)
        keys = {hint_match.jobKey(oid, color, rep) for oid, _, color, rep in jobs}
        self.assertEqual(len(keys), 64, "every game is a different job (so --resume can tell them apart)")
        self.assertEqual([color for _, _, color, _ in jobs[:2]], ['w', 'b'])

    def test_a_small_suite_is_played_again(self):
        jobs = hint_match.jobsFor(hint_match.openingSuite('startpos'), 6)
        self.assertEqual(len(jobs), 6)
        self.assertEqual(len({hint_match.jobKey(oid, color, rep) for oid, _, color, rep in jobs}), 6)
        self.assertTrue(all(line == [] for _, line, _, _ in jobs))

    def test_a_short_match_spreads_over_the_book(self):
        jobs = hint_match.jobsFor(hint_match.openingSuite('book6'), 4)
        self.assertEqual(len(jobs), 4)
        self.assertNotEqual(jobs[0][0], jobs[2][0], "two different openings")


if __name__ == '__main__':
    unittest.main()
