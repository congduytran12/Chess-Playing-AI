# Shared setup for the tests: the game's modules import each other as top-level modules (see CLAUDE.md),
# so game/ goes on the path; pygame runs without a window or sound device.

import os
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, 'game')
API = os.path.join(ROOT, 'api')
if GAME not in sys.path:
    sys.path.insert(0, GAME)
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

from engine import GameState, Move, castleRights  # noqa: E402


def fromFen(fen):
    """A GameState set up from a FEN string (the game itself always starts from the initial position)."""
    gs = GameState()
    placement, side, castling, enPassant = fen.split()[:4]
    board = []
    for r, rowText in enumerate(placement.split('/')):
        row = []
        for ch in rowText:
            if ch.isdigit():
                row += ['--'] * int(ch)
                continue
            color = 'w' if ch.isupper() else 'b'
            piece = 'p' if ch.upper() == 'P' else ch.upper()
            row.append(color + piece)
            if piece == 'K':
                if color == 'w':
                    gs.whiteKinglocation = (r, len(row) - 1)
                else:
                    gs.blackKinglocation = (r, len(row) - 1)
        board.append(row)
    gs.board = board
    gs.whiteToMove = side == 'w'
    gs.whiteCastleKingside = 'K' in castling
    gs.whiteCastleQueenside = 'Q' in castling
    gs.blackCastleKingside = 'k' in castling
    gs.blackCastleQueenside = 'q' in castling
    gs.castleRightsLog = [castleRights(gs.whiteCastleKingside, gs.whiteCastleQueenside,
                                       gs.blackCastleKingside, gs.blackCastleQueenside)]
    gs.enpasantPossible = () if enPassant == '-' else (Move.ranksToRows[enPassant[1]], Move.filesToCols[enPassant[0]])
    gs.enpasantPossibleLog = [gs.enpasantPossible]
    return gs


def play(gs, codes):
    """Plays moves given in coordinate notation (e.g. "e2e4 e7e5") and returns gs."""
    for code in codes.split():
        move = gs.findMoveByCode(code, gs.getValidMoves())
        assert move is not None, "illegal move " + code
        gs.makeMove(move)
    return gs


def loadApi():
    """api/account.py, loaded under another name (game/account.py is 'account')."""
    spec = importlib.util.spec_from_file_location('api_account', os.path.join(API, 'account.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
