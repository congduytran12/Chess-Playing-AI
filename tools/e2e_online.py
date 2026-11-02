"""
End-to-end test of Online Multiplayer: two game clients (two processes, two test accounts) play ten games in a room,
through the game's real network code and account client, against stand-ins that run on this computer only:

  * a relay that speaks the part of ntfy.sh the game uses (the game is pointed at it with CHESS_NTFY_URL), and
  * the real api/account.py on an in-memory imitation of Supabase (the game is pointed at it with CHESS_API_URL).

Nothing is sent to ntfy.sh or to the deployed site, and no real account is made. The games are scripted: mates,
resignations, a draw by agreement, an undo, a long game of random moves, a game with a hint (not rated), rematches
that swap the colors, and a time-out. The report compares what the two clients saw and what the rating server did.

    python tools/e2e_online.py [--games N]       (needs pygame, flask and requests; takes a few minutes)
"""
import asyncio
import importlib.util
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, 'game')

# ---------------------------------------------------------------------------------------------- the scenarios
# moves: the game's moves from the start; random: that many plies of random legal moves; end: 'mate' (the rules end
# it), ('resign', color), ('draw', the color that offers) or 'flag' (Black never moves); hint: the color that asks for a
# hint; undo: (the color that asks, the moves played after the undo); via: how the game is started, 'rematch' (the
# colors swap), 'new' (the same colors) or 'room' (both leave, the host makes a room with a 5 second clock)
SCENARIOS = [
    {'name': "scholar's mate", 'moves': 'e2e4 e7e5 d1h5 b8c6 f1c4 g8f6 h5f7', 'end': 'mate', 'result': 'White wins by checkmate'},
    {'name': "fool's mate", 'moves': 'f2f3 e7e5 g2g4 d8h4', 'end': 'mate', 'result': 'Black wins by checkmate', 'via': 'rematch'},
    {'name': "white resigns", 'moves': 'e2e4 e7e5 g1f3 b8c6 f1b5 a7a6', 'end': ('resign', 'w'),
     'result': 'Black wins by resignation', 'via': 'new'},
    {'name': "black resigns", 'moves': 'd2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1g5 f8e7', 'end': ('resign', 'b'),
     'result': 'White wins by resignation', 'via': 'rematch'},
    {'name': "draw by agreement", 'moves': 'e2e4 e7e5 g1f3 g8f6 f3e5 f6e4 d1e2 d8e7', 'end': ('draw', 'w'),
     'result': 'Draw by agreement', 'via': 'new'},
    {'name': "undo, then white resigns", 'moves': 'e2e4 e7e5 g1f3 b8c6', 'undo': ('b', 'd7d6 d2d4'), 'end': ('resign', 'w'),
     'result': 'Black wins by resignation', 'via': 'rematch'},
    {'name': "30 random plies, black resigns", 'random': 30, 'end': ('resign', 'b'), 'result': None, 'via': 'new'},
    {'name': "a hint is used (not rated)", 'moves': 'e2e4 e7e5 g1f3 b8c6 d2d4 e5d4', 'hint': 'w', 'end': ('resign', 'b'),
     'result': 'White wins by resignation', 'via': 'rematch'},
    {'name': "mate after a rematch", 'moves': 'e2e4 e7e5 d1h5 b8c6 f1c4 g8f6 h5f7', 'end': 'mate',
     'result': 'White wins by checkmate', 'via': 'new'},
    {'name': "black runs out of time", 'moves': 'e2e4', 'end': 'flag', 'result': 'White wins on time', 'via': 'room'},
]
ACCOUNTS = {'host': ('tester_a', 'tester_a@example.com'), 'guest': ('tester_b', 'tester_b@example.com')}
PASSWORD = 'test-password-1'


MOUSE = [(0, 0)]  # where the pointer is, in a player's process


def freePort():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------------------------------------ the relay
class Relay:
    def __init__(self):
        self.topics = {}
        self.cond = threading.Condition()
        self.counter = 0

    def add(self, topic, text):
        with self.cond:
            self.counter += 1
            message = {'id': 'm%08d' % self.counter, 'time': int(time.time()), 'event': 'message', 'topic': topic,
                       'message': text}
            self.topics.setdefault(topic, []).append(message)
            self.cond.notify_all()
            return message


RELAY = Relay()


class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        topic = urlsplit(self.path).path.strip('/')
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode('utf-8', 'replace')
        self.send(RELAY.add(topic, body))

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == '/stats':
            with RELAY.cond:
                return self.send({topic: len(messages) for topic, messages in RELAY.topics.items()})
        topic = parts.path.strip('/').split('/')[0]
        since = parse_qs(parts.query).get('since', ['all'])[0]
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.end_headers()
        try:
            self.wfile.write(json.dumps({'event': 'open', 'topic': topic}).encode() + b'\n')
            self.wfile.flush()
            with RELAY.cond:
                messages = RELAY.topics.setdefault(topic, [])
                index = 0
                if since.endswith('m') and since[:-1].isdigit():
                    cutoff = time.time() - int(since[:-1]) * 60
                    index = next((i for i, m in enumerate(messages) if m['time'] >= cutoff), len(messages))
                elif since != 'all':
                    index = next((i + 1 for i, m in enumerate(messages) if m['id'] == since), 0)
            while True:
                with RELAY.cond:
                    messages = RELAY.topics[topic]
                    if len(messages) <= index:
                        RELAY.cond.wait(15)
                    fresh = messages[index:]
                    index = len(messages)
                if not fresh:
                    self.wfile.write(json.dumps({'event': 'keepalive', 'topic': topic}).encode() + b'\n')
                for message in fresh:
                    self.wfile.write(json.dumps(message).encode() + b'\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def serveRelay(port):
    server = ThreadingHTTPServer(('127.0.0.1', port), RelayHandler)
    server.daemon_threads = True
    server.serve_forever()


# --------------------------------------------------------------------- the account server on a fake Supabase
class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body, self.text = status, body, json.dumps(body)

    def json(self):
        return self.body


class Backend:
    """Just the parts of Supabase (GoTrue and PostgREST) that api/account.py uses, in memory."""

    def __init__(self):
        self.lock = threading.Lock()
        self.users, self.byEmail, self.profiles = {}, {}, {}
        self.games, self.reports, self.applied = [], [], []
        self.tokens = {}

    def session(self, uid):
        access, refresh = 'access-%s-%d' % (uid, len(self.tokens)), 'refresh-' + uid
        self.tokens[access] = uid
        self.tokens[refresh] = uid
        return {'access_token': access, 'refresh_token': refresh, 'user': {'id': uid}}

    def supabase(self, method, path, token=None, **kwargs):
        with self.lock:
            body = kwargs.get('json') or {}
            if path == '/auth/v1/signup':
                email, name = body['email'], (body.get('data') or {}).get('username')
                if email in self.byEmail:
                    return FakeResponse(422, {'msg': 'User already registered'})
                uid = 'u%d' % (len(self.users) + 1)
                self.users[uid] = {'email': email, 'password': body['password']}
                self.byEmail[email] = uid
                self.profiles[uid] = {'id': uid, 'username': name, 'rating': 1200, 'rated_games': 0}
                return FakeResponse(200, self.session(uid))
            if path.startswith('/auth/v1/token?grant_type=password'):
                uid = self.byEmail.get(body.get('email'))
                if uid is None or self.users[uid]['password'] != body.get('password'):
                    return FakeResponse(400, {'msg': 'Invalid login credentials'})
                return FakeResponse(200, self.session(uid))
            if path.startswith('/auth/v1/token?grant_type=refresh_token'):
                uid = self.tokens.get(body.get('refresh_token'))
                return FakeResponse(200, self.session(uid)) if uid else FakeResponse(400, {'msg': 'bad refresh token'})
            if path == '/auth/v1/user':
                uid = self.tokens.get(token)
                return FakeResponse(200, {'id': uid}) if uid else FakeResponse(401, {'msg': 'bad token'})
            if path.startswith('/auth/v1/admin/users/'):
                return FakeResponse(200, {'email': self.users[path.rsplit('/', 1)[1]]['email']})
        raise AssertionError('the fake Supabase has no ' + path)

    def rest(self, method, path, params=None, json=None, headers=None):
        params = params or {}
        with self.lock:
            if path == 'profiles' and method == 'GET':
                rows = list(self.profiles.values())
                if 'id' in params:
                    rows = [r for r in rows if r['id'] == params['id'][3:]]
                if 'username' in params:
                    wanted = params['username'][len('ilike.'):].replace('\\_', '_').lower()
                    rows = [r for r in rows if r['username'].lower() == wanted]
                if 'rated_games' in params:
                    rows = sorted([r for r in rows if r['rated_games'] > 0], key=lambda r: -r['rating'])
                return [dict(r) for r in rows]
            if path == 'games':
                if method == 'POST':
                    row = dict(json, id=len(self.games) + 1, played_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
                    self.games.append(row)
                    return [row]
                if method == 'PATCH':
                    rows = [g for g in self.games if str(g['id']) == params['id'][3:] and g['user_id'] == params['user_id'][3:]]
                    for row in rows:
                        row.update(json)
                    return rows
                return [g for g in self.games if g['user_id'] == params.get('user_id', 'eq.')[3:]]
            if path == 'online_reports':
                if method == 'POST':
                    if not any(r['game_hash'] == json['game_hash'] and r['reporter'] == json['reporter'] for r in self.reports):
                        self.reports.append(dict(json, applied=False, created_at=time.time()))
                    return None
                return [dict(r) for r in self.reports if r['game_hash'] == params['game_hash'][3:]]
            if path == 'rpc/apply_rated_game':
                return self.apply(json['p_hash'], json['p_white'], json['p_black'], json['p_white_score'])
        raise AssertionError('the fake Supabase has no %s %s' % (method, path))

    def apply(self, gameHash, white, black, whiteScore):
        """supabase/schema.sql's apply_rated_game: once per game, Elo with K = 32, 3 games per pair a day."""
        if any(r['applied'] for r in self.reports if r['game_hash'] == gameHash):
            return 'counted'
        recent = {r['game_hash'] for r in self.reports if r['applied'] and r['created_at'] > time.time() - 86400
                  and {r['white_id'], r['black_id']} == {white, black}}
        if len(recent) >= 3:
            return 'limit'
        for r in self.reports:
            if r['game_hash'] == gameHash:
                r['applied'] = True
        wr, br = self.profiles[white]['rating'], self.profiles[black]['rating']
        delta = round(32 * (whiteScore - 1 / (1 + 10 ** ((br - wr) / 400.0))))
        self.profiles[white]['rating'] += delta
        self.profiles[black]['rating'] -= delta
        self.profiles[white]['rated_games'] += 1
        self.profiles[black]['rated_games'] += 1
        return 'applied'


def serveApi(port):
    from flask import jsonify
    spec = importlib.util.spec_from_file_location('api_account', os.path.join(ROOT, 'api', 'account.py'))
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    backend = Backend()
    api.rest, api.supabase = backend.rest, backend.supabase
    api.SUPABASE_URL, api.SERVICE_KEY = 'http://fake', 'fake'

    def debug():
        with backend.lock:
            return jsonify({'profiles': backend.profiles, 'reports': backend.reports, 'games': len(backend.games)})
    api.app.add_url_rule('/debug', 'debug', debug)
    api.app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False)


# --------------------------------------------------------------------------------------------- the players
def say(**data):
    print('E2E ' + json.dumps(data), flush=True)


async def player(role, relayPort, apiPort, folder, games):
    import pygame as p
    import main
    from engine import GameState
    from account import account
    main.GAME_VIEW = view = {}
    main.CLOCK_OPTIONS.append(("0+0", (5, 0)))  # five seconds each, for the last game
    name, email = ACCOUNTS[role]
    mouse = MOUSE
    SQ = main.SQ_SIZE

    async def wait(label, condition, seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if condition():
                return
            await asyncio.sleep(0.05)
        raise AssertionError('%s: timed out waiting for %s (view: %s)' % (role, label, view))

    def post(pos):
        mouse[0] = pos
        p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=pos))

    async def click(pos, after=0.25):
        post(pos)
        await asyncio.sleep(after)

    async def typeText(text):
        for ch in text:
            p.event.post(p.event.Event(p.KEYDOWN, key=ord(ch.lower()), unicode=ch, mod=0, scancode=0))
            await asyncio.sleep(0.03)

    def cell(code, color):
        row, col = main.Move.ranksToRows[code[1]], main.Move.filesToCols[code[0]]
        row, col = (7 - row, 7 - col) if color == 'b' else (row, col)
        return (col * SQ + SQ // 2, row * SQ + SQ // 2)

    async def playMove(code):
        ply = len(view['moves'])
        await click(cell(code[:2], view['color']), 0.15)
        await click(cell(code[2:4], view['color']), 0.3)
        await wait('our move %s to show' % code, lambda: len(view['moves']) > ply and view['moves'][ply] == code, 15)

    def layout():
        return main.panelLayout(2, view['online'])

    async def accept():
        await click(main.promptRects()[1].center, 0.4)

    async def setUp():
        await account.register(email, PASSWORD, name)
        await wait('the game to start', lambda: 'frames' in view, 30)
        mode = main.panelLayout(0, False)['mode']
        await click(mode.center)
        await click(main.dropdownOptionRects(mode, len(main.MODE_OPTIONS))[2].center, 0.5)

    async def openRoom(number, clock=False):
        roomFile = os.path.join(folder, 'room%d.txt' % number)
        setup = main.panelLayout(2, False, number > 1)  # after the first room there is a Rejoin button too
        if role == 'host':
            if clock:
                rect = setup['clock']
                await click(rect.center)
                await click(main.dropdownOptionRects(rect, len(main.CLOCK_OPTIONS))[-1].center, 0.4)
            await click(setup['host'].center, 0.5)
            await wait('the room', lambda: view['online'] and view['room'], 15)
            with open(roomFile, 'w') as f:
                f.write(view['room'])
        else:
            await wait('the room code', lambda: os.path.exists(roomFile) and open(roomFile).read(), 60)
            await asyncio.sleep(0.3)
            await click(setup['room'].center)
            await typeText(open(roomFile).read())
            await click(setup['join'].center, 0.5)
            await wait('joining', lambda: view['online'], 15)

    def legal(moves):
        gs = GameState()
        for code in moves:
            gs.makeMove(gs.findMoveByCode(code, gs.getValidMoves()))
        return gs

    async def playGame(index, scenario, expectedGame):
        await wait('game %d to begin' % (index + 1), lambda: view['online'] and view['game'] == expectedGame
                   and view['moves'] == [] and not view['over'], 40)
        # both are here before anybody moves
        other = 'guest' if role == 'host' else 'host'
        open(os.path.join(folder, 'ready%d_%s' % (index, role)), 'w').close()
        await wait('the other player', lambda: os.path.exists(os.path.join(folder, 'ready%d_%s' % (index, other))), 60)
        color = view['color']
        script = scenario.get('moves', '').split()
        random_plies = scenario.get('random', 0)
        hinted = None

        def myTurn():
            return (len(view['moves']) % 2 == 0) == (color == 'w')

        async def follow(target):
            """Plays our moves and waits for theirs until the game has target plies."""
            nonlocal hinted
            while len(view['moves']) < target and not view['over']:
                ply = len(view['moves'])
                if myTurn():
                    if script and ply < len(script):
                        code = script[ply]
                    else:
                        gs = legal(view['moves'])
                        options = [m for m in gs.getValidMoves() if not m.isPawnPromotion] or gs.getValidMoves()
                        code = random.Random(7000 + ply).choice(options).getCode()
                    if scenario.get('hint') == color and ply == 2 and hinted is None:
                        await wait('our turn', lambda: view['humanTurn'], 15)
                        await click(layout()['hint'].center, 0.2)
                        await wait('the hint', lambda: view['status'].startswith('Hint:'), 15)
                        hinted = view['status']
                    await wait('our turn', lambda: view['humanTurn'] or view['over'], 20)
                    if view['over']:
                        break
                    await playMove(code)
                else:
                    await wait('their move', lambda: len(view['moves']) > ply or view['over'], 30)

        target = len(script) if script else random_plies
        await follow(target)
        if 'undo' in scenario:
            asker, after = scenario['undo']
            before = len(view['moves'])
            if color == asker:
                await click(layout()['undo'].center, 0.3)
            else:
                await wait('the undo request', lambda: view['prompt'] == 'undo', 15)
                await accept()
            await wait('the undo', lambda: len(view['moves']) < before, 15)
            script = view['moves'] + after.split()
            await follow(len(script))
        end = scenario['end']
        if end == 'mate':
            pass
        elif end == 'flag':
            pass
        elif end[0] == 'resign':
            if color == end[1]:
                await click(layout()['resign'].center, 0.3)
                await wait('the question', lambda: view['prompt'] == 'resign', 10)
                await accept()
        elif end[0] == 'draw':
            if color == end[1]:
                await click(layout()['draw'].center, 0.3)
            else:
                await wait('the draw offer', lambda: view['prompt'] == 'draw', 15)
                await accept()
        await wait('the end of the game', lambda: view['over'], 40)
        moves, result = list(view['moves']), view['result'][0] if view['result'] else None
        await asyncio.sleep(1.5)  # the result is saved and reported to the rating server
        say(event='game', index=index + 1, name=scenario['name'], who=role, color=color, moves=moves, result=result,
            hint=hinted)

    async def next_game(index, via):
        """After the game: the next one is started the way its scenario says (the host clicks the result card)."""
        if via == 'room':
            await click(layout()['restart'].center, 0.4)
            await wait('the question', lambda: view['prompt'] == 'restart', 10)
            await accept()
            await wait('leaving', lambda: not view['online'], 10)
            await asyncio.sleep(1.0 if role == 'guest' else 0.2)
            await openRoom(2, clock=True)
        elif role == 'host':
            card = main.resultCardLayout(view['result'][0], ['rematch', 'new'])[2]
            await click(card[via].center, 0.5)

    try:
        await setUp()
        await openRoom(1)
        expected = 0
        for index, scenario in enumerate(SCENARIOS[:games]):
            await playGame(index, scenario, expected)
            if index + 1 < games:
                nextVia = SCENARIOS[index + 1].get('via')
                await next_game(index, nextVia)
                expected = 0 if nextVia == 'room' else expected + 1
        await asyncio.sleep(3)
        say(event='done', who=role, rating=account.profile['rating'], games=account.profile['rated_games'])
    except Exception as e:
        import traceback
        say(event='failed', who=role, error=str(e), trace=traceback.format_exc()[-1500:])
    p.event.post(p.event.Event(p.QUIT))


def runPlayer(role, relayPort, apiPort, folder, games):
    import asyncio as aio
    sys.path.insert(0, GAME)
    os.chdir(GAME)
    import pygame as p
    p.init()
    MOUSE[0] = (0, 0)
    p.mouse.get_pos = lambda: MOUSE[0]  # the game reads the pointer, not the events' positions
    import settings
    settings.put('seenHelp', True)  # How to play opens by itself on the first visit
    settings.put('language', 'en')
    import main

    async def both():
        await aio.gather(main.main(), player(role, relayPort, apiPort, folder, games))
    aio.run(both())


# ------------------------------------------------------------------------------------------ the orchestrator
def get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode())


def waitUp(url, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            get(url)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('%s did not start' % url)


def orchestrate(games):
    relayPort, apiPort = freePort(), freePort()
    folder = tempfile.mkdtemp(prefix='chess-e2e-')
    me = [sys.executable, os.path.abspath(__file__)]
    background = [subprocess.Popen(me + ['relay', str(relayPort)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                  subprocess.Popen(me + ['api', str(apiPort)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    try:
        waitUp('http://127.0.0.1:%d/stats' % relayPort)
        waitUp('http://127.0.0.1:%d/debug' % apiPort)
        players = {}
        for role in ('host', 'guest'):
            home = os.path.join(folder, role)
            os.makedirs(home)
            env = dict(os.environ, USERPROFILE=home, HOME=home, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy',
                       CHESS_NO_STOCKFISH='1', PYTHONIOENCODING='utf-8', CHESS_NTFY_URL='http://127.0.0.1:%d' % relayPort,
                       CHESS_API_URL='http://127.0.0.1:%d' % apiPort)
            log = open(os.path.join(folder, role + '.log'), 'w', encoding='utf-8')
            players[role] = (subprocess.Popen(me + ['player', role, str(relayPort), str(apiPort), folder, str(games)],
                                              stdout=log, stderr=subprocess.STDOUT, env=env), log)
        started = time.time()
        for role, (proc, log) in players.items():
            try:
                proc.wait(timeout=max(10, 900 - (time.time() - started)))
            except subprocess.TimeoutExpired:
                proc.kill()
        events = {'host': [], 'guest': []}
        for role in events:
            with open(os.path.join(folder, role + '.log'), encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith('E2E '):
                        events[role].append(json.loads(line[4:]))
        return report(events, get('http://127.0.0.1:%d/debug' % apiPort), get('http://127.0.0.1:%d/stats' % relayPort),
                      games, time.time() - started, folder)
    finally:
        for proc in background:
            proc.kill()


def report(events, debug, stats, games, seconds, folder):
    problems = []
    print("\nOnline Multiplayer: %d games, 2 test accounts, %.0f s (logs in %s)\n" % (games, seconds, folder))
    for role in events:
        for event in events[role]:
            if event['event'] == 'failed':
                problems.append('%s failed: %s\n%s' % (role, event['error'], event['trace']))
    byGame = {role: {e['index']: e for e in events[role] if e['event'] == 'game'} for role in events}
    print("%-3s %-34s %-6s %-7s %-34s %s" % ('#', 'game', 'host', 'plies', 'result', 'both clients agree'))
    for index, scenario in enumerate(SCENARIOS[:games], 1):
        host, guest = byGame['host'].get(index), byGame['guest'].get(index)
        if not host or not guest:
            problems.append('game %d (%s) was not finished by %s' % (
                index, scenario['name'], 'either player' if not host and not guest else 'host' if not host else 'guest'))
            print("%-3d %-34s not finished" % (index, scenario['name']))
            continue
        agree = host['moves'] == guest['moves'] and host['result'] == guest['result'] and host['color'] != guest['color']
        expectedResult = scenario['result']
        right = expectedResult is None or host['result'] == expectedResult
        if scenario.get('moves') and 'undo' not in scenario and                 host['moves'][:len(scenario['moves'].split())] != scenario['moves'].split():
            right = False
        if not agree:
            problems.append('game %d: the clients disagree (%s / %s)' % (index, host, guest))
        if not right:
            problems.append('game %d: expected %r, got %r' % (index, expectedResult, host['result']))
        print("%-3d %-34s %-6s %-7d %-34s %s" % (index, scenario['name'], 'White' if host['color'] == 'w' else 'Black',
                                                 len(host['moves']), host['result'], 'yes' if agree else 'NO'))
    byHash = {}
    for r in debug['reports']:
        byHash.setdefault(r['game_hash'], []).append(r)
    applied = sum(1 for rows in byHash.values() if any(r['applied'] for r in rows))
    pending = sum(1 for rows in byHash.values() if len(rows) == 1 and not any(r['applied'] for r in rows))
    print("\nRatings: %s" % ", ".join("%s %d (%d rated games)" % (p['username'], p['rating'], p['rated_games'])
                                      for p in debug['profiles'].values()))
    print("Reports to the rating server: %d games reported, %d counted, %d waiting for a second report, "
          "%d not counted (the pair's limit of 3 a day)" % (len(byHash), applied, pending,
                                                              len(byHash) - applied - pending))
    messages = sum(stats.values())
    print("Messages through the relay: %d (%.1f a game, %.0f a minute)" % (messages, messages / max(games, 1),
                                                                         messages / max(seconds / 60, 0.1)))
    ratings = [p['rating'] for p in debug['profiles'].values()]
    # a game counts when both report it: not with a hint in it, not under 4 plies; and 3 games a day for a pair
    eligible = [sc for sc in SCENARIOS[:games] if not sc.get('hint') and sc.get('end') != 'flag']
    if applied != min(3, len(eligible)):
        problems.append('expected %d rated games for this pair in a day, the server counted %d'
                        % (min(3, len(eligible)), applied))
    if sum(ratings) != 2400:
        problems.append('the ratings should add up to 2400, they are %d' % sum(ratings))
    if pending < 1 and any(sc.get('hint') for sc in SCENARIOS[:games]):
        problems.append('the game with a hint should have been reported by one player only')
    print()
    if problems:
        print("PROBLEMS:")
        for line in problems:
            print(" - " + line)
        return 1
    print("All %d games were played and agreed by both clients; the rating server counted what it should." % games)
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'relay':
        serveRelay(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == 'api':
        serveApi(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == 'player':
        runPlayer(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], int(sys.argv[6]))
    else:
        count = int(sys.argv[sys.argv.index('--games') + 1]) if '--games' in sys.argv else len(SCENARIOS)
        sys.exit(orchestrate(min(count, len(SCENARIOS))))
