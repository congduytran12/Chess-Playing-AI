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

    def test_hint_avoids_immediate_third_repetition(self):
        gs = GameState()
        valid = gs.getValidMoves()
        move = valid[0]
        gs.makeMove(move)
        repeated = gs.getPositionKey()
        gs.undoMove()
        candidates = stockfish.hintMoves(gs, valid, [repeated, repeated])
        self.assertNotIn(move, candidates)
        self.assertEqual(stockfish.nonRepetitionMoves(gs, valid, [repeated, repeated]), candidates)

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
        self.assertTrue(any(command.startswith('go movetime %d ' % round(chessAi.LEVELS[0][1] * 1000))
                            for command in sent), "the level's time")

    def test_the_analysis_uses_the_hint_engine(self):
        script = os.path.join(self.folder.name, 'fakefish.py')
        hintLog = os.path.join(self.folder.name, 'hint-commands.txt')
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.Engine([sys.executable, script, hintLog], channel='hint')
        try:
            gs = GameState()
            gs.makeMove(gs.findMoveByCode('e2e4', gs.getValidMoves()))
            score, best, _ = asyncio.run(stockfish.analyzePosition(gs, gs.getValidMoves(), 0.05))
        finally:
            stockfish.hintEngine.close()
            stockfish.hintEngine = saved
        self.assertEqual((best.getCode(), score), ('e7e5', 0.42))
        with open(hintLog) as f:
            self.assertIn('position startpos moves e2e4', f.read().split('\n'))
        self.assertFalse(os.path.exists(self.log), "the gameplay engine wasn't asked")

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

    def test_search_moves_restriction(self):
        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            return await stockfish.engine.go([], 0.05, search_moves=['e2e4'])
        self.assertEqual(asyncio.run(run()), ('e2e4', 0.42))
        self.assertIn('go movetime 50 searchmoves e2e4', self.commands(), "searchmoves last: it takes every word after it")

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

    def test_the_browser_engine_is_the_one_the_build_downloads(self):
        import json
        import re
        with open(os.path.join(support.ROOT, 'package.json'), encoding='utf-8') as f:
            build = json.load(f)['scripts']['build']
        name = os.path.basename(stockfish.WORKER_URL)  # stockfish-19-lite-single.js
        self.assertTrue(name.endswith('-lite-single.js'), "the single-threaded build runs without special headers")
        wasm = name[:-len('.js')] + '.wasm'
        for file in (name, wasm):
            self.assertIn('game/build/web/stockfish/%s https://unpkg.com/stockfish@' % file, build)
            self.assertIn('/bin/%s' % file, build)
        hint_name = os.path.basename(stockfish.HINT_WORKER_URL)  # stockfish-dev-20261028-single.js
        self.assertTrue(hint_name.endswith('-single.js'))
        release = 'https://github.com/congduytran12/Chess-Playing-AI/releases/download/stockfish-dev-20261028-wasm/'
        self.assertIn('game/build/web/stockfish/%s %s%s' % (hint_name, release, hint_name), build)
        parts = hint_name[:-len('.js')] + '-part-$i.wasm'  # the loader fetches <name>-part-0.wasm and on
        self.assertIn('for i in %s; do' % ' '.join(str(i) for i in range(stockfish.HINT_WORKER_PARTS)), build)
        self.assertIn('game/build/web/stockfish/%s %s%s' % (parts, release, parts), build)
        self.assertIn('game/build/web/stockfish/Copying.txt', build, "the GPL license goes with the engine")
        self.assertEqual(re.search(r'stockfish@(\d+)\.', build).group(1), re.search(r'stockfish-(\d+)-', name).group(1),
                         "the version in the file name is the package's")

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
