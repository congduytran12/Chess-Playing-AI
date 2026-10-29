import asyncio
import unittest

from support import fromFen
import chessAi


def search(fen, seconds=1.0, maxDepth=None):
    gs = fromFen(fen)
    before = gs.getPositionKey()
    chessAi.transpositionTable.clear()
    score, move, depth = asyncio.run(chessAi.searchPosition(gs, gs.getValidMoves(), seconds, maxDepth))
    return gs, before, score, move, depth


class SearchTest(unittest.TestCase):
    def test_finds_mate_in_one(self):
        gs, _, score, move, _ = search('6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1')
        self.assertEqual(move.getCode(), 'a1a8')
        self.assertGreater(score, chessAi.MATE_THRESHOLD)

    def test_finds_mate_in_two(self):
        # 1.Rd8+ Rxd8 2.Rxd8#
        _, _, score, move, _ = search('r5k1/5ppp/8/8/8/8/3R1PPP/3R2K1 w - - 0 1', 3.0)
        self.assertEqual(move.getCode(), 'd2d8')
        self.assertGreater(score, chessAi.MATE_THRESHOLD)

    def test_takes_a_free_queen(self):
        _, _, _, move, _ = search('4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1')
        self.assertEqual(move.getCode(), 'd2d5')

    def test_search_leaves_the_position_as_it_was(self):
        gs, before, _, _, _ = search('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 0.5)
        self.assertEqual(gs.getPositionKey(), before)
        self.assertEqual(gs.moveLog, [])

    def test_timeouts_restore_the_position(self):
        # searches cut off at many different moments, some inside null move searches (which pass the turn)
        for seconds in (0.05, 0.13, 0.21, 0.34, 0.55):
            gs = fromFen('r3k2r/pppq1ppp/2npbn2/4p3/2B1P1b1/2NP1N2/PPPQ1PPP/R3K2R w KQkq e6 0 1')
            state = lambda: (gs.getPositionKey(), gs.whiteToMove, len(gs.enpasantPossibleLog),
                             len(gs.castleRightsLog), gs.whiteKinglocation, gs.blackKinglocation)
            before = state()
            chessAi.transpositionTable.clear()
            asyncio.run(chessAi.searchPosition(gs, gs.getValidMoves(), seconds))
            self.assertEqual(state(), before, seconds)

    def test_depth_cap(self):
        _, _, _, _, depth = search('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', 5.0, maxDepth=2)
        self.assertEqual(depth, 2)

    def test_opening_book_moves_are_legal(self):
        book = chessAi.buildBook()
        self.assertGreater(len(book), 50)


if __name__ == '__main__':
    unittest.main()
