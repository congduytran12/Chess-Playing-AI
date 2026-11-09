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
SAN = re.compile(r"^[A-Za-z0-9+#=\-]{1,12}$")
RESULT = re.compile(r"^[A-Za-z0-9 ,.()'/\-]{0,60}$")
MARKS = ("??", "?", "?!")
MAX_NUMBER = 1000000
# a request limit per visitor, best effort: it is kept in memory, so every serverless instance counts on its own
LIMIT_REQUESTS = 12
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
    analysis = checkedAnalysis(payload) if isinstance(payload, dict) else None
    if analysis is None:
        return jsonify(error="Invalid coaching request"), 400
    key = os.environ.get("GROQ_API_KEY")
    if not key or coach_module is None:
        return jsonify(error="Browser coaching is not configured"), 503
    if tooMany(visitorOf(request), time.time()):
        return jsonify(error="Too many coaching requests, try again later"), 429
    prompt = coach_module._prompt(*analysis)
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    url = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    try:
        response = requests.post(url, headers={"Authorization": "Bearer " + key}, json={
            "model": model,
            "temperature": 0.2,
            "max_completion_tokens": 180,
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
