# Player accounts for the game: registration, sign-in, stats, saved games, ratings and the leaderboard.
# Backed by Supabase (see supabase/schema.sql). The game only talks to this endpoint, which uses the service
# role key, so the database tables stay closed to the public.
#
# Vercel environment variables: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
#
# Every request is a POST with a JSON body {"action": ..., ...}; signed-in actions also carry "token",
# the access token returned by "login". Errors come back as {"error": message} with a 4xx/5xx status.

import os
import re
import math
import importlib.util
import hashlib
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Use a global session for connection pooling
session = requests.Session()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_]{3,20}$')
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MIN_PASSWORD_LENGTH = 8
BAD_LOGIN = 'Invalid login credentials'  # Supabase Auth's answer to a wrong email or password
MAX_PGN_LENGTH = 20000
GAMES_LISTED = 50  # the newest saved games shown in the game's My games list
RESET_LINK_EXPIRED = 'This reset link has expired, ask for a new one'
RESULTS = ('1-0', '0-1', '1/2-1/2')
MIN_RATED_PLIES = 4  # shorter online games don't change ratings
MAX_CHECKED_PLIES = 600  # longer reports aren't replayed (a game is at most about this long)
MOVE_PATTERN = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')  # Move.getCode in the game
ADMIN_USERNAMES = {'congduytran12'}  # lower case; their profiles say 'admin' (the game gives them unlimited hints)
# Your mistakes (game/mistakes.py): a mistake solved MISTAKE_SOLVES times in a row is learned and doesn't come back;
# one missed comes back after MISTAKE_AGAIN, one solved after MISTAKE_LATER. Premium practises every game's mistakes
# that are due, without it the latest game's
MISTAKE_SOLVES = 2
MISTAKE_AGAIN = timedelta(minutes=10)
MISTAKE_LATER = timedelta(days=3)
MISTAKES_LISTED = 30  # the mistakes sent for one round of practice at most
MAX_MISTAKES_SAVED = 30  # the mistakes of one game kept at most (game/mistakes.py MAX_PER_GAME)
MAX_MISTAKES_READ = 1000  # a player's mistakes looked through for those to practise
MISTAKE_SCORE_CAP = 10  # pawns; scores are kept within +-this (game/mistakes.py SCORE_CAP)
FEN_PATTERN = re.compile(r'^[1-8pnbrqkPNBRQK]{1,8}(/[1-8pnbrqkPNBRQK]{1,8}){7} [wb] (-|K?Q?k?q?) (-|[a-h][36])'
                         r'( \d{1,3} \d{1,4})?$')
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Cache-Control': 'no-store',
}


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def supabase(method, path, token=None, **kwargs):
    headers = {
        'apikey': SERVICE_KEY,
        'Authorization': 'Bearer ' + (token or SERVICE_KEY),
        'Content-Type': 'application/json',
    }
    headers.update(kwargs.pop('headers', {}))
    try:
        return session.request(method, SUPABASE_URL + path, headers=headers, timeout=8, **kwargs)
    except requests.exceptions.RequestException as e:
        raise ApiError("Can't reach the account service: %s" % e, 502)


# database access through PostgREST, with the service role
def rest(method, path, **kwargs):
    res = supabase(method, '/rest/v1/' + path, **kwargs)
    if res.status_code >= 400:
        print(f"[account] {method} {path} -> {res.status_code} {res.text[:300]}")
        raise ApiError('Database error', 502)
    return res.json() if res.text else None


def authErrorMessage(res):
    try:
        body = res.json()
    except ValueError:
        body = {}
    return body.get('msg') or body.get('error_description') or body.get('message') or 'Sign-in failed'


def text(data, key, limit=200):
    value = data.get(key)
    if not isinstance(value, str):
        raise ApiError('Missing ' + key)
    return value.strip()[:limit]


# the signed-in player's id, from the access token sent with the request
def currentUser(data):
    token = data.get('token')
    if not isinstance(token, str) or not token:
        raise ApiError('Not signed in', 401)
    res = supabase('GET', '/auth/v1/user', token=token)
    if res.status_code in (401, 403):
        raise ApiError('Your session expired, please sign in again', 401)
    if res.status_code != 200:
        raise authUnavailable(res)
    return res.json()['id']


# a temporary auth service problem (rate limit, outage) must not look like a bad token: the game signs out on 401
def authUnavailable(res):
    print(f"[account] auth service -> {res.status_code} {res.text[:300]}")
    return ApiError('The account service is busy, please try again', 503)


def now():
    return datetime.now(timezone.utc)


# a timestamp from the database (ISO 8601, any number of digits after the second's point), or None
def parseTime(value):
    if not isinstance(value, str) or not value:
        return None
    value = re.sub(r'\.(\d+)', lambda m: '.' + (m.group(1) + '000000')[:6], value.replace('Z', '+00:00'))
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# select=*: premium_until, which schema.sql adds to an older table, is read once it is there and left out until then
# (an admin has Premium too)
def getProfile(userId):
    rows = rest('GET', 'profiles', params={'id': 'eq.' + userId, 'select': '*'})
    if not rows:
        raise ApiError('This account has no profile', 404)
    profile = {key: rows[0].get(key) for key in ('id', 'username', 'rating', 'rated_games', 'premium_until')}
    profile['admin'] = str(profile.get('username') or '').lower() in ADMIN_USERNAMES
    until = parseTime(profile['premium_until'])
    profile['premium'] = profile['admin'] or (until is not None and until > now())
    return profile


def signedIn(session):
    return {'token': session['access_token'], 'refresh': session['refresh_token'],
            'profile': getProfile(session['user']['id'])}


def register(data):
    email = text(data, 'email')
    password = text(data, 'password')
    username = text(data, 'username')
    if not EMAIL_PATTERN.match(email):
        raise ApiError("That doesn't look like an email address")
    if not USERNAME_PATTERN.match(username):
        raise ApiError('Usernames are 3-20 letters, digits or _')
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError('Passwords need at least %d characters' % MIN_PASSWORD_LENGTH)
    # ilike ignores case like the unique index does; _ is a wildcard in patterns, so it's escaped
    if rest('GET', 'profiles', params={'username': 'ilike.' + username.replace('_', '\\_'), 'select': 'id'}):
        raise ApiError('That username is taken')
    res = supabase('POST', '/auth/v1/signup', json={'email': email, 'password': password, 'data': {'username': username}})
    if res.status_code >= 400:
        raise ApiError(authErrorMessage(res))
    body = res.json()
    if body.get('access_token'):
        return signedIn(body)
    return {'confirm': True}  # email confirmation is on: the player signs in after clicking the link


# "login" is the email or the username ("email" from older game versions)
def login(data):
    name = text(data, 'login' if 'login' in data else 'email')
    password = text(data, 'password')
    email = name if '@' in name else emailOfUsername(name)
    res = supabase('POST', '/auth/v1/token?grant_type=password', json={'email': email, 'password': password})
    if res.status_code != 200:
        raise ApiError(authErrorMessage(res), 401)
    return signedIn(res.json())


# Supabase Auth signs in by email only, so a username is looked up first; an unknown username gets
# the same answer as a wrong password, so sign-in doesn't reveal which usernames exist
def emailOfUsername(username):
    if not USERNAME_PATTERN.match(username):
        raise ApiError(BAD_LOGIN, 401)
    rows = rest('GET', 'profiles', params={'username': 'ilike.' + username.replace('_', '\\_'), 'select': 'id'})
    if not rows:
        raise ApiError(BAD_LOGIN, 401)
    res = supabase('GET', '/auth/v1/admin/users/' + rows[0]['id'])  # needs the service role key
    if res.status_code != 200:
        raise authUnavailable(res)
    email = res.json().get('email')
    if not email:
        raise ApiError(BAD_LOGIN, 401)
    return email


def refresh(data):
    res = supabase('POST', '/auth/v1/token?grant_type=refresh_token', json={'refresh_token': text(data, 'refresh', 1000)})
    if res.status_code in (400, 401, 403):  # the refresh token is invalid, expired or already used
        raise ApiError('Please sign in again', 401)
    if res.status_code != 200:
        raise authUnavailable(res)
    return signedIn(res.json())


# "Forgot password?": Supabase emails a link that signs the player in for choosing a new password. The answer is
# the same whether or not an account uses the email, so this can't be used to find out who has an account.
# redirect_to is where the link leads (the game's site; it must be in the project's redirect URL allow-list)
def recover(data):
    email = text(data, 'email')
    if not EMAIL_PATTERN.match(email):
        raise ApiError("That doesn't look like an email address")
    params = {}
    redirect = data.get('redirect_to')
    if isinstance(redirect, str) and re.match(r'^https?://[^\s]{1,300}$', redirect):
        params['redirect_to'] = redirect
    res = supabase('POST', '/auth/v1/recover', params=params, json={'email': email})
    if res.status_code >= 500:
        raise authUnavailable(res)
    # e.g. an address the service refuses, or 429: GoTrue sends a known address one email a minute and answers a
    # second request with 429, which an unknown address never gets; so that is no hint whether it has an account
    if res.status_code >= 400:
        print(f"[account] recover -> {res.status_code} {res.text[:300]}")
    return {'sent': True}


# the new password, with the access token from the reset link (it signs in only for this)
def setPassword(data):
    token = text(data, 'token', 4000)
    password = text(data, 'password')
    if not token:
        raise ApiError(RESET_LINK_EXPIRED, 401)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError('Passwords need at least %d characters' % MIN_PASSWORD_LENGTH)
    res = supabase('PUT', '/auth/v1/user', token=token, json={'password': password})
    if res.status_code in (401, 403):
        raise ApiError(RESET_LINK_EXPIRED, 401)
    if res.status_code == 429 or res.status_code >= 500:
        raise authUnavailable(res)
    if res.status_code >= 400:  # e.g. the same password as before, or one the project's rules refuse
        raise ApiError(authErrorMessage(res))
    return {'ok': True}


# wins / losses / draws against each AI level and online
def me(data):
    userId = currentUser(data)
    rows = rest('GET', 'games', params={'user_id': 'eq.' + userId, 'select': 'mode,ai_level,color,result',
                                        'mode': 'neq.local', 'limit': '2000'})
    stats = {}
    for row in rows:
        if row['result'] not in RESULTS or row['color'] not in ('w', 'b'):
            continue
        key = 'ai%d' % (row['ai_level'] or 0) if row['mode'] == 'ai' else 'online'
        record = stats.setdefault(key, {'won': 0, 'lost': 0, 'drawn': 0})
        if row['result'] == '1/2-1/2':
            record['drawn'] += 1
        elif (row['result'] == '1-0') == (row['color'] == 'w'):
            record['won'] += 1
        else:
            record['lost'] += 1
    return {'profile': getProfile(userId), 'stats': stats}


# saves a finished game; with "id" it updates that game instead (the player undid moves and finished again)
def saveGame(data):
    userId = currentUser(data)
    game = data.get('game')
    if not isinstance(game, dict):
        raise ApiError('Missing game')
    mode = game.get('mode')
    if mode not in ('ai', 'local', 'online'):
        raise ApiError('Unknown game mode')
    result = game.get('result')
    if result not in RESULTS + ('*',):
        raise ApiError('Unknown result')
    pgn = game.get('pgn')
    if not isinstance(pgn, str) or not pgn or len(pgn) > MAX_PGN_LENGTH:
        raise ApiError('The game record is missing or too long')
    level = game.get('ai_level')
    row = {
        'user_id': userId,
        'mode': mode,
        'ai_level': level if mode == 'ai' and isinstance(level, int) else None,
        'color': game.get('color') if game.get('color') in ('w', 'b') else None,
        'opponent': str(game.get('opponent') or '')[:60],
        'result': result,
        'pgn': pgn,
    }
    gameId = game.get('id')
    if isinstance(gameId, int):
        rows = rest('PATCH', 'games', params={'id': 'eq.%d' % gameId, 'user_id': 'eq.' + userId},
                    json=row, headers={'Prefer': 'return=representation'})
        if rows:
            return {'id': gameId}
    rows = rest('POST', 'games', json=row, headers={'Prefer': 'return=representation'})
    return {'id': rows[0]['id']}


def listGames(data):
    userId = currentUser(data)
    rows = rest('GET', 'games', params={'user_id': 'eq.' + userId, 'order': 'played_at.desc', 'limit': str(GAMES_LISTED),
                                        'select': 'id,mode,ai_level,color,opponent,result,played_at'})
    return {'games': rows}


def getGame(data):
    userId = currentUser(data)
    gameId = data.get('id')
    if not isinstance(gameId, int):
        raise ApiError('Missing game id')
    rows = rest('GET', 'games', params={'id': 'eq.%d' % gameId, 'user_id': 'eq.' + userId, 'select': 'id,pgn'})
    if not rows:
        raise ApiError('Game not found', 404)
    return rows[0]


# The game's own rules engine (game/engine.py has no imports; vercel.json brings it into the function), loaded under a
# name of its own so nothing else on the path is shadowed. Without it the moves aren't replayed.
def loadEngine():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'game', 'engine.py')
    try:
        spec = importlib.util.spec_from_file_location('chess_engine', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"[account] the rules engine isn't available, reported games aren't replayed: {e}")
        return None


engine = loadEngine()


# A reported game is replayed with the game's rules: every move must be legal in turn, and a game that ended in
# checkmate or stalemate must be reported that way. (A resignation, a time-out or an agreed draw can't be seen in the
# moves, so any result fits a game that was still going.)
def checkGame(moves, result):
    if engine is None or len(moves) > MAX_CHECKED_PLIES:
        return
    game = engine.GameState()
    for code in moves:
        move = game.findMoveByCode(code, game.getValidMoves())
        if move is None:
            raise ApiError('The moves are not a legal game')
        game.makeMove(move)
    game.getValidMoves()  # finds out whether the game is over
    if game.checkmate and result != ('0-1' if game.whiteToMove else '1-0'):
        raise ApiError('The result does not fit the moves')
    if game.stalemate and result != '1/2-1/2':
        raise ApiError('The result does not fit the moves')


# Online games have no server watching them, so a result only changes ratings when both players reported
# the same result for the same game (game_id is the id both clients share for it, see main.py), and at most
# 3 games per pair of players a day (enforced in apply_rated_game) so two accounts can't farm rating
def reportOnline(data):
    userId = currentUser(data)
    white = text(data, 'white_id', 64)
    black = text(data, 'black_id', 64)
    gameId = text(data, 'game_id', 32)
    moves = text(data, 'moves', 8000).split()
    result = data.get('result')
    if userId not in (white, black) or white == black:
        raise ApiError("You didn't play in this game")
    if result not in RESULTS:
        raise ApiError('Unknown result')
    if not gameId:
        raise ApiError('Missing game_id')
    if not all(MOVE_PATTERN.match(move) for move in moves):
        raise ApiError('The moves are not in coordinate notation')
    if len(moves) < MIN_RATED_PLIES:
        return {'rated': False, 'reason': 'too short', 'profile': getProfile(userId)}
    checkGame(moves, result)

    gameHash = hashlib.sha256(('%s|%s|%s|%s' % (white, black, gameId, ' '.join(moves))).encode()).hexdigest()
    # insert first, then read: when both players report at the same moment, the later read sees both reports
    rest('POST', 'online_reports', params={'on_conflict': 'game_hash,reporter'},
         json={'game_hash': gameHash, 'reporter': userId, 'white_id': white, 'black_id': black, 'result': result},
         headers={'Prefer': 'resolution=ignore-duplicates,return=minimal'})
    reports = rest('GET', 'online_reports', params={'game_hash': 'eq.' + gameHash, 'select': 'reporter,result,applied'})
    if any(report['applied'] for report in reports):
        return {'rated': True, 'profile': getProfile(userId)}  # already counted
    if not any(report['reporter'] != userId and report['result'] == result for report in reports):
        return {'rated': False, 'pending': True, 'profile': getProfile(userId)}
    score = {'1-0': 1, '0-1': 0, '1/2-1/2': 0.5}[result]
    status = rest('POST', 'rpc/apply_rated_game', json={'p_hash': gameHash, 'p_white': white, 'p_black': black,
                                                         'p_white_score': score})
    if status == 'limit':
        return {'rated': False, 'reason': 'daily limit', 'profile': getProfile(userId)}
    return {'rated': True, 'profile': getProfile(userId)}


def leaderboard(data):
    rows = rest('GET', 'profiles', params={'rated_games': 'gt.0', 'order': 'rating.desc', 'limit': '10',
                                           'select': 'username,rating,rated_games'})
    return {'players': rows}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def legalMistake(fen, moves, played):
    try:
        game = engine.GameState.fromFen(fen)
        squares = [square for row in game.board for square in row]
        if (len(game.board) != 8 or any(len(row) != 8 for row in game.board) or squares.count('wK') != 1
                or squares.count('bK') != 1):
            return False
        first = game.findMoveByCode(moves[0], game.getValidMoves())
        if first is None:
            return False
        game.makeMove(first)
        answers = game.getValidMoves()
        return all(game.findMoveByCode(code, answers) is not None for code in (moves[1], played))
    except Exception:  # a position the rules can't make sense of
        return False


# A mistake of the player's (game/mistakes.py Mistake.payload), checked with the game's rules: the position, the
# opponent's move and the best answer to it, and the move played in the game instead, all legal. Returns the row kept
def checkMistake(item):
    if not isinstance(item, dict):
        raise ApiError('Not a mistake')
    fen = text(item, 'fen', 100)
    moves = text(item, 'moves', 20).split()
    played = text(item, 'played', 10)
    score, loss, ply = item.get('score'), item.get('loss'), item.get('ply')
    if (not FEN_PATTERN.match(fen) or len(moves) != 2 or played == moves[1]
            or not all(MOVE_PATTERN.match(code) for code in moves + [played])
            or not number(score) or not number(loss) or not isinstance(ply, int) or not 0 < ply <= MAX_CHECKED_PLIES):
        raise ApiError('Not a mistake')
    if engine is not None and not legalMistake(fen, moves, played):
        raise ApiError('The moves are not legal')
    return {'fen': fen, 'moves': ' '.join(moves), 'played': played,
            'score': round(max(-MISTAKE_SCORE_CAP, min(MISTAKE_SCORE_CAP, score)), 2),
            'loss': round(max(0, min(2 * MISTAKE_SCORE_CAP, loss)), 2),
            'opponent': str(item.get('opponent') or '')[:60], 'ply': ply}


# keeps the mistakes of an analyzed game; one kept before (the same position, moves and move played: made again)
# starts over, due now. Returns them with their ids
def saveMistakes(data):
    userId = currentUser(data)
    items = data.get('mistakes')
    if not isinstance(items, list) or not items:
        raise ApiError('Missing mistakes')
    if len(items) > MAX_MISTAKES_SAVED:
        raise ApiError('Too many mistakes at once')
    found = now().isoformat()
    rows = [dict(checkMistake(item), user_id=userId, solved=0, due_at=found, found_at=found) for item in items]
    saved = rest('POST', 'mistakes', params={'on_conflict': 'user_id,fen,moves,played'}, json=rows,
                 headers={'Prefer': 'resolution=merge-duplicates,return=representation'})
    return {'mistakes': [{key: row[key] for key in ('id', 'fen', 'moves', 'played')} for row in saved or []]}


# The mistakes to practise now: Premium's that are due, oldest due first, or without Premium those of the latest game
# (still to be learned, due or not). 'total' counts every mistake still to be learned, 'locked' those only Premium
# brings back, and 'next_due' says when Premium's next one is due when none is now
def listMistakes(data):
    userId = currentUser(data)
    premium = getProfile(userId)['premium']
    rows = rest('GET', 'mistakes', params={'user_id': 'eq.' + userId, 'order': 'found_at.desc,ply.asc',
                                           'limit': str(MAX_MISTAKES_READ), 'select': 'id,solved,due_at,found_at'})
    rows = rows or []
    moment = now()
    learning = [row for row in rows if row['solved'] < MISTAKE_SOLVES]
    if premium:
        due = [row for row in learning if (parseTime(row['due_at']) or moment) <= moment]
        chosen = sorted(due, key=lambda row: parseTime(row['due_at']) or moment)[:MISTAKES_LISTED]
    else:
        chosen = [row for row in learning if row['found_at'] == rows[0]['found_at']][:MISTAKES_LISTED]
    nextDue = None
    if premium and not chosen:
        nextDue = min((due for due in (parseTime(row['due_at']) for row in learning) if due is not None), default=None)
    found = []
    if chosen:
        found = rest('GET', 'mistakes', params={
            'user_id': 'eq.' + userId, 'id': 'in.(%s)' % ','.join(str(row['id']) for row in chosen),
            'select': 'id,fen,moves,played,score,loss,opponent,ply,solved'}) or []
        order = {row['id']: i for i, row in enumerate(chosen)}
        found.sort(key=lambda row: order.get(row['id'], 0))
    return {'mistakes': found, 'premium': premium, 'total': len(learning),
            'locked': 0 if premium else len(learning) - len(chosen),
            'next_due': nextDue.isoformat() if nextDue else None}


# a round of practice of one mistake: solved (at the first try, with no hint) counts towards learning it, anything
# else starts it over
def mistakeResult(data):
    userId = currentUser(data)
    mistakeId = data.get('id')
    if not isinstance(mistakeId, int) or isinstance(mistakeId, bool):
        raise ApiError('Missing mistake id')
    rows = rest('GET', 'mistakes', params={'id': 'eq.%d' % mistakeId, 'user_id': 'eq.' + userId, 'select': 'id,solved'})
    if not rows:
        raise ApiError('Mistake not found', 404)
    solved = rows[0]['solved'] + 1 if data.get('solved') is True else 0
    due = now() + (MISTAKE_LATER if solved else MISTAKE_AGAIN)
    rest('PATCH', 'mistakes', params={'id': 'eq.%d' % mistakeId, 'user_id': 'eq.' + userId},
         json={'solved': solved, 'due_at': due.isoformat()}, headers={'Prefer': 'return=minimal'})
    return {'solved': solved, 'learned': solved >= MISTAKE_SOLVES, 'due_at': due.isoformat()}


ACTIONS = {
    'register': register,
    'login': login,
    'refresh': refresh,
    'recover': recover,
    'set_password': setPassword,
    'me': me,
    'save_game': saveGame,
    'games': listGames,
    'game': getGame,
    'report_online': reportOnline,
    'leaderboard': leaderboard,
    'save_mistakes': saveMistakes,
    'mistakes': listMistakes,
    'mistake_result': mistakeResult,
}


@app.route('/api/account', methods=['POST', 'OPTIONS'])
def account():
    if request.method == 'OPTIONS':
        return '', 204, CORS_HEADERS
    if not SUPABASE_URL or not SERVICE_KEY:
        return jsonify({'error': 'Accounts are not set up on this server'}), 503, CORS_HEADERS
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('action') not in ACTIONS:
        return jsonify({'error': 'Unknown action'}), 400, CORS_HEADERS
    try:
        return jsonify(ACTIONS[data['action']](data)), 200, CORS_HEADERS
    except ApiError as e:
        return jsonify({'error': e.message}), e.status, CORS_HEADERS


# Vercel's Python runtime serves the Flask 'app'
handler = app
