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
    // pasted text arrives as an event (a game can't read the clipboard on its own), so it's kept for polling
    window.__chessPasted = null;
    if (!window.__chessPasteListener) {
        window.__chessPasteListener = true;
        document.addEventListener('paste', function(e) {
            const text = e.clipboardData ? e.clipboardData.getData('text') : '';
            if (text) window.__chessPasted = text;
        });
    }
    window.chessTakePasted = function() {
        const text = window.__chessPasted;
        window.__chessPasted = null;
        return text === null ? '' : text;
    }

    // copying needs a user action in some browsers; the old execCommand way is the fallback
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
            navigator.clipboard.writeText(text).catch(fallback);
            return 1;
        }
        return fallback() ? 1 : 0;
    }
'''
_jsReady = False


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

def pageHidden():
    """The browser tab is in the background (desktop: False; the game listens for window focus there)."""
    return bool(_eval("document.hidden ? 1 : 0", 0))


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
    """Puts text on the clipboard; returns whether that (probably) worked."""
    text = str(text)
    if inBrowser():
        return bool(_eval("window.chessCopyText(%s)" % json.dumps(text), 0))
    if WASM:
        return False
    return _scrapCopy(text) or _tkCopy(text)


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
