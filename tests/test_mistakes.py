# Your mistakes: FEN out of a game, the player's mistakes of an analyzed game as puzzles, and reading them back
import unittest
from datetime import datetime, timedelta, timezone

import support
import mistakes  # noqa: E402
from engine import GameState  # noqa: E402

FOOLS_MATE = "f2f3 e7e5 g2g4 d8h4"
# the analysis of FOOLS_MATE, as main.analyzeGame keeps it: the best move and the score (White's view) of each position
BEST = ['e2e4', 'e7e5', 'e2e4', 'd8h4', None]
EVALS = [0.3, -0.2, 0.1, -999.0, -999.0]


class FenTest(unittest.TestCase):
    def test_a_game_written_as_fen_reads_back_the_same(self):
        lines = ["", "e2e4", "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1", "e2e4 d7d5 e4e5 f7f5",
                 "a2a4 h7h5 a1a3 h8h6 a3h3 h6a6", "e2e4 f7f5 e4f5 g7g5"]
        for line in lines:
            with self.subTest(moves=line):
                gs = support.play(GameState(), line)
                again = GameState.fromFen(gs.toFen())
                self.assertEqual(again.getPositionKey(), gs.getPositionKey())
                self.assertEqual(again.startFen, gs.toFen())
                self.assertEqual(len(again.getValidMoves()), len(gs.getValidMoves()))
        self.assertEqual(GameState().toFen(), "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        self.assertIsNone(GameState().startFen, "the usual start")
        self.assertEqual(support.play(GameState(), "e2e4 d7d5 e4e5 f7f5").toFen().split()[2:4], ['KQkq', 'f6'])
        rights = support.play(GameState(), "a2a4 h7h5 a1a3 h8h6 e2e3 e7e6 e1e2").toFen().split()[2]
        self.assertEqual(rights, 'q', "the king and the rooks that moved lose theirs")


class MistakesTest(unittest.TestCase):
    def game(self):
        return support.play(GameState(), FOOLS_MATE).moveLog

    def marks(self):
        return {2: ("??", 10.1)}

    def test_the_players_mistakes_become_puzzles(self):
        found = mistakes.fromGame(self.game(), BEST, EVALS, self.marks(), 'w', "Computer (Hard)")
        self.assertEqual(len(found), 1)
        mistake = found[0]
        self.assertEqual(mistake.fen, support.play(GameState(), "f2f3").toFen(), "before the opponent's move")
        self.assertEqual(mistake.moves, ['e7e5', 'e2e4'], "the opponent's move, then the best answer")
        self.assertEqual((mistake.played, mistake.score, mistake.loss, mistake.ply, mistake.opponent),
                         ('g2g4', 0.1, 10.1, 2, "Computer (Hard)"))
        self.assertEqual(mistake.color, 'w')
        gs, first = mistake.start()
        self.assertEqual(first.getCode(), 'e7e5')
        self.assertEqual(gs.getPositionKey(), support.play(GameState(), "f2f3 e7e5").getPositionKey(),
                         "the position the mistake was made in")
        self.assertEqual(mistake.payload(), {'fen': mistake.fen, 'moves': 'e7e5 e2e4', 'played': 'g2g4', 'score': 0.1,
                                             'loss': 10.1, 'opponent': "Computer (Hard)", 'ply': 2})
        self.assertEqual(mistake.key, (mistake.fen, 'e7e5 e2e4', 'g2g4'))

    def test_which_marks_and_moves_count(self):
        log = self.game()
        self.assertEqual(mistakes.fromGame(log, BEST, EVALS, self.marks(), 'b'), [], "only the player's own moves")
        self.assertEqual(mistakes.fromGame(log, BEST, EVALS, {2: ("?!", 1.0)}, 'wb'), [], "not inaccuracies")
        self.assertEqual(len(mistakes.fromGame(log, BEST, EVALS, {2: ("?", 1.6)}, 'wb')), 1)
        self.assertEqual(mistakes.fromGame(log, BEST, EVALS, {0: ("??", 3.5)}, 'wb'), [],
                         "the first move has no move of the opponent before it")
        self.assertEqual(mistakes.fromGame(log, BEST[:2], EVALS[:2], self.marks(), 'wb'), [], "an analysis cut short")
        black = mistakes.fromGame(log, ['e2e4', 'e7e5', 'e2e4', 'b8c6', None], [0.3, -0.2, 0.1, 0.4, 0.4],
                                  {3: ("?", 2.0)}, 'wb')
        self.assertEqual((black[0].color, black[0].score), ('b', -0.4), "Black's score is the other way round")
        self.assertEqual(black[0].moves, ['g2g4', 'b8c6'])
        capped = mistakes.fromGame(log, BEST, [0.3, -0.2, 999.0, -999.0, -999.0], self.marks(), 'w')
        self.assertEqual(capped[0].score, mistakes.SCORE_CAP, "a mate is kept as a won position")

    def test_rows_from_the_account(self):
        mistake = mistakes.fromGame(self.game(), BEST, EVALS, self.marks(), 'w')[0]
        row = dict(mistake.payload(), id=12, solved=1)
        again = mistakes.fromRow(row)
        self.assertEqual((again.key, again.id, again.score, again.ply), (mistake.key, 12, 0.1, 2))
        for changes in ({'moves': 'e7e5'}, {'moves': 'e7e5 e2e4 d7d5'}, {'moves': 'e7e5 e1e8'},
                        {'played': 'a1a8'}, {'fen': 'nonsense'}, {'score': 'high'}, {'fen': None}):
            with self.subTest(changes=changes):
                self.assertIsNone(mistakes.fromRow(dict(row, **changes)))
        self.assertIsNone(mistakes.fromRow({'id': 3}))

    def test_seconds_until_a_time_from_the_account(self):
        now = datetime(2026, 11, 6, 9, tzinfo=timezone.utc)
        self.assertEqual(mistakes.secondsUntil('2026-11-06T10:00:00+00:00', now), 3600)
        self.assertEqual(mistakes.secondsUntil('2026-11-06T10:00:00.5Z', now), 3600.5)
        self.assertEqual(mistakes.secondsUntil('2026-11-06T09:00:00', now), 0, "no zone: UTC")
        self.assertLess(mistakes.secondsUntil((now - timedelta(days=1)).isoformat(), now), 0)
        for value in (None, '', 'tomorrow'):
            self.assertIsNone(mistakes.secondsUntil(value, now))


if __name__ == '__main__':
    unittest.main()
