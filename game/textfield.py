# A one-line text box's contents and editing: the text, the caret, and what may be typed into it.
# Drawing is in main.py (drawTextField), which owns the fonts and the theme's colors; this module only needs
# pygame's key constants and a font's size() to place the caret, so it can be tested on its own.

import pygame as p

PASSWORD_MASK = "•"  # a bullet per character of a hidden password


class TextField:
    """value: the text; caret: index in value where typing goes (0 .. len(value)).
    maxLength: longest value; allowed: the characters that may be typed (None: any printable one);
    transform: applied to typed or pasted text first (e.g. str.upper); password: shown masked;
    onPaste(field, text): replaces the plain insert for pasted text (e.g. picking a room code out of a link)."""

    def __init__(self, value="", maxLength=100, allowed=None, transform=None, password=False, onPaste=None):
        self.maxLength = maxLength
        self.allowed = allowed
        self.transform = transform
        self.password = password
        self.onPaste = onPaste
        self.value = ""
        self.caret = 0
        self.scroll = 0  # px of the text scrolled out at the left, so the caret stays in view (see scrollFor)
        self.edited = 0  # ticks of the last change or caret move: the caret shows steadily for a moment after it
        self.setValue(value)

    def __repr__(self):
        return "TextField(%r, caret=%d)" % (self.value, self.caret)

    def clean(self, text):
        """text as it may go in: transformed, without line breaks or characters that aren't allowed."""
        text = str(text or "")
        if self.transform is not None:
            text = self.transform(text)
        return "".join(ch for ch in text if ch.isprintable() and (self.allowed is None or ch in self.allowed))

    def setValue(self, text):
        self.value = self.clean(text)[:self.maxLength]
        self.caret = len(self.value)
        self.touch()

    def touch(self):
        try:
            self.edited = p.time.get_ticks()
        except Exception:  # pygame not initialised (a plain unit test)
            self.edited = 0

    def insert(self, text):
        """Types text at the caret; whatever doesn't fit in maxLength is left out. Returns what went in."""
        text = self.clean(text)[:max(0, self.maxLength - len(self.value))]
        self.value = self.value[:self.caret] + text + self.value[self.caret:]
        self.caret += len(text)
        self.touch()
        return text

    def paste(self, text):
        if self.onPaste is not None:
            self.onPaste(self, text)
        else:
            self.insert(" ".join(str(text or "").split()) if "\n" in str(text or "") else text)

    def backspace(self):
        if self.caret > 0:
            self.value = self.value[:self.caret - 1] + self.value[self.caret:]
            self.caret -= 1
        self.touch()

    def delete(self):
        self.value = self.value[:self.caret] + self.value[self.caret + 1:]
        self.touch()

    def moveCaret(self, index):
        self.caret = min(max(index, 0), len(self.value))
        self.touch()

    def left(self):
        self.moveCaret(self.caret - 1)

    def right(self):
        self.moveCaret(self.caret + 1)

    def home(self):
        self.moveCaret(0)

    def end(self):
        self.moveCaret(len(self.value))

    def shown(self, showPassword=False):
        """The text as drawn: a password is masked unless the player chose Show."""
        return PASSWORD_MASK * len(self.value) if self.password and not showPassword else self.value

    def caretX(self, font, showPassword=False):
        """px from the text's start to the caret."""
        return font.size(self.shown(showPassword)[:self.caret])[0]

    def setCaretFromX(self, font, x, scroll=None, showPassword=False):
        """Puts the caret at the character boundary nearest x (px from the left edge of the text area)."""
        scroll = self.scroll if scroll is None else scroll
        shown = self.shown(showPassword)
        target = x + scroll
        best, bestDistance = 0, abs(target)
        for i in range(1, len(shown) + 1):
            distance = abs(font.size(shown[:i])[0] - target)
            if distance < bestDistance:
                best, bestDistance = i, distance
        self.moveCaret(best)

    def scrollFor(self, font, width, showPassword=False):
        """Scrolls the text (self.scroll) as little as needed to keep the caret within width px; returns it."""
        caret = self.caretX(font, showPassword)
        full = font.size(self.shown(showPassword))[0]
        scroll = min(self.scroll, max(0, full - width + 2))  # no empty space at the right while text is hidden left
        if caret - scroll > width - 2:
            scroll = caret - width + 2
        if caret < scroll:
            scroll = caret
        self.scroll = max(0, scroll)
        return self.scroll

    def handleKey(self, event, clipboard=None):
        """Applies a KEYDOWN event: the arrows, Home/End, Backspace/Delete, typed text, and Ctrl+V / Cmd+V
        (clipboard: a function returning the clipboard's text). Returns whether the key was used."""
        key = event.key
        mods = getattr(event, 'mod', 0)
        # Ctrl or Cmd; Windows reports AltGr (which types '@' on many keyboards) as Ctrl+Alt, and that is typing
        command = (mods & p.KMOD_META) or ((mods & p.KMOD_CTRL) and not (mods & p.KMOD_ALT))
        if key == p.K_v and command:
            text = clipboard() if clipboard is not None else ""
            if text:
                self.paste(text)
            return True
        if key == p.K_LEFT:
            self.left()
        elif key == p.K_RIGHT:
            self.right()
        elif key in (p.K_HOME, p.K_UP):
            self.home()
        elif key in (p.K_END, p.K_DOWN):
            self.end()
        elif key == p.K_BACKSPACE:
            self.backspace()
        elif key == p.K_DELETE:
            self.delete()
        elif not command and getattr(event, 'unicode', "") and event.unicode.isprintable():
            self.insert(event.unicode)
        else:
            return False
        return True
