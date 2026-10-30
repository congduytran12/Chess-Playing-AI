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
import hashlib
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
MOVE_PATTERN = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')  # Move.getCode in the game
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


def getProfile(userId):
    rows = rest('GET', 'profiles', params={'id': 'eq.' + userId, 'select': 'id,username,rating,rated_games'})
    if not rows:
        raise ApiError('This account has no profile', 404)
    return rows[0]


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
    if res.status_code == 429 or res.status_code >= 500:
        raise authUnavailable(res)
    if res.status_code >= 400:  # e.g. an address the service refuses: still no hint whether it has an account
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
