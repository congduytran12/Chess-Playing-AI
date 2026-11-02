# The game's Stockfish bridge against a real Stockfish, when there is one (STOCKFISH_PATH, PATH, or engines/): what the
# bridge counts on, which a new Stockfish version could change: the UCI options the levels use, the move and score
# lines. Skipped without an engine; the other tests use a stand-in (test_stockfish.py).
import asyncio
import re
import subprocess
import unittest

import support
import chessAi
import stockfish
from engine import GameState

EXECUTABLE = stockfish.findExecutable()
FOOLS_MATE = ['f2f3', 'e7e5', 'g2g4']  # Black mates with d8h4


def legalCodes(moves):
    gs = GameState()
    for code in moves:
        gs.makeMove(gs.findMoveByCode(code, gs.getValidMoves()))
    return {move.getCode()[:4] for move in gs.getValidMoves()}


@unittest.skipIf(EXECUTABLE is None, "no Stockfish found (STOCKFISH_PATH, PATH, or the engines/ folder)")
class RealStockfishTest(unittest.TestCase):
    def setUp(self):
        self.saved = stockfish.ENABLED, stockfish.engine
        stockfish.ENABLED = True
        stockfish.engine = stockfish.Engine()
        self.levels = list(chessAi.LEVELS)

    def tearDown(self):
        stockfish.engine.close()
        stockfish.ENABLED, stockfish.engine = self.saved
        chessAi.LEVELS[:] = self.levels

    def test_the_strength_range_covers_the_levels(self):
        out = subprocess.run([EXECUTABLE], input="uci\nquit\n", capture_output=True, text=True, timeout=30).stdout
        self.assertRegex(out, r"id name Stockfish")
        elo = re.search(r"option name UCI_Elo type spin default \d+ min (\d+) max (\d+)", out)
        self.assertIsNotNone(elo, "UCI_Elo is how the levels are set")
        low, high = int(elo.group(1)), int(elo.group(2))
        limits = [e for e in stockfish.LEVEL_ELO if e is not None]
        self.assertLessEqual(low, min(limits), "the weakest level would be stronger than it says")
        self.assertGreaterEqual(high, max(limits))
        for name in ("UCI_LimitStrength", "Threads", "Hash"):
            self.assertIn("option name " + name + " ", out)

    def test_moves_scores_and_mates(self):
        async def run():
            self.assertTrue(await stockfish.engine.ready(30))
            self.assertTrue(stockfish.engine.name.startswith("Stockfish"), stockfish.engine.name)
            start = await stockfish.engine.go([], 0.3)
            mate = await stockfish.engine.go(FOOLS_MATE, 0.3)
            return start, mate
        start, mate = asyncio.run(run())
        self.assertIn(start[0], legalCodes([]))
        self.assertIsInstance(start[1], float)
        self.assertLess(abs(start[1]), 1.5, "the start position is level")
        self.assertEqual(mate[0], 'd8h4')
        self.assertGreater(mate[1], chessAi.MATE_THRESHOLD, "a forced mate in one, in the game's scale")

    def test_every_level_plays_a_legal_move(self):
        for index, level in enumerate(chessAi.LEVELS):
            chessAi.LEVELS[index] = (level[0], 0.1) + tuple(level[2:])  # a tenth of a second each

        async def run():
            self.assertTrue(await stockfish.engine.ready(30))
            gs = GameState()
            found = []
            for index in range(len(chessAi.LEVELS)):
                move = await stockfish.findBestMove(gs, gs.getValidMoves(), level=index)
                found.append(move.getCode()[:4])
            return found
        for code in asyncio.run(run()):
            self.assertIn(code, legalCodes([]))
        self.assertEqual(stockfish.engine.state, 'ready', "Stockfish answered (chessAi's search is the fallback)")


if __name__ == '__main__':
    unittest.main()
