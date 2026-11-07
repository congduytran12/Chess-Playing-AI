# Browser-only features (the page's address, the clipboard, whether the tab is hidden) with desktop fallbacks.
# Every function here returns a plain value and never raises, so the game loop can call them freely.

import sys
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

WASM = sys.platform == 'emscripten'
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

SITE_URL = "https://chess-playing-ai.vercel.app/"  # where the game is played in the browser

JS_HELPERS = r'''
    // pasted text is kept for the game to poll. The canvas's key handling cancels Ctrl+V's default action, so
    // the browser's own paste (the 'paste' event) doesn't happen there: Ctrl+V / Cmd+V asks the clipboard instead
    // (the browser may ask the player to allow it once). A paste event that does come wins over that answer.
    window.__chessPasted = null;
    window.__chessPasteEventAt = 0;
    if (!window.__chessPasteListener) {
        window.__chessPasteListener = true;
        document.addEventListener('paste', function(e) {
            if (window.chessKb && e.target === window.chessKb.input) return;  // the phone keyboard's input takes it
            const text = e.clipboardData ? e.clipboardData.getData('text') : '';
            if (text) {
                window.__chessPasted = text;
                window.__chessPasteEventAt = Date.now();
            }
        });
        window.addEventListener('keydown', function(e) {
            // the V key: by its letter, or by its place while the layout types another alphabet (Russian 'м')
            const vKey = e.key === 'v' || e.key === 'V' || (e.code === 'KeyV' && !/^[a-zA-Z]$/.test(e.key));
            if (!(e.ctrlKey || e.metaKey) || e.altKey || !vKey) return;
            if (window.chessKb && document.activeElement === window.chessKb.input) return;  // pastes into it itself
            if (!navigator.clipboard || !navigator.clipboard.readText) return;
            const asked = Date.now();
            navigator.clipboard.readText().then(function(text) {
                if (text && window.__chessPasteEventAt < asked) window.__chessPasted = text;
            }).catch(function() {});
        }, true);
    }
    window.chessTakePasted = function() {
        const text = window.__chessPasted;
        window.__chessPasted = null;
        return text === null ? '' : text;
    }

    // a phone's on-screen keyboard. The game draws its own text fields, so nothing on the page asks the phone for a
    // keyboard: an invisible <input> does. It has to take the focus inside the tap itself (iOS shows the keyboard
    // for nothing else), so the game publishes where its fields are (chessKbSync) and the page finds the tapped
    // one. What is typed goes back to the game, which polls it (chessKbTake) and cleans it like typed text.
    // rev counts what was typed; the game answers with ack, and the page takes the game's text back only once
    // the game has seen everything typed (or typing in between would be lost).
    if (!window.chessKb) {
        const kb = window.chessKb = {fields: {}, bound: null, rev: 0, pending: null, composing: false,
                                     frozenSize: '', thaw: 0, lastCaret: -1, input: null};
        const canvas = function() { return document.querySelector('canvas'); };
        const place = function(f) {  // the input lies over the field on the screen, where the phone looks for it
            const c = canvas();
            if (!c || !kb.input) return;
            const r = c.getBoundingClientRect(), sx = r.width / c.width, sy = r.height / c.height;
            const s = kb.input.style;
            s.left = (r.left + f.x * sx) + 'px';
            s.top = (r.top + f.y * sy) + 'px';
            s.width = Math.max(1, f.w * sx) + 'px';
            s.height = Math.max(1, f.h * sy) + 'px';
        };
        const report = function(extra) {
            const input = kb.input;
            kb.rev++;
            kb.lastCaret = input.selectionStart;
            kb.pending = Object.assign({id: kb.bound, value: input.value, caret: input.selectionStart}, extra || {});
        };
        const unbind = function() {
            if (kb.input) kb.input.blur();
            kb.bound = null;
            clearTimeout(kb.thaw);  // the window settles a moment after the keyboard goes
            kb.thaw = setTimeout(function() { if (!kb.bound) kb.frozenSize = ''; }, 600);
        };
        const ensureInput = function() {
            if (kb.input) return kb.input;
            const input = document.createElement('input');
            input.id = 'chess-kb-input';
            input.setAttribute('autocorrect', 'off');
            input.setAttribute('spellcheck', 'false');
            input.setAttribute('enterkeyhint', 'go');
            input.setAttribute('aria-hidden', 'true');
            input.tabIndex = -1;
            Object.assign(input.style, {position: 'fixed', left: '0', top: '0', width: '1px', height: '1px',
                opacity: '0', pointerEvents: 'none', border: '0', padding: '0', margin: '0', outline: 'none',
                fontSize: '16px', background: 'transparent', color: 'transparent', caretColor: 'transparent',
                zIndex: '-1'});  // 16px: iOS zooms the page in for smaller text
            input.addEventListener('input', function() { report(); });
            input.addEventListener('compositionstart', function() { kb.composing = true; });
            input.addEventListener('compositionend', function() { kb.composing = false; });
            // the game's own key handling (SDL, on the window) must not see these keys: it would type them into the
            // game's field as well, and it cancels the key's default, which is the text going into this input
            ['keydown', 'keyup', 'keypress'].forEach(function(type) {
                input.addEventListener(type, function(e) { e.stopPropagation(); });
            });
            input.addEventListener('keydown', function(e) {
                if (e.key !== 'Enter') return;
                e.preventDefault();
                report({enter: true});
                unbind();
            });
            input.addEventListener('blur', function() {
                if (kb.bound) unbind();
            });
            document.addEventListener('selectionchange', function() {  // the caret moved (an arrow key)
                if (document.activeElement === input && !kb.composing && input.selectionStart !== kb.lastCaret) {
                    report();
                }
            });
            document.body.appendChild(input);
            kb.input = input;
            return input;
        };
        document.addEventListener('touchend', function(e) {
            const c = canvas(), t = e.changedTouches && e.changedTouches[0];
            if (!c || !t) return;
            const r = c.getBoundingClientRect();
            const x = (t.clientX - r.left) * c.width / r.width, y = (t.clientY - r.top) * c.height / r.height;
            let found = null;
            for (const id in kb.fields) {
                const f = kb.fields[id];
                if (x >= f.x && x < f.x + f.w && y >= f.y && y < f.y + f.h) found = id;
            }
            if (!found) {
                if (kb.bound) unbind();  // a tap anywhere else puts the keyboard away
                return;
            }
            const f = kb.fields[found], input = ensureInput();
            if (!kb.frozenSize) kb.frozenSize = window.innerWidth + 'x' + window.innerHeight;
            clearTimeout(kb.thaw);
            kb.bound = found;
            input.type = f.type;
            input.setAttribute('inputmode', f.mode);
            input.setAttribute('autocapitalize', f.caps);
            input.setAttribute('autocomplete', f.auto);
            input.maxLength = f.max;
            input.value = f.value;
            place(f);
            input.focus();  // inside the tap: this is what makes the phone show its keyboard
            try { input.setSelectionRange(f.caret, f.caret); } catch (err) {}
            kb.lastCaret = f.caret;
        }, {capture: true, passive: true});
        window.chessKbSync = function(text) {
            const state = JSON.parse(text);
            kb.fields = state.fields;
            if (!kb.bound || !kb.input) return;
            const f = kb.fields[kb.bound];
            if (!f) { unbind(); return; }
            place(f);
            if (kb.input.type !== f.type) kb.input.type = f.type;
            if (state.ack === kb.rev && !kb.composing) {
                if (kb.input.value !== f.value) kb.input.value = f.value;
                if (document.activeElement === kb.input && kb.input.selectionStart !== f.caret) {
                    try { kb.input.setSelectionRange(f.caret, f.caret); } catch (err) {}
                    kb.lastCaret = f.caret;
                }
            }
        };
        window.chessKbTake = function() {
            if (!kb.pending) return '';
            const msg = kb.pending;
            msg.rev = kb.rev;
            kb.pending = null;
            return JSON.stringify(msg);
        };
        // the keyboard overlays the page (Chrome on Android) instead of shrinking it, which would shrink the game
        if (window.matchMedia && matchMedia('(pointer: coarse)').matches) {
            const meta = document.querySelector('meta[name=viewport]');
            if (meta && meta.content.indexOf('interactive-widget') < 0) {
                meta.content += ', interactive-widget=overlays-content';
            }
        }
    }

    // the canvas never overflows the window, not even for the moment between a phone turning and the page fitting
    // the canvas again: a phone's browser would zoom out to show the overflow and keep that zoom (the page's window
    // would then report the wrong size and the game would be cut off). The page's own fit stays within this anyway.
    if (!window.__chessCanvasGuard) {
        window.__chessCanvasGuard = true;
        const style = document.createElement('style');
        style.textContent = 'canvas.emscripten, canvas { max-width: 100vw; max-height: 100vh; touch-action: none; -webkit-touch-callout: none; }';
        document.head.appendChild(style);
    }

    // copying needs a user action in some browsers; the old execCommand way is the fallback. The clipboard's
    // answer comes later: 2 means wait for it, and window.__chessCopied becomes 'ok' or 'failed'
    window.__chessCopied = null;
    window.chessTakeCopied = function() {
        const result = window.__chessCopied;
        if (result) window.__chessCopied = null;
        return result || '';
    }
    window.chessCopyText = function(text) {
        function fallback() {
            const area = document.createElement('textarea');
            area.value = text;
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            let ok = false;
            try { ok = document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(area);
            return ok;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            window.__chessCopied = null;
            navigator.clipboard.writeText(text).then(function() {
                window.__chessCopied = 'ok';
            }).catch(function() {
                window.__chessCopied = fallback() ? 'ok' : 'failed';
            });
            return 2;
        }
        return fallback() ? 1 : 0;
    }
'''
_jsReady = False


def language():
    """The language the browser or the system is set to, as two lower-case letters ('vi', 'en'); '' when unknown."""
    value = _eval("navigator.language || ''", "") if inBrowser() else _systemLanguage()
    return str(value or '')[:2].lower()


def _systemLanguage():
    try:
        import os
        import locale
        if sys.platform == 'win32':
            import ctypes
            return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), '')
        return (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or '').split('.')[0]
    except Exception:
        return ''


def inBrowser():
    return WASM and js is not None


def _eval(code, default=None):
    """Runs JavaScript in the page (installing the helpers first); default when it fails or on desktop."""
    global _jsReady
    if not inBrowser():
        return default
    try:
        if not _jsReady:
            js.eval(JS_HELPERS)
            _jsReady = True
        return js.eval(code)
    except Exception as e:
        print("Browser: %s failed -" % code[:40], e)
        return default


# --- the page's address (pure parts first, so they can be tested anywhere)

def paramFromUrl(url, name):
    """The value of ?name=... in url, or None."""
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if key == name:
            return value
    return None


def urlWithoutParam(url, name):
    """url with ?name=... taken out (the other parameters and the #hash stay)."""
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != name]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def hashFromUrl(url):
    """The part after #, without the #."""
    return urlsplit(url).fragment


def urlWithoutHash(url):
    return url.split('#', 1)[0]


def siteFromUrl(url):
    """The page's address without its ?query and #hash: where a link to the game should point."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def _href():
    href = _eval("window.location.href", "")
    return str(href) if href else ""


def queryParam(name):
    """?name=... of the page's address; None on desktop or when it isn't there."""
    href = _href()
    return paramFromUrl(href, name) if href else None


def removeQueryParam(name):
    """Takes ?name=... out of the address bar without reloading (so a reload doesn't act on it again)."""
    href = _href()
    if href and paramFromUrl(href, name) is not None:
        _eval("history.replaceState(null, '', %s)" % json.dumps(urlWithoutParam(href, name)))


def locationHash():
    href = _href()
    return hashFromUrl(href) if href else ""


def clearLocationHash():
    href = _href()
    if href and '#' in href:
        _eval("history.replaceState(null, '', %s)" % json.dumps(urlWithoutHash(href)))


def siteUrl():
    """The game's address: this page in the browser, the public site on desktop."""
    href = _href()
    return siteFromUrl(href) if href else SITE_URL


# --- the tab and the window

_touch = None  # touchScreen()'s answer, asked once


def touchScreen():
    """The browser's main pointer is a finger (a phone or tablet), so texts say "tap"; False on desktop."""
    global _touch
    if _touch is None:
        _touch = bool(_eval("window.matchMedia && matchMedia('(pointer: coarse)').matches ? 1 : 0", 0))
    return _touch


def keyboardSync(state):
    """Publishes the game's text fields for a phone's on-screen keyboard: state is JSON text, {'fields': {id: {x,
    y, w, h (canvas px), type, mode, caps, auto, max, value, caret}}, 'ack': the last typing the game has seen}.
    The page focuses an invisible input when one of the fields is tapped (see JS_HELPERS)."""
    _eval("window.chessKbSync(%s)" % json.dumps(state))


def keyboardTake():
    """What was typed since the last call, as {'id', 'value', 'caret', 'rev', 'enter'?}, or None."""
    raw = str(_eval("window.chessKbTake()", "") or "")
    try:
        message = json.loads(raw) if raw else None
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def pageHidden():
    """The browser tab is in the background (desktop: False; the game listens for window focus there)."""
    return bool(_eval("document.hidden ? 1 : 0", 0))


def viewportSize():
    """The browser window's inside (width, height) in CSS px, which picks the game's layout; None on desktop."""
    # while the keyboard is up the size from before it came: a smaller window must not turn the game sideways
    size = _eval("(window.chessKb && window.chessKb.frozenSize) || (window.innerWidth + 'x' + window.innerHeight)", "")
    try:
        width, height = (int(float(part)) for part in str(size).split('x'))
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def setTitle(text):
    """The window's title, which is the tab's title in the browser."""
    try:
        import pygame
        pygame.display.set_caption(text)
    except Exception as e:
        print("Browser: could not set the title -", e)
    if inBrowser():  # pygbag may not pass the caption on to the page
        _eval("document.title = %s" % json.dumps(text))


# --- the clipboard

def copyText(text):
    """Puts text on the clipboard; returns whether that worked, or None in a browser that answers later: then
    copyResult() tells."""
    text = str(text)
    if inBrowser():
        result = _eval("window.chessCopyText(%s)" % json.dumps(text), 0)
        return None if result == 2 else bool(result)
    if WASM:
        return False
    return _scrapCopy(text) or _tkCopy(text)


def copyResult():
    """After copyText returned None: True or False once the browser has answered (once), None until then."""
    result = _eval("window.chessTakeCopied()", "") if inBrowser() else ""
    return {'ok': True, 'failed': False}.get(str(result) if result else "")


def takePastedText():
    """Text the player pasted (Ctrl+V) since the last call, or None. Browser only: on desktop use clipboardText()."""
    if not inBrowser():
        return None
    text = _eval("window.chessTakePasted()", "")
    return str(text) if text else None


def clipboardText():
    """The clipboard's text on desktop ('' when there is none, and always in the browser: see takePastedText)."""
    if WASM:
        return ""
    return _scrapPaste() or _tkPaste() or ""


def _scrapReady():
    import pygame
    if not pygame.display.get_init() or pygame.display.get_surface() is None:
        return None  # scrap needs the window
    if not pygame.scrap.get_init():
        pygame.scrap.init()
    return pygame


def _scrapCopy(text):
    try:
        pygame = _scrapReady()
        if pygame is None:
            return False
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode('utf-8'))
        return True
    except Exception:
        return False


def _scrapPaste():
    try:
        pygame = _scrapReady()
        if pygame is None:
            return ""
        data = pygame.scrap.get(pygame.SCRAP_TEXT)
        if not data:
            return ""
        if isinstance(data, bytes):
            data = data.decode('utf-8', errors='replace')
        return data.replace('\x00', '')  # Windows ends clipboard text with a null
    except Exception:
        return ""


def _tkCopy(text):
    if sys.platform == 'darwin':  # Tk next to SDL can crash on macOS
        return False
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # hands the text to the system before the window goes
        root.destroy()
        return True
    except Exception:
        return False


def _tkPaste():
    if sys.platform == 'darwin':
        return ""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            text = root.clipboard_get()
        except tk.TclError:  # nothing (or no text) on the clipboard
            text = ""
        root.destroy()
        return text
    except Exception:
        return ""
