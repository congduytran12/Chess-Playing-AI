# Saving and loading games in PGN (Portable Game Notation), the standard chess game file format

import os
import re
import sys
import json

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

SAVE_FOLDER = "saved_games"  # used on desktop when no file dialog is available
RESULTS = ('1-0', '0-1', '1/2-1/2', '*')

# browser helpers: download a text file, and let the user pick one (read back by polling)
JS_HELPERS = '''
    window.chessDownloadText = function(name, text) {
        const blob = new Blob([text], {type: "application/x-chess-pgn"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    window.__chessPickedText = "";
    window.chessPickTextFile = function() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".pgn,.txt,text/plain";
        input.onchange = () => {
            const file = input.files[0];
            if (file) file.text().then(t => { window.__chessPickedText = t; });
        };
        input.click();
    }

    window.chessTakePickedText = function() {
        const t = window.__chessPickedText;
        window.__chessPickedText = "";
        return t;
    }
'''
_jsReady = False
_loadedText = None  # desktop: text of a file picked by the user, waiting to be taken


def _ensureJs():
    global _jsReady
    if not _jsReady:
        js.eval(JS_HELPERS)
        _jsReady = True


def buildPgn(moveLog, headers, result):
    lines = ['[%s "%s"]' % (key, str(value).replace('\\', '\\\\').replace('"', '\\"'))
             for key, value in headers]
    tokens = []
    for i, move in enumerate(moveLog):
        if i % 2 == 0:
            tokens.append(str(i // 2 + 1) + ".")
        tokens.append(move.san or str(move))
    tokens.append(result)

    # move text is wrapped at 80 columns, as the PGN standard recommends
    moveLines = [""]
    for token in tokens:
        if moveLines[-1] and len(moveLines[-1]) + 1 + len(token) > 80:
            moveLines.append("")
        moveLines[-1] = (moveLines[-1] + " " + token).strip()
    return "\n".join(lines) + "\n\n" + "\n".join(moveLines) + "\n"


# returns (headers, moves) of the first game in the text, moves being algebraic notation strings
def parsePgn(text):
    headers = {}
    bodyLines = []
    inHeader = True
    for line in text.replace('\r', '').lstrip('﻿').split('\n'):
        stripped = line.strip()
        if inHeader and stripped.startswith('['):
            match = re.match(r'\[(\w+)\s+"(.*)"\]', stripped)
            if match:
                headers[match.group(1)] = match.group(2).replace('\\"', '"').replace('\\\\', '\\')
            continue
        if stripped:
            inHeader = False
        if not inHeader and stripped.startswith('[Event '):
            break  # the next game starts
        bodyLines.append(line)

    body = "\n".join(bodyLines)
    body = re.sub(r'\{[^}]*\}', ' ', body)  # {comments}
    body = re.sub(r';[^\n]*', ' ', body)  # ; comments to end of line
    previous = None
    while previous != body:  # (variations), which can be nested
        previous = body
        body = re.sub(r'\([^()]*\)', ' ', body)
    body = re.sub(r'\$\d+', ' ', body)  # numeric annotation glyphs

    moves = []
    for token in body.split():
        if token in RESULTS:
            break
        token = re.sub(r'^\d+\.+', '', token)  # move numbers, "12." or "12..."
        if token:
            moves.append(token)
    return headers, moves


# saves the text as a file; returns a short status message for the player
def savePgn(text, fileName):
    if WASM:
        if js is None:
            return "Saving isn't available here"
        _ensureJs()
        js.eval("window.chessDownloadText(%s, %s)" % (json.dumps(fileName), json.dumps(text)))
        return "Downloaded " + fileName

    path = None
    if sys.platform != 'darwin':  # Tk dialogs can crash next to SDL on macOS
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.asksaveasfilename(
                defaultextension=".pgn", initialfile=fileName,
                filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")])
            root.destroy()
            if not path:
                return "Save cancelled"
        except Exception:
            path = None
    if path is None:
        os.makedirs(SAVE_FOLDER, exist_ok=True)
        path = os.path.join(SAVE_FOLDER, fileName)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        return "Couldn't save: " + str(e)
    return "Saved " + os.path.basename(path)


# asks the player for a PGN file; the text arrives later through takeLoadedPgn()
# returns a status message, or None when there is nothing to report yet
def requestPgnLoad():
    global _loadedText
    if WASM:
        if js is None:
            return "Loading isn't available here"
        _ensureJs()
        js.eval("window.chessPickTextFile()")
        return None

    path = None
    if sys.platform != 'darwin':
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askopenfilename(
                filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")])
            root.destroy()
            if not path:
                return "Load cancelled"
        except Exception:
            path = None
    if path is None:
        # no dialog available: load the newest game in the save folder
        files = []
        if os.path.isdir(SAVE_FOLDER):
            files = [os.path.join(SAVE_FOLDER, name) for name in os.listdir(SAVE_FOLDER)
                     if name.lower().endswith(".pgn")]
        if not files:
            return "No saved games in " + SAVE_FOLDER
        path = max(files, key=os.path.getmtime)
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:  # -sig drops a byte order mark (Notepad)
            _loadedText = f.read()
    except OSError as e:
        return "Couldn't open: " + str(e)
    return None


def takeLoadedPgn():
    global _loadedText
    if WASM:
        if js is None or not _jsReady:
            return None
        try:
            text = js.eval("window.chessTakePickedText()")
        except Exception:
            return None
        return str(text) if text else None
    text, _loadedText = _loadedText, None
    return text
