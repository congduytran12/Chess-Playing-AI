# game/textfield.py: editing a one-line text field (no window needed: a stand-in font measures the text)
import unittest

import support  # noqa: F401 (puts game/ on the path)

try:
    import pygame as p
    from textfield import TextField, PASSWORD_MASK
except ImportError:
    p = None


class Font:
    """Every character 10 px wide."""

    def size(self, text):
        return (10 * len(text), 20)


def keyEvent(key, text="", mod=0):
    return p.event.Event(p.KEYDOWN, key=key, unicode=text, mod=mod, scancode=0)


@unittest.skipIf(p is None, "needs pygame")
class TextFieldTest(unittest.TestCase):
    def test_caret_moves_within_the_text(self):
        field = TextField("chess")
        self.assertEqual(field.caret, 5, "a new value puts the caret at its end")
        field.left()
        field.left()
        self.assertEqual(field.caret, 3)
        field.home()
        field.left()
        self.assertEqual(field.caret, 0)
        field.end()
        field.right()
        self.assertEqual(field.caret, 5)

    def test_insert_backspace_and_delete_at_the_caret(self):
        field = TextField("chss")
        field.moveCaret(2)
        field.insert("e")
        self.assertEqual((field.value, field.caret), ("chess", 3))
        field.backspace()
        self.assertEqual((field.value, field.caret), ("chss", 2))
        field.delete()
        self.assertEqual((field.value, field.caret), ("chs", 2))
        field.home()
        field.backspace()  # nothing before the caret
        field.end()
        field.delete()  # nothing after it
        self.assertEqual(field.value, "chs")

    def test_max_length_allowed_characters_and_transform(self):
        field = TextField(maxLength=6, allowed="ABC123", transform=str.upper)
        self.assertEqual(field.insert("a1-b2 c3d"), "A1B2C3", "lowercase goes in as uppercase; the rest is dropped")
        self.assertEqual(field.insert("a"), "", "full")
        field.moveCaret(2)
        field.backspace()
        field.insert("cc")
        self.assertEqual(field.value, "ACB2C3", "only what fits goes in")
        self.assertEqual(TextField("x\ny\tz").value, "xyz", "no line breaks or tabs in a one-line field")

    def test_keys(self):
        field = TextField()
        for ch in "kngiht":
            field.handleKey(keyEvent(ord(ch), ch))
        for key in (p.K_LEFT, p.K_LEFT, p.K_LEFT, p.K_BACKSPACE, p.K_BACKSPACE, p.K_DELETE):
            field.handleKey(keyEvent(key))
        self.assertEqual((field.value, field.caret), ("kht", 1))
        field.handleKey(keyEvent(ord('n'), 'n'))
        field.handleKey(keyEvent(ord('i'), 'i'))
        field.handleKey(keyEvent(ord('g'), 'g'))
        self.assertEqual(field.value, "knight")
        field.handleKey(keyEvent(p.K_HOME))
        self.assertEqual(field.caret, 0)
        field.handleKey(keyEvent(p.K_END))
        self.assertEqual(field.caret, 6)
        field.handleKey(keyEvent(ord('a'), 'a', p.KMOD_CTRL))
        self.assertEqual(field.value, "knight", "a Ctrl shortcut types nothing")
        self.assertFalse(field.handleKey(keyEvent(p.K_F5)), "keys a field doesn't use are left for the game")

    def test_paste_with_ctrl_or_cmd_v(self):
        field = TextField("ab")
        field.moveCaret(1)
        field.handleKey(keyEvent(p.K_v, "\x16", p.KMOD_LCTRL), clipboard=lambda: "XY")
        self.assertEqual((field.value, field.caret), ("aXYb", 3))
        field.handleKey(keyEvent(p.K_v, "v", p.KMOD_LMETA), clipboard=lambda: "1\n2")  # Cmd+V on a Mac
        self.assertEqual(field.value, "aXY1 2b", "a pasted line break becomes a space")
        field.handleKey(keyEvent(p.K_v, "\x16", p.KMOD_CTRL), clipboard=lambda: "")
        field.handleKey(keyEvent(p.K_v, "\x16", p.KMOD_CTRL))  # no clipboard (the browser pastes another way)
        self.assertEqual(field.value, "aXY1 2b")
        replaced = TextField(onPaste=lambda f, text: f.setValue(text[::-1]))
        replaced.paste("abc")
        self.assertEqual(replaced.value, "cba", "onPaste decides what a paste does")

    def test_caret_from_a_click(self):
        field = TextField("rook")
        field.setCaretFromX(Font(), 14, 0)
        self.assertEqual(field.caret, 1, "the nearest boundary")
        field.setCaretFromX(Font(), 16, 0)
        self.assertEqual(field.caret, 2)
        field.setCaretFromX(Font(), -5, 0)
        self.assertEqual(field.caret, 0)
        field.setCaretFromX(Font(), 300, 0)
        self.assertEqual(field.caret, 4)
        field.setCaretFromX(Font(), 4, 20)  # scrolled 20 px: x 4 is the text's x 24
        self.assertEqual(field.caret, 2)

    def test_scrolling_keeps_the_caret_in_view(self):
        field = TextField("a" * 30)  # 300 px of text in a 100 px field
        self.assertEqual(field.scrollFor(Font(), 100), 202, "the end in view")
        field.home()
        self.assertEqual(field.scrollFor(Font(), 100), 0)
        field.moveCaret(12)
        self.assertEqual(field.scrollFor(Font(), 100), 22, "scrolled just enough")
        field.moveCaret(10)
        self.assertEqual(field.scrollFor(Font(), 100), 22, "still in view: no jump")
        field.setValue("abc")
        self.assertEqual(field.scrollFor(Font(), 100), 0, "short text isn't scrolled")

    def test_password_masking(self):
        field = TextField("secret", password=True)
        self.assertEqual(field.shown(), PASSWORD_MASK * 6)
        self.assertEqual(field.shown(showPassword=True), "secret")
        self.assertEqual(TextField("plain").shown(), "plain")
        field.moveCaret(2)
        self.assertEqual(field.caretX(Font()), 20)


if __name__ == '__main__':
    unittest.main()
