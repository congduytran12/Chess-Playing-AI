"""Server-side proxy for the browser's optional LLM chess coach (Groq, OpenRouter, Gemini and Cloudflare Workers AI,
asked in turn with failover on 429 and other errors, see game/llm.py).

The browser sends the game's analysis (moves, best moves, evaluations, marks, result), never a prompt: the prompt is
built here, by game/llm.py's own _prompt, from data checked to be chess data. So the endpoint can't be used as a
general chatbot with the project's key, whatever is posted to it.
"""

import hashlib
import importlib.util
import math
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

MAX_PLIES = 1000  # more than any game worth explaining (an analysis lists one more position than moves)
MOVE_CODE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?\Z")
# a move in algebraic notation (Nf3, exd5, Qh4xe1+, e8=Q#, O-O-O): no other text gets through as a "move"
SAN = re.compile(r"^(?:O-O(?:-O)?|(?:[a-h]x)?[a-h][1-8](?:=[QRBN])?|[KQRBN][a-h]?[1-8]?x?[a-h][1-8])[+#]?\Z")
# a position: pieces, side to move, castling rights, en passant square, move counters
FEN = re.compile(r"^[pnbrqkPNBRQK1-8/]{15,71} [wb] (?:-|[KQkq]{1,4}) (?:-|[a-h][36]) \d{1,3} \d{1,4}\Z")
# the results the game reports (game/main.py), nothing else gets into the prompt
RESULTS = frozenset((
    "", "White wins by checkmate", "Black wins by checkmate", "White wins by resignation",
    "Black wins by resignation", "White wins on time", "Black wins on time", "Draw by agreement",
    "Draw by threefold repetition", "Draw by 50-move rule", "Draw by insufficient material", "Stalemate"))
MARKS = ("??", "?", "?!")
LANGUAGES = ("en", "vi")  # the languages the coach answers in (game/llm.py LANGUAGES)
MAX_HISTORY = 12  # moves before the explained one
MAX_NUMBER = 1000000
# a request limit per visitor, best effort: it is kept in memory, so every serverless instance counts on its own.
# Explaining single moves is a request each, so the limit is roomier than a game summary alone would need
LIMIT_REQUESTS = 30
LIMIT_SECONDS = 600
# a Premium player (unlimited hints) counts on their own, with room for a hint's explanation and the coach's pick
# on every move of a game played from hints (about two requests every 12 s)
PREMIUM_LIMIT_REQUESTS = 120
visits = {}
visitsLock = threading.Lock()
# who a Premium access token belongs to, remembered for a while so a hint doesn't wait on the account service each
# time: sha256 of the token -> (checked at, the player's id, or None when it isn't a Premium player's)
PREMIUM_CACHE_SECONDS = 600
premiumCache = {}
premiumLock = threading.Lock()
ADMIN_USERNAMES = {'congduytran12'}  # as api/account.py: an admin has Premium


def loadCoach():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game", "llm.py")
    try:
        spec = importlib.util.spec_from_file_location("chess_coach", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print("[llm] the coach's prompt isn't available: %s" % e)
        return None


coach_module = loadCoach()


def _content_text(content):
    if isinstance(content, list):
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    else:
        text = content if isinstance(content, str) else ""
    return coach_module.clean_text(text) if coach_module is not None else text.strip()


def askProvider(provider, prompt, tokens):
    """The text one provider answers with; raises when it can't be reached, errs or answers with nothing."""
    response = requests.post(provider["url"], headers={"Authorization": "Bearer " + provider["key"]},
                             json=coach_module.chat_body(provider, prompt, tokens), timeout=20)
    if response.status_code == 429:  # too many requests: the next provider is asked at once, this one rests a while
        raise coach_module.RateLimited("%s returned status 429" % provider["name"],
                                       coach_module.retry_after_seconds(response.headers.get("Retry-After")))
    if response.status_code != 200:
        raise ValueError("%s returned status %s" % (provider["name"], response.status_code))
    try:
        choice = response.json()["choices"][0]
        text = _content_text(choice["message"].get("content"))
        if choice.get("finish_reason") == "length" and coach_module is not None:
            text = coach_module.whole_sentences(text)  # cut off at the token limit: its full sentences only
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ValueError("%s returned an invalid response" % provider["name"])
    if not text:
        raise ValueError("%s returned an empty response" % provider["name"])
    return text


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        and abs(value) <= MAX_NUMBER


def _list(value, check, allowNone=False):
    return isinstance(value, list) and len(value) <= MAX_PLIES + 1 and all(
        (allowNone and item is None) or check(item) for item in value)


def checkedAnalysis(payload):
    """The (moves, best, evals, marks, result) of a payload that is chess data, or None."""
    moves, best, evals = payload.get("moves"), payload.get("best"), payload.get("evals")
    marks, result = payload.get("marks"), payload.get("result", "")
    if not _list(moves, lambda m: isinstance(m, str) and MOVE_CODE.match(m)) or not moves or len(moves) > MAX_PLIES:
        return None
    if not _list(best, lambda m: isinstance(m, str) and SAN.match(m), allowNone=True):
        return None
    if not _list(evals, _number):
        return None
    if not isinstance(result, str) or result not in RESULTS:
        return None
    if not isinstance(marks, list) or len(marks) > MAX_PLIES:
        return None
    markDict = {}
    for entry in marks:
        if not (isinstance(entry, list) and len(entry) == 3 and isinstance(entry[0], int)
                and not isinstance(entry[0], bool) and 0 <= entry[0] < len(moves) and entry[1] in MARKS
                and _number(entry[2])):
            return None
        markDict[entry[0]] = (entry[1], entry[2])
    return moves, best, evals, markDict, result


def _san(value, allowNone=False):
    return (allowNone and value is None) or (isinstance(value, str) and SAN.match(value) is not None)


def _fen(value):
    return isinstance(value, str) and FEN.match(value) is not None


def checkedMove(payload):
    """The fields of a request about one move, or None. Nothing but these fields goes on to the prompt."""
    fen, played, history = payload.get("fen"), payload.get("played"), payload.get("history", [])
    best, reply = payload.get("best"), payload.get("reply")
    before, after, mark, loss = payload.get("before"), payload.get("after"), payload.get("mark"), payload.get("loss")
    if not (_fen(fen) and _san(played) and _san(best, True) and _san(reply, True)):
        return None
    if not (isinstance(history, list) and len(history) <= MAX_HISTORY and all(_san(m) for m in history)):
        return None
    if not (_number(before) and _number(after) and (mark is None or mark in MARKS)
            and (loss is None or _number(loss))):
        return None
    return {"fen": fen, "played": played, "history": history, "best": best, "reply": reply, "before": before,
            "after": after, "mark": mark, "loss": loss}


def checkedMistake(payload):
    """The fields of a request about one of the player's mistakes, or None."""
    fen, opponent, played, best = payload.get("fen"), payload.get("opponent"), payload.get("played"), payload.get("best")
    reply, score, after, loss = payload.get("reply"), payload.get("score"), payload.get("after"), payload.get("loss")
    if not (_fen(fen) and _san(opponent, True) and _san(played) and _san(best) and _san(reply, True)):
        return None
    if not (_number(score) and _number(after) and _number(loss)):
        return None
    return {"fen": fen, "opponent": opponent, "played": played, "best": best, "reply": reply, "score": score,
            "after": after, "loss": loss}


def checkedHint(payload):
    """The fields of a request for a strategic hint, or None."""
    fen, best, history = payload.get("fen"), payload.get("best"), payload.get("history", [])
    score = payload.get("score", 0.0)
    if not (_fen(fen) and _san(best)):
        return None
    if not (isinstance(history, list) and len(history) <= MAX_HISTORY and all(_san(m) for m in history)):
        return None
    if not _number(score):
        return None
    return {"fen": fen, "best": best, "history": history, "score": score}


MAX_OPTIONS = 4  # the alternatives Stockfish offers for the coach to choose from


def checkedPick(payload):
    """The fields of a request to pick one of Stockfish's alternatives, or None."""
    fen, best, history = payload.get("fen"), payload.get("best"), payload.get("history", [])
    score, options = payload.get("score", 0.0), payload.get("options")
    if not (_fen(fen) and _san(best) and _number(score)):
        return None
    if not (isinstance(history, list) and len(history) <= MAX_HISTORY and all(_san(m) for m in history)):
        return None
    if not (isinstance(options, list) and 1 <= len(options) <= MAX_OPTIONS):
        return None
    checked = []
    for option in options:
        if not (isinstance(option, dict) and _san(option.get("san")) and _number(option.get("score"))):
            return None
        checked.append({"san": option["san"], "score": option["score"]})
    return {"fen": fen, "best": best, "history": history, "score": score, "options": checked}


def checkedRequest(payload):
    """(kind, language, data) of a request that is chess data, or None. A request without a kind is a game's, in
    English: what an older page sends."""
    kind, lang = payload.get("kind", "game"), payload.get("lang", "en")
    if lang not in LANGUAGES:
        return None
    if kind == "game":
        data = checkedAnalysis(payload)
    elif kind == "move":
        data = checkedMove(payload)
    elif kind == "mistake":
        data = checkedMistake(payload)
    elif kind == "hint":
        data = checkedHint(payload)
    elif kind == "pick":
        data = checkedPick(payload)
    else:
        return None
    return None if data is None else (kind, lang, data)


def tooMany(visitor, now, limit=LIMIT_REQUESTS):
    """0 when the visitor may ask now (and counts the request), else the seconds until they may ask again."""
    with visitsLock:
        recent = [t for t in visits.get(visitor, []) if now - t < LIMIT_SECONDS]
        if len(recent) >= limit:
            visits[visitor] = recent
            return max(1, math.ceil(recent[len(recent) - limit] + LIMIT_SECONDS - now))
        recent.append(now)
        visits[visitor] = recent
        if len(visits) > 5000:  # forget visitors who haven't come for a while
            for key in [k for k, v in visits.items() if not v or now - v[-1] >= LIMIT_SECONDS]:
                del visits[key]
        return 0


def _parseTime(value):
    """A timestamp from the database (ISO 8601, any number of digits after the second's point), or None."""
    if not isinstance(value, str) or not value:
        return None
    value = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], value.replace("Z", "+00:00"))
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _lookUpPremium(token):
    """The id of the Premium player this access token signs in, or None: no account service configured, a token
    that doesn't sign in, no Premium, or the service unreachable (the visitor's own limit applies then)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        user = requests.get(url + "/auth/v1/user", headers={"apikey": key, "Authorization": "Bearer " + token},
                            timeout=5)
        if user.status_code != 200:
            return None
        userId = user.json().get("id")
        if not isinstance(userId, str) or not userId:
            return None
        rows = requests.get(url + "/rest/v1/profiles", params={"id": "eq." + userId, "select": "*"},
                            headers={"apikey": key, "Authorization": "Bearer " + key}, timeout=5)
        if rows.status_code != 200 or not isinstance(rows.json(), list) or not rows.json():
            return None
        profile = rows.json()[0]
    except (requests.exceptions.RequestException, ValueError, AttributeError):
        return None
    until = _parseTime(profile.get("premium_until"))
    admin = str(profile.get("username") or "").lower() in ADMIN_USERNAMES
    return userId if admin or (until is not None and until > datetime.now(timezone.utc)) else None


def premiumPlayer(token, now):
    """The id of the Premium player whose access token was sent with a request, or None (see _lookUpPremium)."""
    if not isinstance(token, str) or not token or len(token) > 4096:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with premiumLock:
        known = premiumCache.get(digest)
    if known is not None and now - known[0] < PREMIUM_CACHE_SECONDS:
        return known[1]
    player = _lookUpPremium(token)
    with premiumLock:
        if len(premiumCache) > 2000:  # forget tokens checked a while ago
            for key in [k for k, v in premiumCache.items() if now - v[0] >= PREMIUM_CACHE_SECONDS]:
                del premiumCache[key]
        premiumCache[digest] = (now, player)
    return player


def visitorOf(req):
    forwarded = req.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or req.remote_addr or "?"


@app.route("/api/llm", methods=["POST", "OPTIONS"])
def coach():
    if request.method == "OPTIONS":
        return "", 204, {"Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type",
                         "Access-Control-Max-Age": "86400"}
    payload = request.get_json(silent=True)
    checked = checkedRequest(payload) if isinstance(payload, dict) else None
    if checked is None:
        return jsonify(error="Invalid coaching request"), 400
    kind, lang, data = checked
    chosen = coach_module.providers() if coach_module is not None else []
    if not chosen:
        return jsonify(error="Browser coaching is not configured"), 503
    now = time.time()
    player = premiumPlayer(payload.get("token"), now)
    wait = tooMany("premium:" + player, now, PREMIUM_LIMIT_REQUESTS) if player else tooMany(visitorOf(request), now)
    if wait:
        return jsonify(error="Too many coaching requests, try again later"), 429, {"Retry-After": str(wait)}
    prompt = coach_module.prompt_for(kind, data, lang)
    tokens = coach_module.max_tokens(kind, lang)
    try:
        # the providers are asked in turn: the next at once when one fails or answers 429, or when one is slow
        text = coach_module.ask_in_order(chosen, lambda p: askProvider(p, prompt, tokens), timeout=20)
    except coach_module.LLMError as e:
        print("[llm] %s" % e)
        return jsonify(error="The coaching service returned an error"), 502
    return jsonify(text=text)
