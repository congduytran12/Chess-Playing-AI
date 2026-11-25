"""Plays the hint against the Impossible computer, offline, to measure how often following the hint wins.

The hint player is the desktop game's native Stockfish (engines/, STOCKFISH_PATH or PATH), driven through the game's
own code (stockfish.searchHintPosition, stockfish.searchWinningTry); the computer plays through stockfish.findBestMove
at Impossible on one thread with the usual hash, as in the browser. Two opponents (--profile):

    browser  the browser's own engine, Stockfish 19 Lite WASM, run by Node (engines/browser-lite/lite/, see LITE_JS)
    desktop  the native full-net engine on one thread: a stronger opponent than the site's

Times (--budget): 'time' searches for the seconds the game would (one match at a time per core set: see --parallel),
'nodes' turns those seconds into node counts measured once by `calibrate`, so matches can share the machine without
the load changing any search. --scale multiplies every search's seconds.

    python tools/hint_match.py calibrate --profile browser
    python tools/hint_match.py --policy adaptive-wdl --profile browser --budget nodes --games 64 --parallel 3 --record
    python tools/hint_match.py compare RUN_A RUN_B

Each game starts from an opening (--openings: book6, the opening book's distinct first 6 plies, each played with both
colours; startpos; or file:PATH, one line of SAN per opening), runs in a process of its own and is written to a run
folder under tools/hint_match_runs/ (git-ignored) that --resume continues. --record adds the result to
tools/hint_match_results.md. --sprt P0,P1 stops starting games once a sequential test on the hint's wins decides.
"""

import argparse
import asyncio
import datetime
import json
import math
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, 'game')
sys.path.insert(0, GAME)

import chessAi  # noqa: E402
import stockfish  # noqa: E402
from engine import GameState  # noqa: E402

# what each policy does on the hint's turn: hint 'fixed' (5 s, the game before adaptive hints) or 'adaptive'
# (stockfish.hintSeconds); winningTry: in a drawish position, play stockfish.searchWinningTry's move when it offers one
POLICY_CONFIG = {
    'baseline': {'hint': 'fixed', 'winningTry': False},
    'adaptive': {'hint': 'adaptive', 'winningTry': False},
    'adaptive-wdl': {'hint': 'adaptive', 'winningTry': True},
}
POLICIES = tuple(POLICY_CONFIG)
PROFILES = ('browser', 'desktop')
OPENING_PLIES = 6
MAX_PLIES = 300  # a game this long is adjudicated a draw
IMPOSSIBLE = len(chessAi.LEVELS) - 1
LITE_JS = os.path.join(ROOT, 'engines', 'browser-lite', 'lite', 'stockfish-19-lite-single.js')
RUNS = os.path.join(ROOT, 'tools', 'hint_match_runs')
RESULTS = os.path.join(ROOT, 'tools', 'hint_match_results.md')
CALIBRATION = os.path.join(ROOT, 'tools', 'hint_match_calibration.json')
CALIBRATE_SECONDS = 3.0
CALIBRATE_PLIES = (0, 12, 30)  # positions from each sampled opening: start, early middlegame, middlegame


# --- statistics (also used by tests/test_hint_match.py)

def wilson(k, n, z=1.96):
    """The Wilson score interval (low, high) of a proportion k/n."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def sprt(wins, games, p0=0.5, p1=0.65, alpha=0.05, beta=0.10):
    """Wald's sequential test on the share of games won (a draw or a loss is a 'no'): (log likelihood ratio,
    'H1' (the hint wins at least p1 of its games), 'H0' (at most p0) or None while undecided)."""
    others = games - wins
    llr = wins * math.log(p1 / p0) + others * math.log((1 - p1) / (1 - p0))
    if llr >= math.log((1 - beta) / alpha):
        return llr, 'H1'
    if llr <= math.log(beta / (1 - alpha)):
        return llr, 'H0'
    return llr, None


def mcnemar(onlyA, onlyB):
    """Exact two-sided McNemar p-value: of the paired games one policy won and the other didn't, onlyA went to A."""
    n = onlyA + onlyB
    if n == 0:
        return 1.0
    k = min(onlyA, onlyB)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def tally(games):
    """(wins, draws, losses) of the hint over games."""
    wins = sum(1 for g in games if g['hintScore'] == 1.0)
    losses = sum(1 for g in games if g['hintScore'] == 0.0)
    return wins, len(games) - wins - losses, losses


# --- openings

def bookOpenings():
    """The book's distinct first OPENING_PLIES plies, as lists of SAN."""
    found = []
    for line in chessAi.BOOK_LINES:
        start = line.split()[:OPENING_PLIES]
        if start not in found:
            found.append(start)
    return found


def openingSuite(name):
    """[(id, [SAN, ...])]: the openings a match plays, each with both colours."""
    if name == 'book6':
        return [('b%02d' % i, line) for i, line in enumerate(bookOpenings())]
    if name == 'startpos':
        return [('start', [])]
    if name.startswith('file:'):
        with open(name[5:], encoding='utf-8') as f:
            lines = [line.split('#')[0].split() for line in f]
        return [('f%03d' % i, line) for i, line in enumerate(line for line in lines if line)]
    raise SystemExit("unknown opening suite: %s" % name)


def jobsFor(suite, games):
    """The (opening id, SAN list, hint colour, repeat) jobs of a match of `games` games: each opening with White, then
    Black, spread over the suite; a suite smaller than the match plays its openings again (startpos: the same start)."""
    pairs = max(1, (games + 1) // 2)
    if pairs <= len(suite):
        chosen = [suite[round(i * (len(suite) - 1) / max(1, pairs - 1))] for i in range(pairs)] if pairs > 1 \
            else suite[:1]
        chosen = [(oid, line, 0) for oid, line in chosen]
    else:
        chosen = [(oid, line, i // len(suite)) for i, (oid, line) in enumerate(suite * (pairs // len(suite) + 1))]
        chosen = chosen[:pairs]
    return [(oid, line, color, rep) for oid, line, rep in chosen for color in ('w', 'b')][:games]


def jobKey(oid, color, rep):
    return '%s-%s-%d' % (oid, color, rep)


# --- engines

def nativeExecutable():
    exe = stockfish.findExecutable()
    if exe is None:
        raise SystemExit("no Stockfish executable: put one in engines/ or set STOCKFISH_PATH")
    return exe


def computerCommand(profile):
    if profile == 'browser':
        if not os.path.isfile(LITE_JS):
            raise SystemExit("the browser's engine is missing: download stockfish-19-lite-single.js and .wasm "
                             "(stockfish@19.0.1/bin on unpkg, as package.json does) into " + os.path.dirname(LITE_JS))
        return ['node', LITE_JS]
    return [nativeExecutable()]


def loadCalibration(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        raise SystemExit("no calibration at %s: run `hint_match.py calibrate` on an idle machine first" % path)


def setUpEngines(profile, hintThreads, budget, calibration, hintNps=None):
    """hintNps: the hint's nodes per second (--budget nodes), in place of the native engine's calibrated speed, to
    give it the browser's speed (its WASM build is slower than the native one)."""
    stockfish.engine = stockfish.Engine(computerCommand(profile), threads=1)  # the computer: one thread, usual hash
    stockfish.hintEngine = stockfish.Engine([nativeExecutable()], channel='hint', hint=True, threads=hintThreads)
    if budget == 'nodes':
        stockfish.engine.nodesPerSecond = calibration['computer'][profile]
        stockfish.hintEngine.nodesPerSecond = hintNps or calibration['hint'][str(hintThreads)]


# --- one game

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


async def hintMove(policy, gs, moves, history, scale):
    """The hint's move under policy, with (seconds asked, score, whether a winning try was played)."""
    config = POLICY_CONFIG[policy]
    seconds = (5.0 if config['hint'] == 'fixed' else stockfish.hintSeconds(gs, moves)) * scale
    score, move, _ = await stockfish.searchHintPosition(gs, moves, seconds, history=history)
    tried = False
    if config['winningTry'] and stockfish.isDrawish(score):
        found = await stockfish.searchWinningTry(gs, gs.getValidMoves(), 5.0 * scale, history=history,
                                                 best=move, score=score)
        if found is not None:
            move, tried = found['move'], True
    return move, seconds, score, tried


async def playGame(policy, opening, hintColor, scale, profile, budget, hintThreads, calibration, hintNps=None):
    setUpEngines(profile, hintThreads, budget, calibration, hintNps)
    name, seconds = chessAi.LEVELS[IMPOSSIBLE][:2]
    chessAi.LEVELS[IMPOSSIBLE] = (name, seconds * scale) + tuple(chessAi.LEVELS[IMPOSSIBLE][2:])
    if not (await stockfish.engine.ready(60) and await stockfish.hintEngine.ready(60)):
        raise SystemExit("Stockfish did not start")
    computerName = stockfish.engine.name
    gs = GameState()
    history = [gs.getPositionKey()]
    sans, hintTimes, tries, hintScores = [], [], 0, []
    for san in opening:
        moves = gs.getValidMoves()
        move = gs.findMoveBySan(san, moves)
        sans.append(gs.getSan(move, moves))
        gs.makeMove(move)
        history.append(gs.getPositionKey())
    started = time.time()
    while True:
        moves = gs.getValidMoves()
        ended = outcome(gs, moves, history)
        if ended:
            break
        if ('w' if gs.whiteToMove else 'b') == hintColor:
            move, seconds, score, tried = await hintMove(policy, gs, moves, history, scale)
            hintTimes.append(seconds)
            hintScores.append(score)
            tries += tried
            moves = gs.getValidMoves()
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
    known = [s for s in hintScores if s is not None]
    return {'policy': policy, 'profile': profile, 'budget': budget, 'scale': scale, 'computer': computerName,
            'opening': ' '.join(opening), 'hintColor': hintColor, 'result': result, 'reason': reason,
            'hintScore': hintScore, 'plies': len(sans), 'tries': tries,
            'meanHintSeconds': round(sum(hintTimes) / len(hintTimes), 2) if hintTimes else 0,
            'minHintEval': min(known, default=None), 'finalHintEval': known[-1] if known else None,
            'wallSeconds': round(time.time() - started), 'sans': sans}


def pgn(game):
    white, black = ('Hint', 'Impossible') if game['hintColor'] == 'w' else ('Impossible', 'Hint')
    text = ''.join(('%d. ' % (i // 2 + 1) if i % 2 == 0 else '') + san + ' ' for i, san in enumerate(game['sans']))
    return ('[Event "Hint vs Impossible (%s, %s)"]\n[White "%s"]\n[Black "%s"]\n[Result "%s"]\n[Termination "%s"]\n\n'
            '%s%s\n' % (game['policy'], game.get('profile', '?'), white, black, game['result'], game['reason'], text,
                        game['result']))


# --- a match

def readGames(folder):
    games = []
    path = os.path.join(folder, 'games.jsonl')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            games = [json.loads(line) for line in f if line.strip()]
    return games


def summary(games, label):
    wins, draws, losses = tally(games)
    n = len(games)
    low, high = wilson(wins, n)
    score = sum(g['hintScore'] for g in games)
    reasons = {}
    for g in games:
        if g['hintScore'] == 0.5:
            reasons[g['reason']] = reasons.get(g['reason'], 0) + 1
    return ("%s: %d games, hint +%d =%d -%d, wins %.0f%% (95%% %.0f-%.0f%%), score %.1f%%; draws: %s"
            % (label, n, wins, draws, losses, 100 * wins / max(1, n), 100 * low, 100 * high,
               100 * score / max(1, n), ', '.join('%s %d' % kv for kv in sorted(reasons.items())) or 'none'))


def record(folder, settings, games, verdict, minutes):
    wins, draws, losses = tally(games)
    n = len(games)
    low, high = wilson(wins, n)
    commit = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True,
                            text=True).stdout.strip()
    mean = sum(g['meanHintSeconds'] for g in games) / max(1, n)
    row = ('| %s | %s | %s | %s | %s | %s | %s | %d | +%d =%d -%d | %.0f%% (%.0f-%.0f%%) | %.1f%% | %s | %.1f | %.0f | %s |'
           % (datetime.date.today().isoformat(), commit, settings['policy'], settings['profile'],
              settings['budget'], settings['scale'], settings['openings'], n, wins, draws, losses, 100 * wins / max(1, n),
              100 * low, 100 * high, 100 * sum(g['hintScore'] for g in games) / max(1, n), verdict or '-', mean,
              minutes, os.path.basename(folder)))
    if not os.path.exists(RESULTS):
        with open(RESULTS, 'w', encoding='utf-8') as f:
            f.write(RESULTS_HEADER)
    with open(RESULTS, 'a', encoding='utf-8') as f:
        f.write(row + '\n')


RESULTS_HEADER = """# Hint vs Impossible: match results

Rows added by `python tools/hint_match.py ... --record` (see that file's docstring). Win % is the share of games the
hint won, with its 95% Wilson interval; score counts a draw as half. SPRT: the sequential test on wins (H1: the hint
wins at least 65% of games, H0: at most 50%), '-' when it was not run or did not decide. Hint s: the mean seconds the
hint was given per move (before --scale's node conversion). Profile browser: the computer is the site's Stockfish 19
Lite WASM run by Node; desktop: the native full net on one thread. The hint is the native engine in every row.

| Date | Commit | Policy | Profile | Budget | Scale | Openings | Games | +W =D -L | Win % | Score | SPRT | Hint s | Minutes | Run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def orchestrate(args):
    calibrationPath = args.calibration
    if args.budget == 'nodes':
        loadCalibration(calibrationPath)  # fail now, not in every game
    elif args.parallel * (args.hint_threads + 1) > (os.cpu_count() or 1) and not args.force:
        raise SystemExit("%d matches of %d hint threads + 1 for the computer don't fit %d cores: the load would weaken "
                         "the computer. Use --budget nodes, fewer --parallel, or --force"
                         % (args.parallel, args.hint_threads, os.cpu_count() or 1))
    if args.resume:
        folder = args.resume
        with open(os.path.join(folder, 'run.json'), encoding='utf-8') as f:
            settings = json.load(f)
    else:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
        folder = os.path.join(RUNS, '%s-%s-%s-%s-s%s' % (stamp, args.policy, args.profile, args.budget, args.scale))
        os.makedirs(folder)
        settings = {'policy': args.policy, 'profile': args.profile, 'budget': args.budget, 'scale': args.scale,
                    'openings': args.openings, 'games': args.games, 'hintThreads': args.hint_threads,
                    'calibration': calibrationPath if args.budget == 'nodes' else None, 'hintNps': args.hint_nps,
                    'commit': subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True,
                                             text=True).stdout.strip(),
                    'machine': platform.processor() or platform.machine(), 'cores': os.cpu_count()}
        with open(os.path.join(folder, 'run.json'), 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=1)
    games = readGames(folder)
    done = {g['job'] for g in games}
    jobs = [job for job in jobsFor(openingSuite(settings['openings']), settings['games'])
            if jobKey(job[0], job[2], job[3]) not in done]
    print("run folder %s: %d games done, %d to play" % (folder, len(games), len(jobs)), flush=True)
    me = [sys.executable, os.path.abspath(__file__)]
    running, started, verdict = [], time.time(), None
    while jobs or running:
        while jobs and len(running) < args.parallel and verdict is None:
            oid, line, color, rep = jobs.pop(0)
            key = jobKey(oid, color, rep)
            out = os.path.join(folder, 'game-%s.json' % key)
            log = open(out[:-5] + '.log', 'w', encoding='utf-8')
            play = ['play', '--policy', settings['policy'], '--opening', ' '.join(line), '--color', color,
                    '--scale', str(float(settings['scale'])), '--profile', settings['profile'],
                    '--budget', settings['budget'], '--hint-threads', str(settings['hintThreads']),
                    '--calibration', settings['calibration'] or calibrationPath, '--out', out]
            if settings.get('hintNps'):
                play += ['--hint-nps', str(settings['hintNps'])]
            running.append((subprocess.Popen(me + play, shell=False, stdout=log, stderr=subprocess.STDOUT),
                            out, log, key))
        if not running:
            break
        time.sleep(1)
        for job in [job for job in running if job[0].poll() is not None]:
            running.remove(job)
            proc, out, log, key = job
            log.close()
            if not os.path.exists(out):
                print("a game failed: see %s" % (out[:-5] + '.log'), flush=True)
                continue
            with open(out, encoding='utf-8') as f:
                game = json.load(f)
            game['job'] = key
            games.append(game)
            with open(os.path.join(folder, 'games.jsonl'), 'a', encoding='utf-8') as f:
                f.write(json.dumps(game) + '\n')
            with open(out[:-5] + '.pgn', 'w', encoding='utf-8') as f:
                f.write(pgn(game))
            print("%-36s hint %s  %-7s %-26s %3d plies, %d tries, hint %.1f s, %d s"
                  % (game['opening'] or '(start)', game['hintColor'], game['result'], game['reason'], game['plies'],
                     game['tries'], game['meanHintSeconds'], game['wallSeconds']), flush=True)
            if args.sprt:
                wins = tally(games)[0]
                llr, verdict = sprt(wins, len(games), *args.sprt)
                print("  SPRT: LLR %.2f after %d games%s" % (llr, len(games), ', ' + verdict if verdict else ''),
                      flush=True)
    minutes = (time.time() - started) / 60
    print("\n" + summary(games, settings['policy']) + ("; SPRT %s" % verdict if verdict else '')
          + "; %.0f min; games in %s" % (minutes, folder))
    if args.record:
        record(folder, settings, games, verdict, minutes)
        print("recorded in %s" % RESULTS)
    return games


def compare(folderA, folderB):
    """Paired comparison of two runs over the games they share (same opening, colour and repeat)."""
    a = {g['job']: g for g in readGames(folderA)}
    b = {g['job']: g for g in readGames(folderB)}
    shared = sorted(set(a) & set(b))
    onlyA = sum(1 for k in shared if a[k]['hintScore'] == 1.0 and b[k]['hintScore'] != 1.0)
    onlyB = sum(1 for k in shared if b[k]['hintScore'] == 1.0 and a[k]['hintScore'] != 1.0)
    print(summary([a[k] for k in shared], 'A ' + os.path.basename(folderA)))
    print(summary([b[k] for k in shared], 'B ' + os.path.basename(folderB)))
    print("%d paired games: only A won %d, only B won %d; McNemar p = %.3f" % (len(shared), onlyA, onlyB,
                                                                             mcnemar(onlyA, onlyB)))


async def calibrateEngine(command, threads, hint):
    """The engine's mean nodes per second over CALIBRATE_PLIES positions of a few book openings."""
    engine = stockfish.Engine(command, channel='calibrate', hint=hint, threads=threads)
    if not await engine.ready(60):
        raise SystemExit("could not start %s" % command)
    rates = []
    for line in chessAi.BOOK_LINES[::8][:4]:
        sans = line.split()
        for plies in CALIBRATE_PLIES:
            gs = GameState()
            for san in sans[:plies]:
                gs.makeMove(gs.findMoveBySan(san, gs.getValidMoves()))
            await engine.go([m.getCode() for m in gs.moveLog], CALIBRATE_SECONDS)
            if engine.lastNps:
                rates.append(engine.lastNps)
    engine.close()
    return round(sum(rates) / len(rates))


def calibrate(path, profiles, hintThreads):
    found = {}
    if os.path.exists(path):
        found = loadCalibration(path)
    found.setdefault('computer', {})
    found.setdefault('hint', {})
    for profile in profiles:
        found['computer'][profile] = asyncio.run(calibrateEngine(computerCommand(profile), 1, False))
        print("computer (%s): %d nodes/s" % (profile, found['computer'][profile]), flush=True)
    for threads in hintThreads:
        found['hint'][str(threads)] = asyncio.run(calibrateEngine([nativeExecutable()], threads, True))
        print("hint (%d threads): %d nodes/s" % (threads, found['hint'][str(threads)]), flush=True)
    found['machine'] = platform.processor() or platform.machine()
    found['cores'] = os.cpu_count()
    found['date'] = datetime.date.today().isoformat()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(found, f, indent=1)
    print("written to %s" % path)


def probability(text):
    p0, p1 = (float(x) for x in text.split(','))
    return p0, p1


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command')
    play = sub.add_parser('play', help='one game (used by the match itself)')
    play.add_argument('--policy', choices=POLICIES, required=True)
    play.add_argument('--opening', default='')
    play.add_argument('--color', choices=('w', 'b'), required=True)
    play.add_argument('--scale', type=float, default=0.25)
    play.add_argument('--profile', choices=PROFILES, default='desktop')
    play.add_argument('--budget', choices=('time', 'nodes'), default='time')
    play.add_argument('--hint-threads', type=int, default=stockfish.HINT_MAX_THREADS)
    play.add_argument('--calibration', default=CALIBRATION)
    play.add_argument('--hint-nps', type=int)
    play.add_argument('--out', required=True)
    cal = sub.add_parser('calibrate', help='measure nodes per second for --budget nodes (on an idle machine)')
    cal.add_argument('--profile', choices=PROFILES + ('both',), default='both')
    cal.add_argument('--hint-threads', type=int, nargs='+', default=[stockfish.HINT_MAX_THREADS])
    cal.add_argument('--calibration', default=CALIBRATION)
    cmp = sub.add_parser('compare', help='paired comparison of two run folders (McNemar on wins)')
    cmp.add_argument('a')
    cmp.add_argument('b')
    parser.add_argument('--policy', choices=POLICIES, default='adaptive-wdl')
    parser.add_argument('--profile', choices=PROFILES, default='browser')
    parser.add_argument('--budget', choices=('time', 'nodes'), default='time')
    parser.add_argument('--openings', default='book6', help='book6, startpos or file:PATH')
    parser.add_argument('--games', type=int, default=64)
    parser.add_argument('--parallel', type=int, default=1)
    parser.add_argument('--scale', type=float, default=0.25)
    parser.add_argument('--hint-threads', type=int, default=stockfish.HINT_MAX_THREADS)
    parser.add_argument('--calibration', default=CALIBRATION)
    parser.add_argument('--hint-nps', type=int, help="--budget nodes: the hint's nodes per second (e.g. the browser's)")
    parser.add_argument('--sprt', type=probability, help='P0,P1: stop once the test on wins decides (e.g. 0.5,0.65)')
    parser.add_argument('--resume', help='a run folder to continue')
    parser.add_argument('--record', action='store_true', help='add the result to tools/hint_match_results.md')
    parser.add_argument('--force', action='store_true', help='run time-budget matches even when cores are short')
    args = parser.parse_args()
    if args.command == 'play':
        calibration = loadCalibration(args.calibration) if args.budget == 'nodes' else None
        game = asyncio.run(playGame(args.policy, args.opening.split(), args.color, args.scale, args.profile,
                                    args.budget, args.hint_threads, calibration, args.hint_nps))
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(game, f)
        return
    if args.command == 'calibrate':
        calibrate(args.calibration, PROFILES if args.profile == 'both' else (args.profile,), args.hint_threads)
        return
    if args.command == 'compare':
        compare(args.a, args.b)
        return
    orchestrate(args)


if __name__ == '__main__':
    main()
