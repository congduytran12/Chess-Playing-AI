"""
Picks the puzzles in game/puzzles.txt from the Lichess puzzle database (CC0, https://database.lichess.org/#puzzles).

Takes the database's CSV, or its .zst file (the first 40 MB of the download are enough: the puzzles in it are in no
particular order), and keeps PER_BIN well-liked puzzles of every 100 points of rating from 500 to 2400, short
enough to play (up to four moves of the player). One puzzle per line, separated by |:

    id|FEN (the position before the opponent's move)|moves (UCI; the first is the opponent's)|rating|themes

Needs zstandard for .zst files (pip install zstandard); the game itself doesn't.

    python tools/make_puzzles.py lichess_db_puzzle.csv.zst      # writes game/puzzles.txt
"""
import io
import os
import sys
import random

PER_BIN = 30
LOW, HIGH, STEP = 500, 2500, 100
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'game', 'puzzles.txt')
# themes that don't say what the puzzle is about
PLAIN = {'short', 'long', 'veryLong', 'oneMove', 'advantage', 'crushing', 'equality', 'master', 'masterVsMaster',
         'superGM', 'opening', 'middlegame', 'endgame'}


def readText(path):
    raw = open(path, 'rb').read()
    if not path.endswith('.zst'):
        return raw.decode('utf-8', errors='ignore')
    import zstandard
    out = io.BytesIO()
    try:
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            while True:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    except zstandard.ZstdError:
        pass  # a partial download ends in the middle of a frame
    return out.getvalue().decode('utf-8', errors='ignore')


def main(path):
    lines = readText(path).split('\n')[1:-1]  # no header, and the last line may be cut short
    bins = {}
    for line in lines:
        fields = line.split(',')
        if len(fields) < 8:
            continue
        puzzleId, fen, moves, rating, deviation, popularity, plays, themes = fields[:8]
        rating, deviation, popularity, plays = int(rating), int(deviation), int(popularity), int(plays)
        count = len(moves.split())
        if popularity < 90 or plays < 300 or deviation > 100 or not 2 <= count <= 8 or not LOW <= rating < HIGH:
            continue
        kept = [theme for theme in themes.split() if theme not in PLAIN][:3]
        bins.setdefault((rating - LOW) // STEP, []).append('|'.join((puzzleId, fen, moves, str(rating), ' '.join(kept))))
    rng = random.Random(2026)
    chosen = []
    for key in sorted(bins):
        chosen += rng.sample(bins[key], min(PER_BIN, len(bins[key])))
    chosen.sort(key=lambda row: int(row.split('|')[3]))
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(chosen) + '\n')
    print("%d puzzles in %d rating bins -> %s" % (len(chosen), len(bins), OUT))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
