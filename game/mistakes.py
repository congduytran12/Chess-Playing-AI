# Your mistakes: the moves of the player's own games that the analysis marked as mistakes (? and ??), as puzzles.
# Each is a puzzle like those of puzzles.txt: the position before the opponent's move that led to the mistake, that
# move and the best answer (the analysis's), plus the move played in the game. Another move that scores about as well
# as the best solves it too (main.py judges it with a search). A signed-in player's mistakes are kept with the account
# (api/account.py): Premium brings back those of every game until each is solved twice in a row, without it the
# latest game's.

import re
from datetime import datetime, timezone

from engine import GameState
from puzzles import Puzzle

MISTAKE_MARKS = ("??", "?")  # the analysis marks that make a puzzle (an inaccuracy, ?!, doesn't)
MAX_PER_GAME = 30  # the mistakes of one game kept at most (the account takes no more at once)
SCORE_CAP = 10  # scores are kept within +-this many pawns (a mate is a won position, like main.EVAL_CAP)


class Mistake(Puzzle):
    """A puzzle from the player's own game. played: the move of the game (a code); score: the best move's score for
    the player in pawns; loss: what the move played lost against it; ply: the move's index in the game; opponent: who
    the game was against; id: the account's id for it (None until it is kept there)."""

    def __init__(self, fen, moves, played, score, loss=0.0, opponent="", ply=0, mistakeId=None):
        super().__init__(mistakeId, fen, moves, 0, [])
        self.played = played
        self.score = score
        self.loss = loss
        self.opponent = opponent
        self.ply = ply

    @property
    def key(self):
        """The same mistake has the same key in any game (the account keeps it once)."""
        return self.fen, " ".join(self.moves), self.played

    def payload(self):
        """As the account keeps it (see api/account.py)."""
        return {'fen': self.fen, 'moves': " ".join(self.moves), 'played': self.played, 'score': round(self.score, 2),
                'loss': round(self.loss, 2), 'opponent': self.opponent, 'ply': self.ply}


def capped(score):
    return max(-SCORE_CAP, min(SCORE_CAP, score))


def fromGame(moveLog, best, evals, marks, colors, opponent=""):
    """The mistakes of an analyzed game played from the starting position. best and evals: the analysis's best move
    (a code) and score (in pawns, from White's point of view) for each position; marks: ply -> (mark, pawns lost)
    (main.moveMarks); colors: the sides whose moves count ('w', 'b' or 'wb'). A mistake on the game's first move has
    no move of the opponent before it, so it is left out."""
    found = []
    board = GameState()
    previous = None  # the FEN before the last move
    for ply, move in enumerate(moveLog):
        fen = board.toFen()
        mark = marks.get(ply)
        if (previous is not None and mark and mark[0] in MISTAKE_MARKS and move.pieceMoved[0] in colors
                and ply < min(len(best), len(evals)) and best[ply] and len(found) < MAX_PER_GAME):
            score = evals[ply] if move.pieceMoved[0] == 'w' else -evals[ply]
            found.append(Mistake(previous, [moveLog[ply - 1].getCode(), best[ply]], move.getCode(), capped(score),
                                 mark[1], opponent, ply))
        previous = fen
        board.makeMove(move)
    return found


def secondsUntil(moment, now=None):
    """Seconds from now (a datetime; the current time when None) until moment, a time the account sent (ISO 8601);
    None for one that can't be read."""
    if not isinstance(moment, str):
        return None
    text = re.sub(r'\.(\d+)', lambda m: '.' + (m.group(1) + '000000')[:6], moment.replace('Z', '+00:00'))
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when - (now or datetime.now(timezone.utc))).total_seconds()


def fromRow(row):
    """A Mistake from a row the account sent, or None when it doesn't make one."""
    try:
        moves = str(row['moves']).split()
        if len(moves) != 2:
            return None
        mistake = Mistake(str(row['fen']), moves, str(row['played']), float(row['score']),
                          float(row.get('loss') or 0), str(row.get('opponent') or ""), int(row.get('ply') or 0),
                          row.get('id'))
        gs, _ = mistake.start()  # the moves must be legal in turn, and so must the move played instead
        answers = gs.getValidMoves()
        if gs.findMoveByCode(moves[1], answers) is None or gs.findMoveByCode(mistake.played, answers) is None:
            return None
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None
    return mistake
