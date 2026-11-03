# Chess puzzles: positions where the player has to find the best moves, one after the other. The puzzles are in
# puzzles.txt (picked from the Lichess puzzle database, CC0, by tools/make_puzzles.py): one per line,
#
#     id|FEN|moves|rating|themes
#
# FEN is the position before the opponent's move, which is the first of the moves (UCI); the player finds the
# next one, the opponent answers with the one after it, and so on. The player's rating, the puzzles solved and the
# streak are kept on this device (browser localStorage, or a file in the home folder on desktop).

import os
import re
import sys
import json
import random

from engine import GameState

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'puzzles.txt')
STORAGE_KEY = "chess_ai_puzzles"
STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".chess-playing-ai-puzzles.json")  # desktop only
START_RATING = 1000
RATING_K = 24  # how far one puzzle moves the rating
RATING_RANGE = 120  # the next puzzle is picked within this many points of the player's rating when there is one
MAX_REMEMBERED = 2000  # solved puzzles kept in the list of those not to show again

_puzzles = None  # the puzzles from DATA_FILE, loaded once
_saved = None  # {'rating', 'solved': [ids], 'streak', 'best', 'attempts'}, read from storage once


class Puzzle:
    def __init__(self, puzzleId, fen, moves, rating, themes):
        self.id = puzzleId
        self.fen = fen
        self.moves = moves  # UCI codes: the opponent's first, then the player's, and so on
        self.rating = rating
        self.themes = themes

    @property
    def color(self):
        """The player's color, 'w' or 'b': the side to move once the opponent's first move is played."""
        return 'b' if self.fen.split()[1] == 'w' else 'w'

    def start(self):
        """The position the player sees: the FEN with the opponent's first move played. Returns (GameState, Move)."""
        gs = GameState.fromFen(self.fen)
        validMoves = gs.getValidMoves()
        move = gs.findMoveByCode(self.moves[0], validMoves)
        gs.makeMoveWithSan(move, validMoves)
        return gs, move

    @property
    def themeLabels(self):
        return [themeLabel(theme) for theme in self.themes]

    @property
    def themeText(self):
        return " · ".join(self.themeLabels)


def themeLabel(theme):
    """A theme as the database writes it, as a label: discoveredAttack -> Discovered attack, mateIn2 -> Mate in 2."""
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', theme)
    words = re.sub(r'([a-z])(\d)', r'\1 \2', words).lower()
    return words[:1].upper() + words[1:]


def load():
    """All puzzles, easiest first."""
    global _puzzles
    if _puzzles is None:
        _puzzles = []
        try:
            with open(DATA_FILE, encoding='utf-8') as f:
                for line in f:
                    fields = line.rstrip('\n').split('|')
                    if len(fields) == 5:
                        _puzzles.append(Puzzle(fields[0], fields[1], fields[2].split(), int(fields[3]),
                                               fields[4].split()))
        except (OSError, ValueError) as e:
            print("Puzzles: could not read the puzzles -", e)
        _puzzles.sort(key=lambda puzzle: puzzle.rating)
    return _puzzles


def find(puzzleId):
    for puzzle in load():
        if puzzle.id == puzzleId:
            return puzzle
    return None


def pick(rating=None, rng=random):
    """The next puzzle: one not solved yet, near the rating (the player's own by default), or the one nearest
    to it; once all are solved, the solved ones are forgotten and it starts over."""
    puzzles = load()
    if not puzzles:
        return None
    rating = current()['rating'] if rating is None else rating
    solved = set(current()['solved'])
    fresh = [puzzle for puzzle in puzzles if puzzle.id not in solved]
    if not fresh:
        current()['solved'] = []
        _store()
        fresh = puzzles
    near = [puzzle for puzzle in fresh if abs(puzzle.rating - rating) <= RATING_RANGE]
    if near:
        return rng.choice(near)
    return min(fresh, key=lambda puzzle: abs(puzzle.rating - rating))


def newRating(rating, puzzleRating, solved):
    """The rating after a puzzle: Elo against the puzzle's rating, a whole point for solving it, none for failing."""
    expected = 1 / (1 + 10 ** ((puzzleRating - rating) / 400))
    return max(100, round(rating + RATING_K * ((1 if solved else 0) - expected)))


def current():
    """The saved progress (a dict that can be changed; call finish() or save() to keep a change)."""
    global _saved
    if _saved is None:
        _saved = _clean(_load())
    return _saved


def _clean(saved):
    def whole(key, default, low=0):
        value = saved.get(key, default)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= low else default
    solved = saved.get('solved')
    return {'rating': whole('rating', START_RATING, 100), 'streak': whole('streak', 0), 'best': whole('best', 0),
            'attempts': whole('attempts', 0),
            'solved': [x for x in solved if isinstance(x, str)][-MAX_REMEMBERED:] if isinstance(solved, list) else []}


def finish(puzzle, solved, hinted=False):
    """The puzzle is over: solved (the first try, with no hint, changes the rating up; a failure down; a hint
    leaves the rating alone) or failed. Returns the rating change."""
    progress = current()
    before = progress['rating']
    progress['attempts'] += 1
    if solved:
        if puzzle.id not in progress['solved']:
            progress['solved'].append(puzzle.id)
            del progress['solved'][:-MAX_REMEMBERED]
        if not hinted:
            progress['rating'] = newRating(before, puzzle.rating, True)
        progress['streak'] += 1
        progress['best'] = max(progress['best'], progress['streak'])
    else:
        progress['rating'] = newRating(before, puzzle.rating, False)
        progress['streak'] = 0
    _store()
    return progress['rating'] - before


def save():
    _store()


def _load():
    try:
        if WASM:
            data = js.eval("localStorage.getItem(%s) || ''" % json.dumps(STORAGE_KEY)) if js is not None else ""
        elif os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE) as f:
                data = f.read()
        else:
            data = ""
        saved = json.loads(str(data)) if data else {}
    except Exception as e:
        print("Puzzles: could not read the progress -", e)
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _store():
    data = json.dumps(current())
    try:
        if WASM:
            if js is not None:
                js.eval("localStorage.setItem(%s, %s)" % (json.dumps(STORAGE_KEY), json.dumps(data)))
        else:
            with open(STORAGE_FILE, "w") as f:
                f.write(data)
    except Exception as e:
        print("Puzzles: could not save the progress -", e)
