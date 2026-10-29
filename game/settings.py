# The player's preferences (board colors, piece style), kept on this device: browser localStorage, or a file
# in the home folder on desktop.

import os
import sys
import json

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

STORAGE_KEY = "chess_ai_settings"
STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".chess-playing-ai-settings.json")  # desktop only

_values = None  # read from storage once


def get(name, default=None):
    global _values
    if _values is None:
        _values = _load()
    return _values.get(name, default)


def put(name, value):
    get(name)  # makes sure the stored values are loaded first, so the others are kept
    _values[name] = value
    _store(_values)


def _load():
    try:
        if WASM:
            data = js.eval("localStorage.getItem(%s) || ''" % json.dumps(STORAGE_KEY)) if js is not None else ""
        elif os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE) as f:
                data = f.read()
        else:
            data = ""
        values = json.loads(str(data)) if data else {}
    except Exception as e:
        print("Settings: could not read the settings -", e)
        values = {}
    return values if isinstance(values, dict) else {}


def _store(values):
    data = json.dumps(values)
    try:
        if WASM:
            if js is not None:
                js.eval("localStorage.setItem(%s, %s)" % (json.dumps(STORAGE_KEY), json.dumps(data)))
        else:
            with open(STORAGE_FILE, "w") as f:
                f.write(data)
    except Exception as e:
        print("Settings: could not save the settings -", e)
