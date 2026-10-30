# Stockfish plays the computer's moves, finds the hints and analyzes finished games. In the browser it is
# stockfish.js (copied next to the page, under stockfish/, by `npm run build`) running in a Web Worker; on desktop
# it is a native stockfish executable (STOCKFISH_PATH, on PATH, or in the repository's engines/ folder). Both speak
# UCI: this module sends them commands and polls their answers, so the game loop never blocks. Without an engine,
# or when it fails, findBestMove and searchPosition fall back to chessAi's own search.

import os
import sys
import glob
import json
import time
import queue
import shutil
import atexit
import asyncio
import threading
import subprocess

import chessAi

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

# the tests turn Stockfish off (CHESS_NO_STOCKFISH=1), so the computer plays the same moves on every machine
ENABLED = os.environ.get('CHESS_NO_STOCKFISH') != '1'
WORKER_URL = "stockfish/stockfish-17.1-lite-single-03e3232.js"  # the browser build; its .wasm sits next to it
ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines')  # desktop
LEVEL_ELO = [1320, 1600, 1900, 2300, None]  # the strength of each of chessAi.LEVELS; None: full strength
START_SECONDS = 30  # the engine has this long to answer 'uci' (the browser downloads 7 MB first)
READY_WAIT = 10  # a search waits this long for an engine that is still starting, then uses chessAi
ANSWER_GRACE = 5  # seconds past the search time before a silent engine counts as broken
POLL_SECONDS = 0.02
HASH_MB = 16

JS_HELPERS = '''
    window.chessSf = window.chessSf || {worker: null, lines: [], failed: ''};
    window.chessSfStart = function(url) {
        const sf = window.chessSf;
        if (sf.worker) return;
        try {
            sf.worker = new Worker(url);
            sf.worker.onmessage = function(e) {
                if (typeof e.data === 'string') sf.lines.push(...e.data.split('\\n').filter(Boolean));
            };
            sf.worker.onerror = function(e) { sf.failed = String((e && e.message) || 'the engine did not load'); };
        } catch (e) {
            sf.failed = String(e);
        }
    };
    window.chessSfSend = function(line) { if (window.chessSf.worker) window.chessSf.worker.postMessage(line); };
    window.chessSfTake = function() {
        const lines = window.chessSf.lines;
        window.chessSf.lines = [];
        return lines.join('\\n');
    };
'''


class EngineError(Exception):
    pass


# desktop: the stockfish executable to run, or None
def findExecutable():
    path = os.environ.get('STOCKFISH_PATH')
    if path:
        return path if os.path.isfile(path) else None
    found = shutil.which('stockfish')
    if found:
        return found
    for pattern in ('stockfish*', os.path.join('*', 'stockfish*')):
        for path in sorted(glob.glob(os.path.join(ENGINE_DIR, pattern))):
            if os.path.isfile(path) and (path.lower().endswith('.exe') or os.access(path, os.X_OK)):
                return path
    return None


# (kind, value) of a UCI 'info' line's score: ('cp', centipawns) or ('mate', moves; negative: getting mated);
# None for a line without one, or a bound from an unfinished search
def parseScore(line):
    parts = line.split()
    if 'score' not in parts or 'lowerbound' in parts or 'upperbound' in parts:
        return None
    if 'multipv' in parts and parts[parts.index('multipv') + 1] != '1':
        return None
    i = parts.index('score')
    try:
        return parts[i + 1], int(parts[i + 2])
    except (IndexError, ValueError):
        return None


# a UCI score in pawns for the side to move, on chessAi's scale (a forced mate is near +-chessAi.CHECKMATE)
def scoreInPawns(score):
    kind, value = score
    if kind == 'mate':
        if value == 0:
            return -chessAi.CHECKMATE  # mated already
        return (chessAi.CHECKMATE - abs(value)) * (1 if value > 0 else -1)
    return value / 100


class Engine:
    def __init__(self, command=None):
        self.command = command  # desktop: the command to run (a list); None: findExecutable()
        self.state = 'off'  # 'off' -> 'starting' -> 'ready', or 'failed'
        self.name = None  # the engine's own name, from 'id name'
        self._proc = None
        self._lines = queue.Queue()  # desktop: lines read by the reader thread
        self._lock = None  # one search at a time
        self._elo = 'unset'  # the strength limit set last
        self._searching = False  # a 'go' whose bestmove hasn't been read yet (its search was cancelled)

    @property
    def busy(self):
        return self._lock is not None and self._lock.locked()

    def start(self):
        """Starts the engine in the background (call it from the running game loop)."""
        if self.state != 'off' or not ENABLED:
            return
        self.state = 'starting'
        asyncio.ensure_future(self._handshake())

    async def ready(self, timeout=0):
        """Whether the engine answers; waits up to timeout seconds for one that is still starting."""
        if not ENABLED:
            return False
        self.start()
        deadline = time.time() + timeout
        while self.state == 'starting' and time.time() < deadline:
            await asyncio.sleep(POLL_SECONDS)
        return self.state == 'ready'

    async def go(self, moves, seconds, elo=None):
        """Searches the position after moves (Move.getCode codes from the start position) for seconds, at most
        elo strong (None: full strength). Returns (best move code or None, score in pawns for the side to move,
        or None), or None when the engine isn't ready or fails."""
        if self.state != 'ready':
            return None
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                return await self._search(moves, seconds, elo)
            except asyncio.CancelledError:
                if self._searching:
                    self._send('stop')  # the next search first reads this one's bestmove (see _search)
                raise
            except Exception as e:
                print("Stockfish: stopped working -", e)
                self.state = 'failed'
                self.close()
                return None

    async def _search(self, moves, seconds, elo):
        # a search cancelled earlier may still be answering: its bestmove comes first (an engine answers isready
        # even while it searches, so readyok alone doesn't mean it is done)
        if self._searching:
            self._send('stop')
            await self._waitFor('bestmove', ANSWER_GRACE)
            self._searching = False
        self._send('isready')
        await self._waitFor('readyok', ANSWER_GRACE)
        if elo != self._elo:
            if elo is None:
                self._send('setoption name UCI_LimitStrength value false')
            else:
                self._send('setoption name UCI_LimitStrength value true')
                self._send('setoption name UCI_Elo value %d' % elo)
            self._elo = elo
        self._send('position startpos' + (' moves ' + ' '.join(moves) if moves else ''))
        self._send('go movetime %d' % max(1, round(seconds * 1000)))
        self._searching = True
        score = None
        deadline = time.time() + seconds + ANSWER_GRACE
        while True:
            for line in self._take():
                if line.startswith('info'):
                    score = parseScore(line) or score
                elif line.startswith('bestmove'):
                    self._searching = False
                    parts = line.split()
                    best = parts[1] if len(parts) > 1 and parts[1] != '(none)' else None
                    return best, (scoreInPawns(score) if score else None)
            if time.time() > deadline:
                raise EngineError("no answer to 'go'")
            await asyncio.sleep(POLL_SECONDS)

    async def _handshake(self):
        try:
            self._open()
            self._send('uci')
            for line in await self._waitFor('uciok', START_SECONDS):
                if line.startswith('id name '):
                    self.name = line[len('id name '):]
            self._send('setoption name Hash value %d' % HASH_MB)
            if not WASM:
                self._send('setoption name Threads value %d' % max(1, min(4, (os.cpu_count() or 2) // 2)))
            self._send('isready')
            await self._waitFor('readyok', START_SECONDS)
            self.state = 'ready'
            print("Stockfish: ready -", self.name)
        except Exception as e:
            print("Stockfish: not available, the game's own AI plays -", e)
            self.state = 'failed'
            self.close()

    # the lines up to and including the first that starts with prefix
    async def _waitFor(self, prefix, seconds):
        seen = []
        deadline = time.time() + seconds
        while True:
            for line in self._take():
                seen.append(line)
                if line.startswith(prefix):
                    return seen
            if time.time() > deadline:
                raise EngineError("no '%s' from the engine" % prefix)
            await asyncio.sleep(POLL_SECONDS)

    # --- the two ways to reach an engine

    def _open(self):
        if WASM:
            if js is None:
                raise EngineError("no JavaScript bridge")
            js.eval(JS_HELPERS)
            js.eval("window.chessSfStart(%s)" % json.dumps(WORKER_URL))
            return
        command = self.command
        if command is None:
            path = findExecutable()
            if path is None:
                raise EngineError("no stockfish executable found (set STOCKFISH_PATH, or put one in engines/)")
            command = [path]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # Windows: no console window
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1, creationflags=flags)
        threading.Thread(target=self._readLoop, args=(self._proc,), daemon=True).start()

    def _readLoop(self, proc):
        try:
            for line in proc.stdout:
                self._lines.put(line.strip())
        except Exception:
            pass

    def _send(self, line):
        if WASM:
            js.eval("window.chessSfSend(%s)" % json.dumps(line))
        elif self._proc is not None:
            try:
                self._proc.stdin.write(line + '\n')
                self._proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise EngineError("the engine closed (%s)" % e)

    def _take(self):
        if WASM:
            failed = str(js.eval("window.chessSf.failed") or '')
            if failed:
                raise EngineError(failed)
            raw = str(js.eval("window.chessSfTake()") or '')
            return [line.strip() for line in raw.split('\n') if line.strip()]
        lines = []
        while True:
            try:
                lines.append(self._lines.get_nowait())
            except queue.Empty:
                break
        if not lines and self._proc is not None and self._proc.poll() is not None:
            raise EngineError("the engine exited")
        return lines

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.write('quit\n')
                self._proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self._proc.kill()
                self._proc.wait(2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._proc = None


engine = Engine()
atexit.register(lambda: engine.close())  # desktop: the engine quits with the game


def moveCodes(gs):
    return [move.getCode() for move in gs.moveLog]


async def findBestMove(gs, validMoves, level=None, history=()):
    """The computer's move at the difficulty chessAi.LEVELS[level] (chessAi.LEVEL when None): Stockfish held to
    that level's strength (LEVEL_ELO) for the level's time, or chessAi's own search without it."""
    if not validMoves:
        return None
    level = chessAi.LEVEL if level is None else level
    if len(validMoves) > 1 and not gs.playerWantsToPlayAsBlack and await engine.ready(READY_WAIT):
        name, seconds = chessAi.LEVELS[level][:2]
        found = await engine.go(moveCodes(gs), seconds, LEVEL_ELO[level])
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move is not None:
            print("AI (%s, Stockfish): %s score %s" % (name, move, found[1]))
            return move
    return await chessAi.findBestMove(gs, validMoves, level, history)


async def searchPosition(gs, validMoves, seconds, history=()):
    """Like chessAi.searchPosition: (score for the side to move in pawns, best move, depth), searched by Stockfish
    at full strength when it is there (depth is then 0: Stockfish keeps it to itself)."""
    if validMoves and not gs.playerWantsToPlayAsBlack and await engine.ready(READY_WAIT):
        found = await engine.go(moveCodes(gs), seconds)
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move is not None and found[1] is not None:
            return found[1], move, 0
    return await chessAi.searchPosition(gs, validMoves, seconds, history=history)


async def evaluate(gs, seconds):
    """The position's score for the side to move in pawns from a short Stockfish search, or None when Stockfish
    isn't ready or is busy (the caller then judges for itself)."""
    if engine.state != 'ready' or engine.busy or gs.playerWantsToPlayAsBlack:
        return None
    found = await engine.go(moveCodes(gs), seconds)
    return found[1] if found else None
