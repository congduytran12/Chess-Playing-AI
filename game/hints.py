# Hints are limited to HINTS_PER_DAY a day. They are counted on this device (browser localStorage, or a file
# in the home folder on desktop) and the count starts over at local midnight.

import os
import sys
import json
import time

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

HINTS_PER_DAY = 5
STORAGE_KEY = "chess_ai_hints"
STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".chess-playing-ai-hints.json")  # desktop only

_saved = None  # {'day': 'YYYY-MM-DD', 'used': count}, read from storage once


def _today():
    return time.strftime("%Y-%m-%d")


def _usedToday():
    global _saved
    if _saved is None:
        _saved = _load()
    if _saved.get('day') != _today():
        return 0
    try:
        return max(0, int(_saved.get('used', 0)))
    except (TypeError, ValueError):
        return 0


def remaining():
    """Hints left today."""
    return max(0, HINTS_PER_DAY - _usedToday())


def use():
    """Counts one hint shown."""
    global _saved
    _saved = {'day': _today(), 'used': _usedToday() + 1}
    _store(_saved)


def _load():
    try:
        if WASM:
            data = js.eval("localStorage.getItem(%s) || ''" % json.dumps(STORAGE_KEY)) if js is not None else ""
        elif os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE) as f:
                data = f.read()
        else:
            data = ""
        saved = json.loads(str(data)) if data else {}
    except Exception as e:
        print("Hints: could not read the hint count -", e)
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _store(saved):
    data = json.dumps(saved)
    try:
        if WASM:
            if js is not None:
                js.eval("localStorage.setItem(%s, %s)" % (json.dumps(STORAGE_KEY), json.dumps(data)))
        else:
            with open(STORAGE_FILE, "w") as f:
                f.write(data)
    except Exception as e:
        print("Hints: could not save the hint count -", e)
