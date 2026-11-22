"""Plays the hint against the Impossible computer, offline, to measure how often following the hint wins.

Both sides are the native Stockfish of the desktop game (engines/, STOCKFISH_PATH or PATH), driven through the game's
own code: the hint player through stockfish.searchHintPosition (and stockfish.searchWinningTry), the computer through
stockfish.findBestMove at Impossible on one thread with the usual hash, as in the browser. The browser's Impossible
runs the Lite build, which is weaker than the full net here, so the computer here is the harder opponent.

    python tools/hint_match.py --policy adaptive-wdl --games 20 --parallel 2 --scale 0.25

Policies: baseline (5 s hints, the best move only, as the game played before), adaptive (hint time from
stockfish.hintSeconds, the best move only) and adaptive-wdl (adaptive, and the winning try whenever Stockfish offers
one in a drawish position). --scale multiplies every search time (the hint's, the try's and the computer's). Each game
starts from one of the opening book's lines (chessAi.BOOK_LINES, its first 6 plies), played once with each colour, and
runs in a process of its own; the PGNs and a JSON of each game are kept in a temporary folder.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

GAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'game')
sys.path.insert(0, GAME)

import chessAi  # noqa: E402
import stockfish  # noqa: E402
from engine import GameState  # noqa: E402

POLICIES = ('baseline', 'adaptive', 'adaptive-wdl')
OPENING_PLIES = 6
MAX_PLIES = 300  # a game this long is adjudicated a draw
IMPOSSIBLE = len(chessAi.LEVELS) - 1


def openings():
    """The book's distinct first OPENING_PLIES plies, as lists of SAN."""
    found = []
    for line in chessAi.BOOK_LINES:
        start = line.split()[:OPENING_PLIES]
        if start not in found:
            found.append(start)
    return found


def outcome(gs, moves, history):
    """'1-0', '0-1', '1/2-1/2' with the reason, or None while the game goes on."""
    if not moves:
        if gs.inCheck:
            return ('0-1' if gs.whiteToMove else '1-0'), 'checkmate'
        return '1/2-1/2', 'stalemate'
    if history.count(history[-1]) >= 3:
        return '1/2-1/2', 'threefold repetition'
    if gs.fiftyMoveRuleReached():
        return '1/2-1/2', '50-move rule'
    if gs.insufficientMaterial():
        return '1/2-1/2', 'insufficient material'
    if len(gs.moveLog) >= MAX_PLIES:
        return '1/2-1/2', 'adjudicated at %d plies' % MAX_PLIES
    return None


async def playGame(policy, opening, hintColor, scale):
    exe = stockfish.findExecutable()
    if exe is None:
        raise SystemExit("no Stockfish executable: put one in engines/ or set STOCKFISH_PATH")
    stockfish.engine = stockfish.Engine([exe], threads=1)  # the computer: one thread, the usual hash
    stockfish.hintEngine = stockfish.Engine([exe], channel='hint', hint=True, threads=stockfish.HINT_MAX_THREADS)
    name, seconds = chessAi.LEVELS[IMPOSSIBLE][:2]
    chessAi.LEVELS[IMPOSSIBLE] = (name, seconds * scale) + tuple(chessAi.LEVELS[IMPOSSIBLE][2:])
    if not (await stockfish.engine.ready(60) and await stockfish.hintEngine.ready(60)):
        raise SystemExit("Stockfish did not start")
    gs = GameState()
    history = [gs.getPositionKey()]
    sans, hintTimes, tries, hintScores = [], [], 0, []
    for san in opening:
        moves = gs.getValidMoves()
        move = gs.findMoveBySan(san, moves)
        sans.append(gs.getSan(move, moves))
        gs.makeMove(move)
        history.append(gs.getPositionKey())
    while True:
        moves = gs.getValidMoves()
        ended = outcome(gs, moves, history)
        if ended:
            break
        if ('w' if gs.whiteToMove else 'b') == hintColor:
            seconds = (5.0 if policy == 'baseline' else stockfish.hintSeconds(gs, moves)) * scale
            hintTimes.append(seconds)
            score, move, _ = await stockfish.searchHintPosition(gs, moves, seconds, history=history)
            hintScores.append(score)
            if policy == 'adaptive-wdl' and stockfish.isDrawish(score):
                found = await stockfish.searchWinningTry(gs, gs.getValidMoves(), 5.0 * scale, history=history,
                                                         best=move, score=score)
                moves = gs.getValidMoves()
                if found is not None:
                    move, tries = gs.findMoveByCode(found['move'].getCode(), moves), tries + 1
            move = gs.findMoveByCode(move.getCode(), moves)
        else:
            move = await stockfish.findBestMove(gs, moves, level=IMPOSSIBLE, history=history)
        sans.append(gs.getSan(move, moves))
        gs.makeMove(move)
        history.append(gs.getPositionKey())
    stockfish.engine.close()
    stockfish.hintEngine.close()
    result, reason = ended
    hintScore = {'1-0': 1.0, '0-1': 0.0}.get(result, 0.5)
    if hintColor == 'b':
        hintScore = 1.0 - hintScore
    return {'policy': policy, 'opening': ' '.join(opening), 'hintColor': hintColor, 'result': result,
            'reason': reason, 'hintScore': hintScore, 'plies': len(sans), 'tries': tries,
            'meanHintSeconds': round(sum(hintTimes) / len(hintTimes), 2) if hintTimes else 0,
            'minHintEval': min((s for s in hintScores if s is not None), default=None), 'sans': sans}


def pgn(game):
    white, black = ('Hint', 'Impossible') if game['hintColor'] == 'w' else ('Impossible', 'Hint')
    text = ''.join(('%d. ' % (i // 2 + 1) if i % 2 == 0 else '') + san + ' ' for i, san in enumerate(game['sans']))
    return ('[Event "Hint vs Impossible (%s)"]\n[White "%s"]\n[Black "%s"]\n[Result "%s"]\n[Termination "%s"]\n\n%s%s\n'
            % (game['policy'], white, black, game['result'], game['reason'], text, game['result']))


def orchestrate(policy, games, parallel, scale):
    folder = tempfile.mkdtemp(prefix='hint-match-')
    lines = openings()
    pairs = max(1, games // 2)
    chosen = [lines[round(i * (len(lines) - 1) / max(1, pairs - 1))] for i in range(pairs)] if pairs > 1 else lines[:1]
    jobs = [(i, line, color) for i, line in enumerate(chosen) for color in ('w', 'b')][:games]
    me = [sys.executable, os.path.abspath(__file__)]
    running, results, started = [], [], time.time()
    while jobs or running:
        while jobs and len(running) < parallel:
            i, line, color = jobs.pop(0)
            out = os.path.join(folder, 'game-%02d-%s.json' % (i, color))
            log = open(out[:-5] + '.log', 'w', encoding='utf-8')
            args = ['play', '--policy', policy, '--opening', ' '.join(line), '--color', color,
                    '--scale', str(float(scale)), '--out', out]
            running.append((subprocess.Popen(me + args, shell=False, stdout=log, stderr=subprocess.STDOUT), out, log))
        time.sleep(1)
        for job in [job for job in running if job[0].poll() is not None]:
            running.remove(job)
            proc, out, log = job
            log.close()
            if os.path.exists(out):
                with open(out, encoding='utf-8') as f:
                    game = json.load(f)
                results.append(game)
                with open(out[:-5] + '.pgn', 'w', encoding='utf-8') as f:
                    f.write(pgn(game))
                print("%-40s hint %s  %-7s %-26s %3d plies, %d tries, hint %.1f s on average"
                      % (game['opening'], game['hintColor'], game['result'], game['reason'], game['plies'],
                         game['tries'], game['meanHintSeconds']), flush=True)
            else:
                print("a game failed: see %s" % (out[:-5] + '.log'), flush=True)
    wins = sum(1 for g in results if g['hintScore'] == 1.0)
    losses = sum(1 for g in results if g['hintScore'] == 0.0)
    draws = len(results) - wins - losses
    score = sum(g['hintScore'] for g in results)
    print("\n%s: %d games, hint +%d =%d -%d (%.1f%%), %.0f min; games in %s"
          % (policy, len(results), wins, draws, losses, 100 * score / max(1, len(results)),
             (time.time() - started) / 60, folder))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command')
    play = sub.add_parser('play', help='one game (used by the match itself)')
    play.add_argument('--policy', choices=POLICIES, required=True)
    play.add_argument('--opening', required=True)
    play.add_argument('--color', choices=('w', 'b'), required=True)
    play.add_argument('--scale', type=float, default=0.25)
    play.add_argument('--out', required=True)
    parser.add_argument('--policy', choices=POLICIES, default='adaptive-wdl')
    parser.add_argument('--games', type=int, default=20)
    parser.add_argument('--parallel', type=int, default=2)
    parser.add_argument('--scale', type=float, default=0.25)
    args = parser.parse_args()
    if args.command == 'play':
        game = asyncio.run(playGame(args.policy, args.opening.split(), args.color, args.scale))
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(game, f)
        return
    orchestrate(args.policy, args.games, args.parallel, args.scale)


if __name__ == '__main__':
    main()
