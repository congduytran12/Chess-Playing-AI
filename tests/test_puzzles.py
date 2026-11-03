# The puzzles: the FEN loader, the puzzle data, picking and rating
import os
import json
import random
import tempfile
import unittest

import support  # noqa: F401  (puts game/ on the path)
import puzzles  # noqa: E402
from engine import GameState, Move

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class PuzzlesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = puzzles.STORAGE_FILE, puzzles._saved
        puzzles.STORAGE_FILE = os.path.join(self.folder.name, 'puzzles.json')
        puzzles._saved = None

    def tearDown(self):
        puzzles.STORAGE_FILE, puzzles._saved = self.saved
        self.folder.cleanup()

    def test_a_fen_gives_the_game(self):
        gs, start = GameState.fromFen(START), GameState()
        self.assertEqual(gs.board, start.board)
        self.assertEqual(gs.getPositionKey(), start.getPositionKey())
        self.assertEqual(len(gs.getValidMoves()), 20)
        gs = GameState.fromFen("r3k2r/8/8/3pP3/8/8/8/R3K2R w Kq d6 0 12")
        self.assertEqual((gs.whiteCastleKingside, gs.whiteCastleQueenside, gs.blackCastleKingside,
                          gs.blackCastleQueenside), (True, False, False, True))
        self.assertEqual(gs.enpasantPossible, (Move.ranksToRows['6'], Move.filesToCols['d']))
        codes = {move.getCode() for move in gs.getValidMoves()}
        self.assertIn('e5d6', codes, "en passant")
        self.assertIn('e1g1', codes, "castling")
        self.assertNotIn('e1c1', codes, "no queenside right")
        self.assertEqual((gs.whiteKinglocation, gs.blackKinglocation), ((7, 4), (0, 4)))
        black = GameState.fromFen("4k3/8/8/8/8/8/4p3/4K3 b - - 0 1")
        self.assertFalse(black.whiteToMove)
        promotions = {move.getCode() for move in black.getValidMoves() if move.isPawnPromotion}
        self.assertEqual(promotions, set(), "the pawn is blocked by the king's square")

    def test_every_puzzle_can_be_played(self):
        everything = puzzles.load()
        self.assertGreaterEqual(len(everything), 500)
        ratings = [puzzle.rating for puzzle in everything]
        self.assertEqual(ratings, sorted(ratings), "easiest first")
        self.assertLess(ratings[0], 700)
        self.assertGreater(ratings[-1], 2300)
        self.assertEqual(len({puzzle.id for puzzle in everything}), len(everything), "no puzzle twice")
        for puzzle in everything:
            with self.subTest(puzzle=puzzle.id):
                gs, first = puzzle.start()
                self.assertEqual(first.getCode()[:4], puzzle.moves[0][:4])
                self.assertEqual('w' if gs.whiteToMove else 'b', puzzle.color)
                self.assertEqual(len(puzzle.moves) % 2, 0, "ends with the player's move")
                for code in puzzle.moves[1:]:
                    move = gs.findMoveByCode(code, gs.getValidMoves())
                    self.assertIsNotNone(move, "%s is not legal" % code)
                    gs.makeMove(move)

    def test_picking_the_next_puzzle(self):
        rng = random.Random(1)
        puzzle = puzzles.pick(1000, rng)
        self.assertLessEqual(abs(puzzle.rating - 1000), puzzles.RATING_RANGE)
        self.assertEqual(puzzles.pick(100000, rng).rating, puzzles.load()[-1].rating, "none that high: the hardest")
        self.assertEqual(puzzles.pick(-5000, rng).rating, puzzles.load()[0].rating)
        progress = puzzles.current()
        progress['solved'] = [p.id for p in puzzles.load() if abs(p.rating - 1000) <= puzzles.RATING_RANGE]
        puzzle = puzzles.pick(1000, rng)
        self.assertNotIn(puzzle.id, progress['solved'], "a puzzle already solved isn't shown again")
        self.assertGreater(abs(puzzle.rating - 1000), puzzles.RATING_RANGE - 1, "the nearest ones left")
        progress['solved'] = [p.id for p in puzzles.load()]
        puzzles.pick(1000, rng)
        self.assertEqual(progress['solved'], [], "everything solved: it starts over")

    def test_rating(self):
        self.assertEqual(puzzles.newRating(1000, 1000, True), 1012)
        self.assertEqual(puzzles.newRating(1000, 1000, False), 988)
        self.assertGreater(puzzles.newRating(1000, 1600, True), puzzles.newRating(1000, 1000, True), "harder: more")
        self.assertLess(puzzles.newRating(1000, 1600, False), 1000)
        self.assertLess(puzzles.newRating(1000, 600, False), puzzles.newRating(1000, 1400, False),
                        "failing an easy one costs more")
        self.assertEqual(puzzles.newRating(100, 100, False), 100, "never below 100")

    def test_progress_is_kept(self):
        puzzle = puzzles.load()[0]
        self.assertEqual(puzzles.current()['rating'], puzzles.START_RATING)
        change = puzzles.finish(puzzle, True)
        self.assertGreater(change, 0)
        self.assertEqual(puzzles.current()['streak'], 1)
        puzzles.finish(puzzles.load()[1], True, hinted=True)
        self.assertEqual(puzzles.current()['rating'], puzzles.START_RATING + change, "a hint: no change")
        self.assertEqual(puzzles.current()['streak'], 2)
        puzzles.finish(puzzles.load()[2], False)
        self.assertEqual((puzzles.current()['streak'], puzzles.current()['best']), (0, 2))
        self.assertLess(puzzles.current()['rating'], puzzles.START_RATING + change)
        self.assertEqual(puzzles.current()['solved'], [puzzles.load()[0].id, puzzles.load()[1].id])
        puzzles._saved = None  # read again from the file
        again = puzzles.current()
        self.assertEqual((again['best'], again['attempts'], len(again['solved'])), (2, 3, 2))
        with open(puzzles.STORAGE_FILE, 'w') as f:
            json.dump({'rating': 'high', 'solved': 5, 'streak': -3, 'best': True}, f)
        puzzles._saved = None
        self.assertEqual(puzzles.current(), {'rating': 1000, 'streak': 0, 'best': 0, 'attempts': 0, 'solved': []},
                         "nonsense in the file is left out")

    def test_the_themes_read_well(self):
        puzzle = puzzles.Puzzle('x', START, ['e2e4'], 1000, ['mateIn2', 'backRankMate'])
        self.assertEqual(puzzle.themeText, "Mate in 2 · Back rank mate")
        self.assertEqual(puzzle.themeLabels, ["Mate in 2", "Back rank mate"])
        for theme, label in (('discoveredAttack', "Discovered attack"), ('fork', "Fork"), ('xRayAttack', "X ray attack"),
                             ('attackingF2F7', "Attacking f2f7"), ('queenRookEndgame', "Queen rook endgame")):
            self.assertEqual(puzzles.themeLabel(theme), label)


if __name__ == '__main__':
    unittest.main()
