"""Server-side proxy for the browser's optional Groq chess coach.

The browser sends the game's analysis (moves, best moves, evaluations, marks, result), never a prompt: the prompt is
built here, by game/llm.py's own _prompt, from data checked to be chess data. So the endpoint can't be used as a
general chatbot with the project's key, whatever is posted to it.
"""

import importlib.util
import math
import os
import re
import threading
import time

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

MAX_PLIES = 1000  # more than any game worth explaining (an analysis lists one more position than moves)
MOVE_CODE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
# a move in algebraic notation (Nf3, exd5, Qh4xe1+, e8=Q#, O-O-O): no other text gets through as a "move"
SAN = re.compile(r"^(?:O-O(?:-O)?|(?:[a-h]x)?[a-h][1-8](?:=[QRBN])?|[KQRBN][a-h]?[1-8]?x?[a-h][1-8])[+#]?$")
# a position: pieces, side to move, castling rights, en passant square, move counters
FEN = re.compile(r"^[pnbrqkPNBRQK1-8/]{15,71} [wb] (?:-|[KQkq]{1,4}) (?:-|[a-h][36]) \d{1,3} \d{1,4}$")
RESULT = re.compile(r"^[A-Za-z0-9 ,.()'/\-]{0,60}$")
MARKS = ("??", "?", "?!")
LANGUAGES = ("en", "vi")  # the languages the coach answers in (game/llm.py LANGUAGES)
MAX_HISTORY = 12  # moves before the explained one
MAX_NUMBER = 1000000
# a request limit per visitor, best effort: it is kept in memory, so every serverless instance counts on its own.
# Explaining single moves is a request each, so the limit is roomier than a game summary alone would need
LIMIT_REQUESTS = 30
LIMIT_SECONDS = 600
visits = {}
visitsLock = threading.Lock()


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
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return (content or "").strip() if isinstance(content, str) else ""


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
    if not isinstance(result, str) or not RESULT.match(result):
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
    else:
        return None
    return None if data is None else (kind, lang, data)


def tooMany(visitor, now):
    with visitsLock:
        recent = [t for t in visits.get(visitor, []) if now - t < LIMIT_SECONDS]
        if len(recent) >= LIMIT_REQUESTS:
            visits[visitor] = recent
            return True
        recent.append(now)
        visits[visitor] = recent
        if len(visits) > 5000:  # forget visitors who haven't come for a while
            for key in [k for k, v in visits.items() if not v or now - v[-1] >= LIMIT_SECONDS]:
                del visits[key]
        return False


def visitorOf(req):
    forwarded = req.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or req.remote_addr or "?"


@app.route("/api/llm", methods=["POST", "OPTIONS"])
def coach():
    if request.method == "OPTIONS":
        return "", 204
    payload = request.get_json(silent=True)
    checked = checkedRequest(payload) if isinstance(payload, dict) else None
    if checked is None:
        return jsonify(error="Invalid coaching request"), 400
    kind, lang, data = checked
    key = os.environ.get("GROQ_API_KEY")
    if not key or coach_module is None:
        return jsonify(error="Browser coaching is not configured"), 503
    if tooMany(visitorOf(request), time.time()):
        return jsonify(error="Too many coaching requests, try again later"), 429
    prompt = coach_module.prompt_for(kind, data, lang)
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    url = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    try:
        response = requests.post(url, headers={"Authorization": "Bearer " + key}, json={
            "model": model,
            "temperature": 0.2,
            "max_completion_tokens": coach_module.max_tokens(kind, lang),
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": "You explain chess analysis accurately and briefly."},
                {"role": "user", "content": prompt},
            ],
        }, timeout=20)
    except requests.RequestException:
        return jsonify(error="The coaching service could not be reached"), 502
    if response.status_code != 200:
        return jsonify(error="The coaching service returned an error"), 502
    try:
        data = response.json()
        text = _content_text(data["choices"][0]["message"].get("content"))
        if not text:
            raise ValueError("empty response")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return jsonify(error="The coaching service returned an invalid response"), 502
    return jsonify(text=text)
