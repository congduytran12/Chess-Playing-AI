# game/stockfish.py against a stand-in UCI engine (a small Python script), so no real Stockfish is needed
import os
import sys
import time
import asyncio
import tempfile
import textwrap
import unittest

import support  # noqa: F401  (puts game/ on the path, turns the real Stockfish off)
import chessAi
import stockfish
from engine import GameState

# Black to move after these, and f6g8 / c6b8 would be the start position's third time: playing on instead scores
# -9 pawns after the first, -0.1 after the second
LOSING_ON = ['g1f3', 'g8f6', 'f3g1', 'f6g8', 'g1f3', 'g8f6', 'f3g1']
HOLDING_ON = ['b1c3', 'b8c6', 'c3b1', 'c6b8', 'b1c3', 'b8c6', 'c3b1']

# answers like Stockfish: e2e4 from the start, e7e5 after it, a mate score after 1. f3 e5 2. g4, the scores above
# after LOSING_ON and HOLDING_ON, and a long search until 'stop' for 'go movetime 9999'; every command it gets goes
# to the log file
FAKE_ENGINE = textwrap.dedent('''
    import sys
    LOSING_ON = LOSING_ON_MOVES
    HOLDING_ON = HOLDING_ON_MOVES
    log = open(sys.argv[1], 'a')
    moves = []
    multipv = 1
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
        elif line.startswith('setoption name MultiPV value'):
            multipv = int(line.split()[-1])
        elif line.startswith('position startpos'):
            moves = line.split()[3:]
        elif line == 'go movetime 9999':
            pass  # answers on stop
        elif line == 'stop':
            say('bestmove a2a3')
        elif line.startswith('go'):
            if moves == LOSING_ON or moves == HOLDING_ON:  # Black can repeat; the best other move scores:
                say('info depth 6 score cp %d pv h7h6' % (-900 if moves == LOSING_ON else -10))
                say('bestmove h7h6')
            elif moves == ['f2f3', 'e7e5', 'g2g4']:
                say('info depth 3 score mate 1 pv d8h4')
                say('bestmove d8h4')
            elif multipv > 1:  # the best line and three more, the last one clearly worse; d4 wins more often than e4
                say('info depth 5 multipv 1 score cp 10 upperbound pv e2e4')
                for rank, (cp, wdl, move) in enumerate([(10, '40 920 40', 'e2e4'), (5, '90 870 40', 'd2d4'),
                                                         (-30, '10 900 90', 'a2a3'), (-200, '0 600 400', 'h2h3')], 1):
                    say('info depth 6 multipv %d score cp %d wdl %s pv %s' % (rank, cp, wdl, move))
                # stopped part way through depth 7: one line of it, which a mix of depths would list twice
                say('info depth 7 multipv 1 score cp 8 wdl 80 880 40 pv d2d4')
                say('bestmove e2e4')
            else:
                say('info depth 5 score cp 10 upperbound pv a2a3')
                say('info depth 6 score cp 42 nps 123456 pv e2e4')
                say('bestmove ' + ('e2e4' if not moves else 'e7e5'))
        elif line == 'quit':
            break
''').replace('LOSING_ON_MOVES', repr(LOSING_ON)).replace('HOLDING_ON_MOVES', repr(HOLDING_ON))


# the game after moves, and the position history (one key per ply) the game keeps
def playedOut(moves):
    gs = GameState()
    history = [gs.getPositionKey()]
    for code in moves:
        gs.makeMove(gs.findMoveByCode(code, gs.getValidMoves()))
        history.append(gs.getPositionKey())
    return gs, history


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

    def test_lines_of_a_multi_line_search(self):
        self.assertEqual(stockfish.parseLine('info depth 6 multipv 2 score cp -30 pv a2a3 e7e5'),
                         (2, ('a2a3', ('cp', -30))))
        self.assertIsNone(stockfish.parseLine('info depth 6 multipv 2 score cp -30 lowerbound pv a2a3'), "a bound")
        self.assertIsNone(stockfish.parseLine('info depth 6 score cp -30 pv a2a3'), "no rank")
        self.assertIsNone(stockfish.parseLine('info string NNUE enabled'))
        self.assertEqual(stockfish.lineDepth('info depth 17 seldepth 20 multipv 1 score cp 3 pv e2e4'), 17)
        self.assertEqual(stockfish.lineDepth('info string NNUE enabled'), 0)
        # depth 9 finished, depth 10 stopped after its first line: depth 9's lines, d3 once
        byDepth = {9: {1: ('d2d3', ('cp', 4)), 2: ('b1c3', ('cp', 0)), 3: ('d1e2', ('cp', -23))},
                   10: {1: ('b1c3', ('cp', 6))}}
        self.assertEqual(stockfish.bestLines(byDepth), [('d2d3', 0.04, None), ('b1c3', 0.0, None),
                                                        ('d1e2', -0.23, None)])
        self.assertEqual(stockfish.bestLines({5: {1: ('e2e4', ('cp', 10)), 2: ('e2e4', ('cp', 9))}}),
                         [('e2e4', 0.1, None)], "a move listed once")
        self.assertEqual(stockfish.bestLines({5: {1: ('e2e4', ('cp', 10), (60, 900, 40))}}),
                         [('e2e4', 0.1, (60, 900, 40))], "with its win/draw/loss chances")
        self.assertEqual(stockfish.bestLines({}), [])
        self.assertEqual(stockfish.parseWdl('info depth 20 multipv 2 score cp 12 wdl 61 912 27 nodes 9 pv e2e4'),
                         (61, 912, 27))
        self.assertIsNone(stockfish.parseWdl('info depth 20 score cp 12 pv e2e4'))
        self.assertTrue(stockfish.isDrawish(0.0) and stockfish.isDrawish(-0.3) and stockfish.isDrawish(0.3))
        self.assertFalse(stockfish.isDrawish(0.31) or stockfish.isDrawish(-1.5) or stockfish.isDrawish(None))

    def test_the_winning_try_of_a_drawish_position(self):
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.engine  # the stand-in answers for the hint engine too

        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            gs = GameState()
            moves = gs.getValidMoves()
            best = gs.findMoveByCode('e2e4', moves)
            found = await stockfish.searchWinningTry(gs, moves, 0.05, best=best, score=0.0)
            single = await stockfish.engine.go([], 0.05)
            # its own search finds d4 0.42 worse for White: more than ALTERNATIVE_MARGIN below a hint scoring 0.5
            dropped = await stockfish.searchWinningTry(gs, moves, 0.05, best=best, score=0.5)
            return found, single, dropped, len(gs.moveLog)

        try:
            found, single, dropped, plies = asyncio.run(run())
        finally:
            stockfish.hintEngine = saved
        self.assertEqual((found['move'].getCode(), found['score'], found['wdl'], found['hintWdl']),
                         ('d2d4', -0.42, (90, 870, 40), (40, 920, 40)),
                         "d4 wins more often than the hint's e4, and its own search keeps it within the margin")
        self.assertIsNone(dropped)
        self.assertEqual(plies, 0, "the board is set back")
        sent = self.commands()
        self.assertIn('setoption name MultiPV value %d' % stockfish.ALTERNATIVE_LINES, sent)
        self.assertIn('position startpos moves d2d4', sent, "the try gets a search of its own")
        self.assertEqual(len(single), 2, "a normal search still returns (move, score) only")
        self.assertEqual(sent[sent.index('setoption name MultiPV value 4'):].count('setoption name MultiPV value 1'),
                         sent.count('setoption name MultiPV value 4'),
                         "every search after a multi-line one goes back to the single best line")

    def test_picking_the_winning_try(self):
        lines = [('e2e4', 0.1, (40, 920, 40)), ('d2d4', 0.05, (90, 870, 40)), ('c2c4', -0.15, (110, 800, 90)),
                 ('a2a3', -0.3, (200, 500, 300)), ('h2h3', -2.0, (0, 600, 400))]
        self.assertEqual(stockfish.pickWinningTry(lines, 'e2e4'), ('c2c4', -0.15, (110, 800, 90), (40, 920, 40)),
                         "the best chance of winning among the moves within TRY_MARGIN (a3 is 0.4 worse)")
        self.assertIsNone(stockfish.pickWinningTry(lines, 'c2c4'),
                          "the hint's own move is never the try: c4 already has the best chances")
        self.assertIsNone(stockfish.pickWinningTry([('e2e4', 0.0, (40, 920, 40)), ('d2d4', 0.0, (50, 910, 40))],
                                                   'e2e4'), "10 per mille better is not enough for a try")
        self.assertEqual(stockfish.pickWinningTry([('e2e4', 0.0, (40, 920, 40)), ('d2d4', 0.0, (60, 900, 40)),
                                                   ('c2c4', 0.0, (60, 920, 20))], 'e2e4')[0], 'c2c4',
                         "the same chance of winning: fewer losses")
        self.assertIsNone(stockfish.pickWinningTry([('e2e4', 0.0, (40, 920, 40)), ('d2d4', 998.0, (999, 1, 0))],
                                                   'e2e4'), "no forced mate either way")
        self.assertIsNone(stockfish.pickWinningTry([('e2e4', 0.0, None), ('d2d4', 0.0, None)], 'e2e4'),
                          "no win/draw/loss chances: no try")
        self.assertIsNone(stockfish.pickWinningTry([], 'e2e4'))

    def test_the_hint_thinks_longer_where_there_is_more_to_find(self):
        def seconds(fen=None, moves=()):
            gs = GameState.fromFen(fen) if fen else GameState()
            for code in moves:
                gs.makeMove(gs.findMoveByCode(code, gs.getValidMoves()))
            return stockfish.hintSeconds(gs, gs.getValidMoves())
        self.assertEqual(seconds(), stockfish.HINT_OPENING_SECONDS, "the opening")
        middlegame = 'r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 9'
        self.assertGreaterEqual(seconds(middlegame), 10.5, "a full middlegame: near HINT_MAX_SECONDS")
        self.assertLessEqual(seconds(middlegame), stockfish.HINT_MAX_SECONDS)
        rooks = seconds('8/5pk1/6p1/8/8/6P1/5PK1/R6r w - - 0 40')
        pawns = seconds('8/5pk1/6p1/8/8/6P1/5PK1/8 w - - 0 50')
        self.assertTrue(stockfish.HINT_BASE_SECONDS < pawns < rooks < 8, (pawns, rooks))
        self.assertEqual(seconds('7k/8/6QK/8/8/8/8/8 b - - 0 60'), stockfish.HINT_FORCED_SECONDS,
                         "nothing to choose between")

    def test_the_coachs_pick_gets_a_search_of_its_own(self):
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.engine  # the stand-in answers for the hint engine too

        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            gs = GameState()
            quiet = await stockfish.checkAlternative(gs, gs.findMoveByCode('e2e4', gs.getValidMoves()), 0.05)
            restored = (len(gs.moveLog), gs.whiteToMove)
            fools = GameState()
            for code in ('f2f3', 'e7e5'):
                fools.makeMove(fools.findMoveByCode(code, fools.getValidMoves()))
            # 2. g4 walks into a mate in one (the stand-in scores it so for Black)
            blunder = await stockfish.checkAlternative(fools, fools.findMoveByCode('g2g4', fools.getValidMoves()), 0.05)
            fools.makeMove(fools.findMoveByCode('g2g4', fools.getValidMoves()))
            sent = len(self.commands())
            mates = await stockfish.checkAlternative(fools, fools.findMoveByCode('d8h4', fools.getValidMoves()), 0.05)
            return quiet, restored, blunder, mates, sent == len(self.commands())

        try:
            quiet, restored, blunder, mates, unsearched = asyncio.run(run())
        finally:
            stockfish.hintEngine = saved
        self.assertEqual(quiet, -0.42, "the search scores the reply for the opponent: the move's score is its negative")
        self.assertEqual(restored, (0, True), "the board is set back")
        self.assertLess(blunder, -chessAi.MATE_THRESHOLD)
        self.assertEqual(mates, chessAi.CHECKMATE)
        self.assertTrue(unsearched, "a move that mates needs no search")
        self.assertTrue(stockfish.alternativeHolds(-0.42, 0.0))
        self.assertFalse(stockfish.alternativeHolds(-0.6, 0.0), "more than ALTERNATIVE_MARGIN worse than the hint")
        self.assertFalse(stockfish.alternativeHolds(blunder, 0.0), "a forced mate against it")
        self.assertFalse(stockfish.alternativeHolds(None, 0.0), "not searched: not shown")
        self.assertTrue(stockfish.alternativeHolds(mates, 0.0))
        self.assertTrue(stockfish.alternativeHolds(0.1, None))

    def test_no_winning_try_without_the_hint_engine_or_with_one_move(self):
        async def run():
            gs = GameState()
            moves = gs.getValidMoves()
            return (await stockfish.searchWinningTry(gs, moves, 0.05),
                    await stockfish.searchWinningTry(gs, moves[:1], 0.05))
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.Engine([sys.executable, '-c', 'import time; time.sleep(30)'], channel='hint')
        try:
            self.assertEqual(asyncio.run(run()), (None, None))
        finally:
            stockfish.hintEngine.close()
            stockfish.hintEngine = saved

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

    def test_a_game_from_a_fen_is_sent_from_its_fen(self):
        # a puzzle or one of the player's mistakes starts from a FEN: the moves go after it, not after the start
        fen = "rnbqkbnr/pppppppp/8/8/8/5P2/PPPPP1PP/RNBQKBNR b KQkq - 0 1"

        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            gs = GameState.fromFen(fen)
            gs.makeMove(gs.findMoveByCode('e7e5', gs.getValidMoves()))
            await stockfish.analyzePosition(gs, gs.getValidMoves(), 0.05)
            await stockfish.searchPosition(GameState(), GameState().getValidMoves(), 0.05)
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.engine  # the stand-in answers for the analysis too
        try:
            asyncio.run(run())
        finally:
            stockfish.hintEngine = saved
        sent = self.commands()
        self.assertIn('position fen %s moves e7e5' % fen, sent)
        self.assertIn('position startpos', sent, "a game from the start goes as before")

    def test_a_repetition_draw_only_when_playing_on_loses(self):
        self.assertTrue(stockfish.takesTheDraw(-0.6))
        self.assertFalse(stockfish.takesTheDraw(-0.4))
        self.assertFalse(stockfish.takesTheDraw(None))
        script = os.path.join(self.folder.name, 'fakefish.py')
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.Engine([sys.executable, script, self.log + '.hint'], channel='hint')

        async def run(moves):
            gs, history = playedOut(moves)
            valid = gs.getValidMoves()
            self.assertTrue(await stockfish.hintEngine.ready(10))
            ai = await stockfish.findBestMove(gs, valid, level=4, history=history)
            hint = await stockfish.searchHintPosition(gs, valid, 0.05, history=history)
            return ai.getCode(), (hint[1].getCode(), hint[0])
        try:
            losing = asyncio.run(run(LOSING_ON))
            holding = asyncio.run(run(HOLDING_ON))
        finally:
            stockfish.hintEngine.close()
            stockfish.hintEngine = saved
        self.assertEqual(losing, ('f6g8', ('f6g8', 0.0)), "every other move loses: the draw")
        self.assertEqual(holding, ('h7h6', ('h7h6', -0.1)), "a move about as good as the draw: play on")

    def test_a_hint_doesnt_wait_for_the_hint_engine_to_load(self):
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.Engine([sys.executable, '-c', 'import time; time.sleep(30)'], channel='hint')

        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            gs = GameState()
            gs.makeMove(gs.findMoveByCode('e2e4', gs.getValidMoves()))
            start = time.time()
            found = await stockfish.searchHintPosition(gs, gs.getValidMoves(), 0.05)
            return found, time.time() - start, stockfish.hintEngine.state
        try:
            (score, move, _), seconds, state = asyncio.run(run())
        finally:
            stockfish.hintEngine.close()
            stockfish.hintEngine = saved
        self.assertEqual(state, 'starting', "still loading")
        self.assertEqual((move.getCode(), score), ('e7e5', 0.42), "the gameplay engine answered")
        self.assertLess(seconds, 2, "without waiting READY_WAIT")

    def test_signing_in_starts_the_hint_engine(self):
        script = os.path.join(self.folder.name, 'fakefish.py')
        saved = stockfish.hintEngine
        stockfish.hintEngine = stockfish.Engine([sys.executable, script, self.log + '.hint'], channel='hint')

        async def run():
            stockfish.prepareHintEngine()
            self.assertEqual(stockfish.hintEngine.state, 'starting')
            return await stockfish.hintEngine.ready(10)
        try:
            self.assertTrue(asyncio.run(run()))
        finally:
            stockfish.hintEngine.close()
            stockfish.hintEngine = saved
        self.assertEqual(stockfish.saveState(), '', "nothing to save on desktop")
        self.assertEqual(stockfish.hintEngineParts()[0], 'stockfish/stockfish-dev-20261028-single-part-0.wasm')
        self.assertEqual(len(stockfish.hintEngineParts()), stockfish.HINT_WORKER_PARTS)

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

    def test_a_node_budget_for_the_tools(self):
        # tools/hint_match: a search of `seconds` becomes a node count, so a loaded machine doesn't change its result
        stockfish.engine.nodesPerSecond = 200000

        async def run():
            self.assertTrue(await stockfish.engine.ready(10))
            return await stockfish.engine.go([], 0.5, search_moves=['e2e4'])
        self.assertEqual(asyncio.run(run()), ('e2e4', 0.42))
        self.assertIn('go nodes 100000 searchmoves e2e4', self.commands(), "searchmoves still last")
        self.assertEqual(stockfish.engine.lastNps, 123456, "the nodes per second it reported")
        self.assertEqual(stockfish.lineNps('info depth 6 score cp 42 pv e2e4'), None)

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

    def test_the_threaded_hint_engine_is_the_one_the_build_downloads(self):
        import json
        with open(os.path.join(support.ROOT, 'package.json'), encoding='utf-8') as f:
            build = json.load(f)['scripts']['build']
        name = os.path.basename(stockfish.HINT_THREADED_URL)  # stockfish-19.js, the multi-threaded full build
        self.assertNotIn('single', name)
        folder = 'game/build/web/stockfish/'
        for file in (name, name[:-len('.js')] + '.wasm'):
            self.assertIn('-o %s%s https://unpkg.com/stockfish@19.0.1/bin/%s' % (folder, file, file), build)
        base = name[:-len('.js')]
        # split into parts the worker joins, and the build stops if their count isn't HINT_THREADED_PARTS
        self.assertIn('split -b 25000000 -d -a 1 --additional-suffix=.wasm %s%s.wasm %s%s-part-' % (folder, base, folder, base),
                      build)
        self.assertIn('rm %s%s.wasm' % (folder, base), build, "only the parts are served")
        self.assertIn('ls %s%s-part-*.wasm | wc -l) -eq %d ]' % (folder, base, stockfish.HINT_THREADED_PARTS), build)
        self.assertEqual(stockfish.threadedParts()[0], 'stockfish/%s-part-0.wasm' % base)
        self.assertEqual(len(stockfish.threadedParts()), stockfish.HINT_THREADED_PARTS)
        self.assertLessEqual(stockfish.HINT_THREADED_PARTS, 10, "split -a 1 names ten parts at most")

    def test_the_site_can_run_engine_threads(self):
        import json
        with open(os.path.join(support.ROOT, 'vercel.json'), encoding='utf-8') as f:
            config = json.load(f)
        headers = {h['key']: h['value'] for rule in config['headers'] if rule['source'] == '/(.*)' for h in rule['headers']}
        self.assertEqual(headers.get('Cross-Origin-Opener-Policy'), 'same-origin')
        # credentialless, not require-corp: the page still loads pygbag's runtime from its CDN, which sends no CORP
        self.assertEqual(headers.get('Cross-Origin-Embedder-Policy'), 'credentialless')
        # Vercel bundles the project's files into the account function, the built site too: its engines (over 230 MB)
        # would take the function past Vercel's 225 MB limit
        self.assertEqual(config['functions']['api/account.py'].get('excludeFiles'), 'game/build/**')

    def test_hint_threads(self):
        self.assertEqual(stockfish.hintThreads(20), stockfish.HINT_MAX_THREADS)
        self.assertEqual(stockfish.hintThreads(8), 8 - stockfish.SPARE_CORES)
        self.assertEqual(stockfish.hintThreads(3), 1)
        self.assertEqual(stockfish.hintThreads(None), 1)
        self.assertEqual(stockfish.browserThreads(), 1, "desktop: no browser threads")

    def test_the_hint_engine_runs_more_threads_than_the_computers(self):
        from unittest import mock
        script = os.path.join(self.folder.name, 'fakefish.py')

        def started(cores):
            """The (Threads, Hash) each engine is sent on a desktop with that many cores: (computer's, hint's)."""
            computerLog = os.path.join(self.folder.name, 'computer-%d.txt' % cores)
            hintLog = os.path.join(self.folder.name, 'hint-%d.txt' % cores)
            computer = stockfish.Engine([sys.executable, script, computerLog])
            hint = stockfish.Engine([sys.executable, script, hintLog], channel='hint', hint=True)

            async def run():
                return await computer.ready(10), await hint.ready(10)
            try:
                with mock.patch('os.cpu_count', return_value=cores):
                    self.assertEqual(asyncio.run(run()), (True, True))
            finally:
                computer.close()
                hint.close()

            def options(log, engine):
                with open(log) as f:
                    sent = f.read().split('\n')
                threads = [int(line.split()[-1]) for line in sent if line.startswith('setoption name Threads value')]
                hashes = [int(line.split()[-1]) for line in sent if line.startswith('setoption name Hash value')]
                self.assertEqual(threads, [engine.threads])
                # the winning try reads each line's win/draw/loss chances: the hint engine only reports them
                self.assertEqual('setoption name UCI_ShowWDL value true' in sent, engine.hint)
                return threads[0], hashes[0]
            return options(computerLog, computer), options(hintLog, hint)
        self.assertEqual(started(16), ((4, stockfish.HASH_MB), (stockfish.HINT_MAX_THREADS, stockfish.HINT_HASH_MB)))
        self.assertEqual(started(8), ((4, stockfish.HASH_MB), (6, stockfish.HINT_HASH_MB)))
        self.assertEqual(started(2), ((1, stockfish.HASH_MB), (1, stockfish.HASH_MB)), "one thread: the usual hash")

    def test_a_tool_can_fix_the_threads(self):
        script = os.path.join(self.folder.name, 'fakefish.py')
        log = os.path.join(self.folder.name, 'fixed.txt')
        computer = stockfish.Engine([sys.executable, script, log], threads=1)
        try:
            self.assertTrue(asyncio.run(computer.ready(10)))
        finally:
            computer.close()
        with open(log) as f:
            self.assertIn('setoption name Threads value 1', f.read().split('\n'), "whatever the machine has")

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
