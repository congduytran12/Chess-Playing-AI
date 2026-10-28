# The player's account: sign-up, sign-in, stats, saved games and ratings, through the game's /api/account endpoint.
# Requests never block the game loop: in the browser they go through fetch and are polled, on desktop they run
# on a worker thread. The sign-in is remembered (browser localStorage, or a file in the home folder on desktop).

import os
import sys
import json
import time
import asyncio
import urllib.request
import urllib.error

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

# the browser build calls its own site; the desktop game calls the deployed one (override with CHESS_API_URL)
API_URL = "/api/account" if WASM else os.environ.get('CHESS_API_URL', "https://chess-playing-ai.vercel.app") + "/api/account"
REQUEST_SECONDS = 20
STORAGE_KEY = "chess_ai_account"
STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".chess-playing-ai-account.json")  # desktop only

JS_HELPERS = '''
    window.chessApiResults = {};
    window.chessApiRequest = function(id, url, body) {
        fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: body})
            .then(r => r.text().then(t => { window.chessApiResults[id] = JSON.stringify({status: r.status, body: t}); }))
            .catch(e => { window.chessApiResults[id] = JSON.stringify({status: 0, body: String(e)}); });
    }
    window.chessApiTake = function(id) {
        const result = window.chessApiResults[id];
        if (result === undefined) return "";
        delete window.chessApiResults[id];
        return result;
    }
'''


class AccountError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class Account:
    def __init__(self):
        self.token = None  # access token, valid for about an hour
        self.refreshToken = None
        self.profile = None  # {'id', 'username', 'rating', 'rated_games'}
        self.stats = {}  # 'ai0'..'ai4' / 'online' -> {'won', 'lost', 'drawn'}
        self._jsReady = False
        self._nextRequestId = 0
        self._session = 0  # bumped by sign-in and sign-out; answers to requests from an older session are dropped

    @property
    def signedIn(self):
        return self.profile is not None

    @property
    def username(self):
        return self.profile['username'] if self.profile else None

    # --- requests

    async def _post(self, payload):
        body = json.dumps(payload)
        if WASM:
            if js is None:
                raise AccountError("Accounts aren't available here")
            if not self._jsReady:
                js.eval(JS_HELPERS)
                self._jsReady = True
            self._nextRequestId += 1
            requestId = self._nextRequestId
            js.eval("window.chessApiRequest(%d, %s, %s)" % (requestId, json.dumps(API_URL), json.dumps(body)))
            deadline = time.time() + REQUEST_SECONDS
            while True:
                raw = js.eval("window.chessApiTake(%d)" % requestId)
                if raw:
                    break
                if time.time() > deadline:
                    raise AccountError("The server didn't answer")
                await asyncio.sleep(0.05)
            reply = json.loads(str(raw))
            status, text = reply['status'], reply['body']
        else:
            status, text = await asyncio.get_event_loop().run_in_executor(None, _postBlocking, body)
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {}
        if status != 200:
            raise AccountError(data.get('error') or ("Can't reach the server" if status == 0 else "Server error %d" % status), status)
        return data

    # a signed-in request; an expired access token is refreshed once and the request retried
    async def _authed(self, action, **fields):
        if not self.token:
            raise AccountError("Not signed in", 401)
        try:
            return await self._post(dict(fields, action=action, token=self.token))
        except AccountError as e:
            if e.status != 401 or not self.refreshToken:
                raise
        await self._refresh()
        return await self._post(dict(fields, action=action, token=self.token))

    async def _refresh(self):
        session = self._session
        try:
            data = await self._post({'action': 'refresh', 'refresh': self.refreshToken})
        except AccountError as e:
            if e.status == 401 and session == self._session:
                self.signOut()
            raise
        if session != self._session:
            raise AccountError("Not signed in", 401)  # signed out (or in as someone else) meanwhile
        self._signedInWith(data)

    def _signedInWith(self, data):
        self.token = data['token']
        self.refreshToken = data['refresh']
        self.profile = data['profile']
        self._store(self.refreshToken)

    # --- account

    async def restore(self):
        """Signs back in with the remembered refresh token, if there is one."""
        self.refreshToken = self._load()
        if not self.refreshToken:
            return
        try:
            await self._refresh()
            await self.loadStats()
        except AccountError as e:
            print("Account: could not restore the sign-in -", e)

    async def register(self, email, password, username):
        """Returns True when signed in, False when the email must be confirmed first."""
        data = await self._post({'action': 'register', 'email': email, 'password': password, 'username': username})
        if data.get('confirm'):
            return False
        self._session += 1
        self._signedInWith(data)
        self.stats = {}
        return True

    async def signIn(self, email, password):
        data = await self._post({'action': 'login', 'email': email, 'password': password})
        self._session += 1
        self._signedInWith(data)
        await self.loadStats()

    def signOut(self):
        self._session += 1
        self.token = self.refreshToken = self.profile = None
        self.stats = {}
        self._store(None)

    async def loadStats(self):
        session = self._session
        data = await self._authed('me')
        if session == self._session:
            self.profile = data['profile']
            self.stats = data['stats']

    async def saveGame(self, game):
        """Saves a finished game ({'id'?, 'mode', 'ai_level', 'color', 'opponent', 'result', 'pgn'}); returns its id."""
        data = await self._authed('save_game', game=game)
        return data['id']

    async def listGames(self):
        return (await self._authed('games'))['games']

    async def loadGame(self, gameId):
        return (await self._authed('game', id=gameId))['pgn']

    async def reportOnline(self, whiteId, blackId, gameId, moves, result):
        """Returns (rated, pending, reason); the profile's rating is updated when the game counted.
        gameId is the id both players share for the game, so both reports are matched up."""
        session = self._session
        data = await self._authed('report_online', white_id=whiteId, black_id=blackId, game_id=gameId,
                                  moves=moves, result=result)
        if session == self._session:
            self.profile = data.get('profile', self.profile)
        return bool(data.get('rated')), bool(data.get('pending')), data.get('reason')

    async def leaderboard(self):
        return (await self._post({'action': 'leaderboard'}))['players']

    # --- remembered sign-in

    def _store(self, refreshToken):
        data = json.dumps({'refresh': refreshToken}) if refreshToken else ""
        try:
            if WASM:
                if js is not None:
                    js.eval("localStorage.setItem(%s, %s)" % (json.dumps(STORAGE_KEY), json.dumps(data)))
            elif data:
                with open(STORAGE_FILE, "w") as f:
                    f.write(data)
            elif os.path.exists(STORAGE_FILE):
                os.remove(STORAGE_FILE)
        except Exception as e:
            print("Account: could not remember the sign-in -", e)

    def _load(self):
        try:
            if WASM:
                data = js.eval("localStorage.getItem(%s) || ''" % json.dumps(STORAGE_KEY)) if js is not None else ""
            elif os.path.exists(STORAGE_FILE):
                with open(STORAGE_FILE) as f:
                    data = f.read()
            else:
                data = ""
            return json.loads(str(data)).get('refresh') if data else None
        except Exception as e:
            print("Account: could not read the remembered sign-in -", e)
            return None


def _postBlocking(body):
    request = urllib.request.Request(API_URL, data=body.encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_SECONDS) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')
    except Exception as e:
        return 0, json.dumps({'error': "Can't reach the server (%s)" % e})


account = Account()
