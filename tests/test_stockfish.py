# game/stockfish.py against a stand-in UCI engine (a small Python script), so no real Stockfish is needed
import os
import sys
import asyncio
import tempfile
import textwrap
import unittest

import support  # noqa: F401  (puts game/ on the path, turns the real Stockfish off)
import chessAi
import stockfish
from engine import GameState

# answers like Stockfish: e2e4 from the start, e7e5 after it, a mate score after 1. f3 e5 2. g4, and a long
# search until 'stop' for 'go movetime 9999'; every command it gets goes to the log file
FAKE_ENGINE = textwrap.dedent('''
    import sys
    log = open(sys.argv[1], 'a')
    moves = []
    def say(line):
        sys.stdout.write(line + '\\n')
        sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        log.write(line + '\\n')
        log.flush()
        if line == 'uci':
            say('id name FakeFish 1')
            say('uciok')
        elif line == 'isready':
            say('readyok')
        elif line.startswith('position startpos'):
            moves = line.split()[3:]
        elif line == 'go movetime 9999':
            pass  # answers on stop
        elif line == 'stop':
            say('bestmove a2a3')
        elif line.startswith('go'):
            if moves == ['f2f3', 'e7e5', 'g2g4']:
                say('info depth 3 score mate 1 pv d8h4')
                say('bestmove d8h4')
            else:
                say('info depth 5 score cp 10 upperbound pv a2a3')
                say('info depth 6 score cp 42 pv e2e4')
                say('bestmove ' + ('e2e4' if not moves else 'e7e5'))
        elif line == 'quit':
            break
''')


class StockfishTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        script = os.path.join(self.folder.name, 'fakefish.py')
        with open(script, 'w') as f:
            f.write(FAKE_ENGINE)
        self.log = os.path.join(self.folder.name, 'commands.txt')
        self.saved = stockfish.ENABLED, stockfish.engine
        stockfish.ENABLED = True
        stockfish.engine = stockfish.Engine([sys.executable, script, self.log])

    def tearDown(self):
        stockfish.engine.close()
        stockfish.ENABLED, stockfish.engine = self.saved
        self.folder.cleanup()

    def commands(self):
        with open(self.log) as f:
            return f.read().split('\n')

    def test_scores(self):
        self.assertEqual(stockfish.parseScore('info depth 6 score cp 42 pv e2e4'), ('cp', 42))
        self.assertEqual(stockfish.parseScore('info depth 9 score mate -3 pv h7h6'), ('mate', -3))
        self.assertIsNone(stockfish.parseScore('info depth 6 score cp 42 lowerbound pv e2e4'), "a bound")
        self.assertIsNone(stockfish.parseScore('info depth 6 multipv 2 score cp 42 pv e2e4'), "not the best line")
        self.assertIsNone(stockfish.parseScore('info string NNUE enabled'))
        self.assertEqual(stockfish.scoreInPawns(('cp', -150)), -1.5)
        self.assertEqual(stockfish.scoreInPawns(('mate', 2)), chessAi.CHECKMATE - 2)
        self.assertEqual(stockfish.scoreInPawns(('mate', -1)), -(chessAi.CHECKMATE - 1))
        self.assertGreater(stockfish.scoreInPawns(('mate', 30)), chessAi.MATE_THRESHOLD, "a mate counts as one")

    def test_moves_hints_and_levels(self):
        async def run():
            gs = GameState()
            self.assertTrue(await stockfish.engine.ready(10))
            self.assertEqual(stockfish.engine.name, 'FakeFish 1')
            move = await stockfish.findBestMove(gs, gs.getValidMoves(), level=0)
            self.assertEqual(move.getCode(), 'e2e4')
            gs.makeMove(move)
            score, reply, _ = await stockfish.searchPosition(gs, gs.getValidMoves(), 0.05)
            self.assertEqual((reply.getCode(), score), ('e7e5', 0.42), "the last full score, not the bound")
            mate = GameState()
            for code in ('f2f3', 'e7e5', 'g2g4'):
                mate.makeMove(mate.findMoveByCode(code, mate.getValidMoves()))
            score, best, _ = await stockfish.searchPosition(mate, mate.getValidMoves(), 0.05)
            self.assertEqual((best.getCode(), score), ('d8h4', chessAi.CHECKMATE - 1))
            await stockfish.findBestMove(GameState(), GameState().getValidMoves(), level=4)
        asyncio.run(run())
        sent = self.commands()
        self.assertIn('position startpos moves e2e4', sent, "the game's moves from the start")
        self.assertIn('position startpos moves f2f3 e7e5 g2g4', sent)
        self.assertIn('setoption name UCI_Elo value %d' % stockfish.LEVEL_ELO[0], sent, "Easy plays weaker")
        self.assertIn('setoption name UCI_LimitStrength value false', sent, "hints and Impossible at full strength")
        self.assertIn('go movetime %d' % round(chessAi.LEVELS[0][1] * 1000), sent, "the level's time")

    def test_a_cancelled_search_doesnt_answer_the_next(self):
        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            task = asyncio.ensure_future(stockfish.engine.go([], 9999 / 1000))
            await asyncio.sleep(0.3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return await stockfish.engine.go(['e2e4'], 0.05)
        self.assertEqual(asyncio.run(run()), ('e7e5', 0.42), "not the stopped search's a2a3")

    def test_without_an_engine_the_games_own_ai_plays(self):
        stockfish.engine = stockfish.Engine([sys.executable, '-c', 'pass'])  # exits at once

        async def run():
            gs = GameState()
            moves = gs.getValidMoves()
            move = await stockfish.findBestMove(gs, moves, level=0)
            score, hint, _ = await stockfish.searchPosition(gs, moves, 0.05)
            return move, hint, await stockfish.evaluate(gs, 0.05)
        move, hint, evaluation = asyncio.run(run())
        self.assertEqual(stockfish.engine.state, 'failed')
        self.assertIn(move, GameState().getValidMoves())
        self.assertIn(hint, GameState().getValidMoves())
        self.assertIsNone(evaluation, "the draw decision counts material instead")

    def test_turned_off(self):
        stockfish.ENABLED = False
        self.assertFalse(asyncio.run(stockfish.engine.ready(1)))
        self.assertEqual(stockfish.engine.state, 'off', "never started")

    def test_finding_the_executable(self):
        saved = os.environ.get('STOCKFISH_PATH')
        try:
            os.environ['STOCKFISH_PATH'] = os.path.join(self.folder.name, 'missing.exe')
            self.assertIsNone(stockfish.findExecutable(), "a wrong STOCKFISH_PATH finds nothing")
            os.environ['STOCKFISH_PATH'] = self.log
            open(self.log, 'a').close()
            self.assertEqual(stockfish.findExecutable(), self.log)
        finally:
            if saved is None:
                os.environ.pop('STOCKFISH_PATH', None)
            else:
                os.environ['STOCKFISH_PATH'] = saved


if __name__ == '__main__':
    unittest.main()
