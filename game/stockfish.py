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
WORKER_URL = "stockfish/stockfish-19-lite-single.js"  # the browser build; its .wasm sits next to it
# the full browser build (Stockfish dev-20261028, NNUE SFNNv19; built from source, see tools/stockfish-wasm), loaded
# only for a hint or an analysis; its 137 MB .wasm comes in HINT_WORKER_PARTS parts, -part-0.wasm and on
HINT_WORKER_URL = "stockfish/stockfish-dev-20261028-single.js"
HINT_WORKER_PARTS = 6
# where the page can run threads (cross-origin isolated by vercel.json's COOP/COEP headers; not Safari, which doesn't
# know COEP credentialless), hints and the analysis use stockfish.js 19.0.1's multi-threaded full build instead, on
# hintThreads() threads: several times the computer's search (one thread of the lite build) in the same time. Its
# 99 MB .wasm is split by `npm run build` into HINT_THREADED_PARTS files of 25 MB, -part-0.wasm and on, which the
# worker joins (chessSfCachedWorker); its own loader asks for the whole .wasm
HINT_THREADED_URL = "stockfish/stockfish-19.js"
HINT_THREADED_PARTS = 4
HINT_MAX_THREADS = 8  # the hint engine's threads, in the browser and on desktop: the cores less SPARE_CORES, up to this
SPARE_CORES = 2  # left to the game and the computer's engine
HINT_HASH_MB = 128  # the hint engine's hash when it runs threads (the single-threaded build keeps HASH_MB)
# a phone or a device with little memory (chessSfSmallDevice) runs the threaded build smaller
SMALL_DEVICE_THREADS = 4
SMALL_DEVICE_HASH_MB = 32
ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines')  # desktop
LEVEL_ELO = [1320, 1600, 1900, 2300, None]  # the strength of each of chessAi.LEVELS; None: full strength
START_SECONDS = 30  # the engine has this long to answer 'uci' (the browser downloads 7 MB first)
HINT_START_SECONDS = 180  # the same for the hint engine, which downloads 137 MB first (99 MB threaded)
READY_WAIT = 10  # a search waits this long for an engine that is still starting, then uses chessAi (hints don't wait)
ANSWER_GRACE = 5  # seconds past the search time before a silent engine counts as broken
POLL_SECONDS = 0.02
HASH_MB = 16

JS_HELPERS = '''
    window.chessSf = window.chessSf || {};
    window.chessSfStart = function(key, url) {
        const sf = window.chessSf[key] = window.chessSf[key] || {worker: null, lines: [], failed: ''};
        if (sf.worker) return;
        try {
            sf.worker = new Worker(url);
            sf.worker.onmessage = function(e) {
                if (typeof e.data === 'string') sf.lines.push(...e.data.split('\\n').filter(Boolean));
            };
            sf.worker.onerror = function(e) {
                const message = String((e && e.message) || 'the engine did not load');
                // stockfish.js's threaded build reads one message without data as it starts (e.data.progressPort):
                // harmless, the engine answers as usual
                if (message.indexOf('progressPort') >= 0) {
                    if (e.preventDefault) e.preventDefault();
                    return;
                }
                sf.failed = message;
            };
        } catch (e) {
            sf.failed = String(e);
        }
    };
    window.chessSfStop = function(key) {
        const sf = window.chessSf[key];
        if (sf && sf.worker) {
            try { sf.worker.terminate(); } catch (e) {}
        }
        delete window.chessSf[key];
    };
    // the cores the page can run engine threads on: 0 unless it is cross-origin isolated (SharedArrayBuffer)
    window.chessSfThreadCores = function() {
        if (self.crossOriginIsolated !== true || typeof SharedArrayBuffer === 'undefined') return 0;
        return navigator.hardwareConcurrency || 0;
    };
    // a phone or tablet (a coarse pointer), or a device with 4 GB of memory or less (navigator.deviceMemory, Chrome)
    window.chessSfSmallDevice = function() {
        const coarse = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
        return coarse || (typeof navigator.deviceMemory === 'number' && navigator.deviceMemory <= 4);
    };
    window.chessSfSend = function(key, line) {
        const sf = window.chessSf[key];
        if (sf && sf.worker) sf.worker.postMessage(line);
    };
    window.chessSfTake = function(key) {
        const sf = window.chessSf[key];
        if (!sf) return '';
        const lines = sf.lines;
        sf.lines = [];
        return lines.join('\\n');
    };
    window.chessSfFailed = function(key) {
        const sf = window.chessSf[key];
        return sf ? sf.failed : '';
    };
    // the hint engine's .wasm parts, saved in Cache Storage for a signed-in player (prepareHintEngine): '' until asked,
    // then 'saving', 'saved', 'unsupported' or 'failed: ...'
    window.chessSfCacheName = 'chess-hint-engine-v1';
    window.chessSfSaveState = window.chessSfSaveState || '';
    window.chessSfSave = function(urls) {
        if (window.chessSfSaveState === 'saving' || window.chessSfSaveState === 'saved') return;
        if (!window.caches) { window.chessSfSaveState = 'unsupported'; return; }
        window.chessSfSaveState = 'saving';
        caches.open(window.chessSfCacheName).then(async function(cache) {
            for (const url of urls) {
                const key = new URL(url, location.href).href;
                if (await cache.match(key)) continue;
                const response = await fetch(key);
                if (!response.ok) throw new Error('HTTP ' + response.status + ' for ' + key);
                await cache.put(key, response);
            }
            window.chessSfSaveState = 'saved';
        }).catch(function(e) { window.chessSfSaveState = 'failed: ' + e; });
    };
    // a worker running the engine at url whose .wasm files come from Cache Storage when they are saved there: it
    // stands in for the XMLHttpRequest (the dev build's loader) and the fetch (stockfish.js 19's threaded loader) the
    // loader asks for them with, then loads the engine; the hash tells the loader where its .wasm is, as the worker's
    // own address is a blob. parts: the files the build split the .wasm into (its loader asks for the whole .wasm),
    // joined here, or none. The engine's threads start from this same blob and get the compiled engine from it.
    window.chessSfCachedWorker = function(url, parts) {
        const engine = new URL(url, location.href).href;
        const wasm = engine.replace(/\\.js$/, '.wasm');
        const source = [
            'const CACHE = ' + JSON.stringify(window.chessSfCacheName) + ';',
            'const ENGINE = ' + JSON.stringify(engine) + ';',
            'const WASM = ' + JSON.stringify(wasm) + ';',
            'const PARTS = ' + JSON.stringify((parts || []).map(function(p) { return new URL(p, location.href).href; })) + ';',
            'const networkFetch = self.fetch.bind(self);',
            'function fromCache(url) {',
            '    if (!self.caches) return Promise.resolve(null);',
            '    return caches.open(CACHE).then(function(c) { return c.match(url); }).catch(function() { return null; });',
            '}',
            'function load(url) {',
            '    return fromCache(url).then(function(r) { return r || networkFetch(url); });',
            '}',
            'function loadFile(url) {',
            '    if (url !== WASM || !PARTS.length) return load(url);',
            '    return Promise.all(PARTS.map(function(part) {',
            '        return load(part).then(function(r) {',
            '            if (!r.ok) throw new Error("HTTP " + r.status + " for " + part);',
            '            return r.blob();',
            '        });',
            '    })).then(function(blobs) {',
            '        return new Response(new Blob(blobs, {type: "application/wasm"}),',
            '                            {status: 200, headers: {"Content-Type": "application/wasm"}});',
            '    });',
            '}',
            'self.fetch = function(input, init) {',
            '    const url = new URL(typeof input === "string" ? input : input.url, ENGINE).href;',
            '    return /\\\\.wasm$/.test(url) ? loadFile(url) : networkFetch(input, init);',
            '};',
            'function CachedRequest() { this.status = 0; this.response = null; }',
            'CachedRequest.prototype.open = function(method, url) { this.url = new URL(url, ENGINE).href; };',
            'CachedRequest.prototype.setRequestHeader = function() {};',
            'CachedRequest.prototype.send = function() {',
            '    const request = this;',
            '    loadFile(request.url).then(function(r) {',
            '        request.status = r.status;',
            '        return r.blob();',
            '    }).then(function(blob) {',
            '        request.response = blob;',
            '        if (request.onprogress) request.onprogress({loaded: blob.size, total: blob.size, lengthComputable: true});',
            '        if (request.onload) request.onload();',
            '    }, function(e) { if (request.onerror) request.onerror(e); });',
            '};',
            'self.XMLHttpRequest = CachedRequest;',
            // a .wasm that doesn't download or compile rejects a promise nothing waits for: thrown again here, it
            // reaches the page's onerror, so the engine counts as failed at once (the threads report their own)
            'if (self.name !== "em-pthread") self.addEventListener("unhandledrejection", function(e) {',
            '    const reason = e.reason;',
            '    setTimeout(function() { throw reason instanceof Error ? reason : new Error(String(reason || "the engine did not load")); });',
            '});',
            'importScripts(ENGINE);',
        ].join('\\n');
        const worker = URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
        return worker + '#' + encodeURIComponent(wasm);
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
    def __init__(self, command=None, worker_url=WORKER_URL, channel='main', start_seconds=START_SECONDS, saved=False,
                 hint=False):
        self.command = command  # desktop: the command to run (a list); None: findExecutable()
        self.worker_url = worker_url
        self.channel = channel
        self.start_seconds = start_seconds
        self.saved = saved  # browser: its .wasm parts may be saved on the device (the hint engine, prepareHintEngine)
        # the hint engine runs on more threads, with more hash, than the computer's: in the browser the threaded build
        # (HINT_THREADED_URL) where the page allows it, on desktop the same executable on hintThreads() threads
        self.hint = hint
        self.threads = 1  # the threads it runs on (set as it starts)
        self.threadedFailed = False  # browser: the threaded build didn't start, so the single-threaded one runs
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

    async def go(self, moves, seconds, elo=None, search_moves=None, start=None):
        """Searches the position after moves (Move.getCode codes from the start position, or from the FEN start)
        for seconds, at most elo strong (None: full strength). Returns (best move code or None, score in pawns for
        the side to move, or None), or None when the engine isn't ready or fails."""
        if self.state != 'ready':
            return None
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                return await self._search(moves, seconds, elo, search_moves, start)
            except asyncio.CancelledError:
                if self._searching:
                    self._send('stop')  # the next search first reads this one's bestmove (see _search)
                raise
            except Exception as e:
                print("Stockfish: stopped working -", e)
                if self._threaded():  # the next hint or analysis starts the single-threaded build
                    self._useSingleThreaded()
                    self.state = 'off'
                    return None
                self.state = 'failed'
                self.close()
                return None

    async def _search(self, moves, seconds, elo, search_moves=None, start=None):
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
        self._send(('position fen ' + start if start else 'position startpos')
                   + (' moves ' + ' '.join(moves) if moves else ''))
        go = 'go movetime %d' % max(1, round(seconds * 1000))
        if search_moves:  # last: Stockfish reads every word after searchmoves as a move, movetime too
            go += ' searchmoves ' + ' '.join(search_moves)
        self._send(go)
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

    def _threaded(self):
        """Browser: whether this engine runs the threaded build (HINT_THREADED_URL)."""
        return WASM and self.hint and self.threads > 1 and not self.threadedFailed

    def _useSingleThreaded(self):
        """Browser: the threaded build failed, so from now on this engine runs the single-threaded one. That build is
        also saved on the device when the threaded one was (prepareHintEngine), so the next visit finds it there."""
        self.threadedFailed = True
        self.close()
        self.threads, self._searching, self._elo = 1, False, 'unset'  # a new worker: nothing from the old one
        if self.saved and saveState():
            try:
                js.eval("window.chessSfSaveState = ''")
                js.eval("window.chessSfSave(%s)" % json.dumps(singleThreadedParts()))
            except Exception as e:
                print("Stockfish: could not save the hint engine -", e)

    async def _handshake(self):
        try:
            while self.saved and saveState() == 'saving':  # its files are on their way into the cache: load them from there
                await asyncio.sleep(0.1)
            self._open()
            self._send('uci')
            for line in await self._waitFor('uciok', self.start_seconds):
                if line.startswith('id name '):
                    self.name = line[len('id name '):]
            if not WASM:
                self.threads = hintThreads(os.cpu_count()) if self.hint else max(1, min(4, (os.cpu_count() or 2) // 2))
            self._send('setoption name Hash value %d' % (hintHash() if self.hint and self.threads > 1 else HASH_MB))
            if not WASM or self.threads > 1:
                self._send('setoption name Threads value %d' % self.threads)
            self._send('isready')
            await self._waitFor('readyok', self.start_seconds)
            self.state = 'ready'
            print("Stockfish: ready -", self.name, "(%d thread%s)" % (self.threads, '' if self.threads == 1 else 's'))
        except Exception as e:
            if self._threaded():  # the threaded build: the single-threaded one
                print("Stockfish: the threaded hint engine did not start, it runs on one thread -", e)
                self._useSingleThreaded()
                await self._handshake()
                return
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
            url, parts, self.threads = self.worker_url, [], 1
            if self.hint and not self.threadedFailed and browserThreads() > 1:
                url, parts, self.threads = HINT_THREADED_URL, threadedParts(), browserThreads()
            if self.saved:
                url = str(js.eval("window.chessSfCachedWorker(%s, %s)" % (json.dumps(url), json.dumps(parts))))
            js.eval("window.chessSfStart(%s, %s)" % (json.dumps(self.channel), json.dumps(url)))
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
            js.eval("window.chessSfSend(%s, %s)" % (json.dumps(self.channel), json.dumps(line)))
        elif self._proc is not None:
            try:
                self._proc.stdin.write(line + '\n')
                self._proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise EngineError("the engine closed (%s)" % e)

    def _take(self):
        if WASM:
            failed = str(js.eval("window.chessSfFailed(%s)" % json.dumps(self.channel)) or '')
            if failed:
                raise EngineError(failed)
            raw = str(js.eval("window.chessSfTake(%s)" % json.dumps(self.channel)) or '')
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
        if WASM and js is not None:  # the worker stops (a later start makes a new one)
            try:
                js.eval("window.chessSfStop && window.chessSfStop(%s)" % json.dumps(self.channel))
            except Exception:
                pass
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
hintEngine = Engine(worker_url=HINT_WORKER_URL, channel='hint', start_seconds=HINT_START_SECONDS, saved=True,
                    hint=True)
atexit.register(lambda: engine.close())  # desktop: the engine quits with the game
atexit.register(lambda: hintEngine.close())


def moveCodes(gs):
    return [move.getCode() for move in gs.moveLog]


def nonRepetitionMoves(gs, validMoves, history):
    """Moves that do not immediately claim a third occurrence, unless every move does."""
    if not history:
        return validMoves
    candidates = []
    for move in validMoves:
        gs.makeMove(move)
        repeated = history.count(gs.getPositionKey()) >= 2
        gs.undoMove()
        if not repeated:
            candidates.append(move)
    return candidates or validMoves


hintMoves = nonRepetitionMoves

# a move that repeats the position a third time ends the game in a draw; the computer and the hints play on instead,
# unless every other move scores worse than this (pawns, for the side to move): then the draw is the better result
REPETITION_MARGIN = 0.5


def takesTheDraw(score):
    """Whether claiming a repetition beats playing on, when the best move that doesn't repeat scores score."""
    return score is not None and score < -REPETITION_MARGIN


def repeatingMoves(validMoves, candidates):
    return [move for move in validMoves if move not in candidates]


async def findBestMove(gs, validMoves, level=None, history=()):
    """The computer's move at the difficulty chessAi.LEVELS[level] (chessAi.LEVEL when None): Stockfish held to
    that level's strength (LEVEL_ELO) for the level's time, or chessAi's own search without it."""
    if not validMoves:
        return None
    level = chessAi.LEVEL if level is None else level
    candidates = nonRepetitionMoves(gs, validMoves, history)
    repeating = repeatingMoves(validMoves, candidates)
    name, seconds = chessAi.LEVELS[level][:2]
    if len(validMoves) > 1 and not gs.playerWantsToPlayAsBlack and await engine.ready(READY_WAIT):
        found = await engine.go(moveCodes(gs), seconds, LEVEL_ELO[level], start=gs.startFen,
                                search_moves=[move.getCode() for move in candidates])
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move in candidates:
            if repeating and takesTheDraw(found[1]):
                print("AI (%s, Stockfish): %s repeats, as playing on scores %s" % (name, repeating[0], found[1]))
                return repeating[0]
            print("AI (%s, Stockfish): %s score %s" % (name, move, found[1]))
            return move
    move = await chessAi.findBestMove(gs, validMoves, level, history)
    if move in candidates or not repeating:
        return move
    # chessAi chose to repeat: it plays on if a move that doesn't repeat is about as good
    score, other, _ = await chessAi.searchPosition(gs, candidates, seconds, history=history)
    return move if takesTheDraw(score) or other is None else other


async def searchPosition(gs, validMoves, seconds, history=()):
    """Like chessAi.searchPosition: (score for the side to move in pawns, best move, depth), searched by Stockfish
    at full strength when it is there (depth is then 0: Stockfish keeps it to itself)."""
    if validMoves and not gs.playerWantsToPlayAsBlack and await engine.ready(READY_WAIT):
        found = await engine.go(moveCodes(gs), seconds, start=gs.startFen)
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move is not None and found[1] is not None:
            return found[1], move, 0
    return await chessAi.searchPosition(gs, validMoves, seconds, history=history)


async def searchHintPosition(gs, validMoves, seconds, history=()):
    """Searches a hint with the full browser build, without changing the gameplay engine. A hint doesn't wait for
    that engine while it loads (it starts on the first hint, or at sign-in: prepareHintEngine): searchPosition
    answers meanwhile."""
    if validMoves and await hintEngine.ready(0):
        candidates = nonRepetitionMoves(gs, validMoves, history)
        found = await hintEngine.go(moveCodes(gs), seconds, start=gs.startFen,
                                    search_moves=[move.getCode() for move in candidates])
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move is not None and found[1] is not None:
            repeating = repeatingMoves(validMoves, candidates)
            if repeating and takesTheDraw(found[1]):
                return 0.0, repeating[0], 0  # the draw is better than any move that plays on
            return found[1], move, 0
    return await searchPosition(gs, validMoves, seconds, history=history)


async def analyzePosition(gs, validMoves, seconds, history=()):
    """Like searchPosition, for the analysis after the game: searched by the hint engine (the full build), which it
    waits for while it loads, so one game's scores all come from the same engine."""
    if validMoves and not gs.playerWantsToPlayAsBlack and await hintEngine.ready(HINT_START_SECONDS):
        found = await hintEngine.go(moveCodes(gs), seconds, start=gs.startFen)
        move = gs.findMoveByCode(found[0], validMoves) if found and found[0] else None
        if move is not None and found[1] is not None:
            return found[1], move, 0
    return await searchPosition(gs, validMoves, seconds, history=history)


async def evaluate(gs, seconds):
    """The position's score for the side to move in pawns from a short Stockfish search, or None when Stockfish
    isn't ready or is busy (the caller then judges for itself)."""
    if engine.state != 'ready' or engine.busy or gs.playerWantsToPlayAsBlack:
        return None
    found = await engine.go(moveCodes(gs), seconds, start=gs.startFen)
    return found[1] if found else None


def hintThreads(cores):
    """The hint engine's threads on a device with this many cores (None: unknown): all but SPARE_CORES, up to
    HINT_MAX_THREADS, at least one."""
    return max(1, min(HINT_MAX_THREADS, (cores or 1) - SPARE_CORES))


def smallDevice():
    """Browser: a phone or tablet, or a device with 4 GB of memory or less (chessSfSmallDevice); False on desktop."""
    if not WASM or js is None:
        return False
    try:
        js.eval(JS_HELPERS)
        return bool(js.eval("window.chessSfSmallDevice()"))
    except Exception:
        return False


def browserThreads():
    """Browser: the threads the hint engine runs on, hintThreads() of the cores when the page can run threads
    (cross-origin isolated), at most SMALL_DEVICE_THREADS on a small device, else 1; 1 on desktop."""
    if not WASM or js is None:
        return 1
    try:
        js.eval(JS_HELPERS)
        cores = int(js.eval("window.chessSfThreadCores()") or 0)
    except Exception:
        return 1
    threads = hintThreads(cores) if cores else 1
    return min(threads, SMALL_DEVICE_THREADS) if threads > 1 and smallDevice() else threads


def hintHash():
    """The hint engine's hash in MB when it runs threads: HINT_HASH_MB, SMALL_DEVICE_HASH_MB on a small device."""
    return SMALL_DEVICE_HASH_MB if smallDevice() else HINT_HASH_MB


def threadedParts():
    base = HINT_THREADED_URL[:-len('.js')]
    return ['%s-part-%d.wasm' % (base, i) for i in range(HINT_THREADED_PARTS)]


def singleThreadedParts():
    base = HINT_WORKER_URL[:-len('.js')]
    return ['%s-part-%d.wasm' % (base, i) for i in range(HINT_WORKER_PARTS)]


def hintEngineParts():
    """The files of the hint engine this page runs: the threaded build's where it can run threads, else the
    single-threaded build's."""
    if browserThreads() > 1 and not hintEngine.threadedFailed:
        return threadedParts()
    return singleThreadedParts()


def saveState():
    """Browser: how saving the hint engine on the device goes (window.chessSfSaveState); '' elsewhere."""
    if not WASM or js is None:
        return ''
    try:
        return str(js.eval("window.chessSfSaveState || ''") or '')
    except Exception:
        return ''


def prepareHintEngine():
    """Called once a player is signed in. In the browser the hint engine (137 MB, 99 MB threaded) is saved on the
    device the first time (Cache Storage; found there on later visits), and the engine starts from it, so hints and
    the analysis don't wait for the download; on desktop the engine just starts."""
    if not ENABLED:
        return
    if WASM and js is not None:
        try:
            js.eval(JS_HELPERS)
            js.eval("window.chessSfSave(%s)" % json.dumps(hintEngineParts()))
        except Exception as e:
            print("Stockfish: could not save the hint engine -", e)
    hintEngine.start()
