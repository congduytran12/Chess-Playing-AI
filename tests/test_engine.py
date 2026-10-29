import unittest

from support import fromFen, play
from engine import GameState


def perft(gs, depth):
    """Counts the leaf positions depth plies ahead; promotions count once per piece choice."""
    moves = gs.getValidMoves()
    if depth == 1:
        return sum(4 if move.isPawnPromotion else 1 for move in moves)
    total = 0
    for move in moves:
        for choice in ('QRBN' if move.isPawnPromotion else 'Q'):
            move.promotionChoice = choice
            gs.makeMove(move)
            total += perft(gs, depth - 1)
            gs.undoMove()
    return total


# well-known positions with their published move counts (chessprogramming.org "Perft Results")
PERFT = [
    ('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', [20, 400, 8902]),
    ('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', [48, 2039]),  # "Kiwipete"
    ('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1', [14, 191, 2812]),
    ('r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1', [6, 264, 9467]),
    ('rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8', [44, 1486]),
    ('r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10', [46, 2079]),
]


class MoveGenerationTest(unittest.TestCase):
    def test_perft(self):
        for fen, counts in PERFT:
            for depth, expected in enumerate(counts, 1):
                with self.subTest(fen=fen, depth=depth):
                    self.assertEqual(perft(fromFen(fen), depth), expected)

    def codes(self, fen):
        return {move.getCode() for move in fromFen(fen).getValidMoves()}

    def test_pinned_queen_stays_on_the_pin_line(self):
        # the d8 queen is pinned along the 8th rank by the c8 queen: it may not leave the rank
        moves = self.codes('rnQq1k1r/pp2bppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R b KQ - 0 8')
        self.assertIn('d8c8', moves)
        self.assertNotIn('d8d1', moves)

    def test_pinned_pawn_moves_along_the_pin(self):
        # king in front of its pawn on the file: the pawn may still advance
        self.assertIn('e5e6', self.codes('8/4K3/8/4P3/8/8/8/k3r3 w - - 0 1'))
        # pinned on a diagonal toward its own king: en passant along that diagonal is legal
        self.assertIn('e5d6', self.codes('8/2K5/8/3pP3/8/6b1/8/k7 w - d6 0 1'))

    def test_en_passant_that_exposes_the_king_on_the_rank(self):
        # both pawns leave the 5th rank, which would open it to the rook
        self.assertNotIn('e5d6', self.codes('8/8/8/K2pP2r/8/8/8/7k w - d6 0 1'))

    def test_castling_rules(self):
        self.assertIn('e1g1', self.codes('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1'))
        # the rook on f3 attacks f1: no kingside castling through it, queenside is still fine
        moves = self.codes('r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1')
        self.assertNotIn('e1g1', moves)
        self.assertIn('e1c1', moves)

    def test_make_and_undo_restore_everything(self):
        gs = fromFen('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1')
        before = (gs.getPositionKey(), gs.whiteKinglocation, gs.blackKinglocation)
        for move in gs.getValidMoves():
            gs.makeMove(move)
            for reply in gs.getValidMoves():
                gs.makeMove(reply)
                gs.undoMove()
            gs.undoMove()
            self.assertEqual((gs.getPositionKey(), gs.whiteKinglocation, gs.blackKinglocation), before, move.getCode())


class NotationAndDrawsTest(unittest.TestCase):
    def test_san_round_trip(self):
        gs = GameState()
        moves = gs.getValidMoves()
        sans = []
        for code in "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5c6 d7c6 e1g1 f7f6".split():
            move = gs.findMoveByCode(code, moves)
            moves = gs.makeMoveWithSan(move, moves)
            sans.append(move.san)
        self.assertEqual(sans, ['e4', 'e5', 'Nf3', 'Nc6', 'Bb5', 'a6', 'Bxc6', 'dxc6', 'O-O', 'f6'])
        replay = GameState()
        for san in sans:
            replay.makeMove(replay.findMoveBySan(san, replay.getValidMoves()))
        self.assertEqual(replay.getPositionKey(), gs.getPositionKey())

    def test_checkmate_and_stalemate(self):
        gs = play(GameState(), "f2f3 e7e5 g2g4 d8h4")
        gs.getValidMoves()
        self.assertTrue(gs.checkmate)
        stalemate = fromFen('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')
        stalemate.getValidMoves()
        self.assertTrue(stalemate.stalemate)

    def test_insufficient_material(self):
        self.assertTrue(fromFen('8/8/8/8/8/8/8/K1k1B3 w - - 0 1').insufficientMaterial())
        self.assertFalse(fromFen('8/8/8/8/8/8/8/K1k1R3 w - - 0 1').insufficientMaterial())


if __name__ == '__main__':
    unittest.main()
