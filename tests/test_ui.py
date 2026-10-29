# Runs the real game loop without a window: scripted clicks and keys, checked against the drawn screen
import asyncio
import os
import tempfile
import unittest

import support

try:
    import pygame as p
except ImportError:
    p = None


@unittest.skipIf(p is None, "needs pygame")
class GameLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # assets load by relative path, and nothing may touch the real sign-in, session or hint files
        cls.cwd = os.getcwd()
        os.chdir(support.GAME)
        cls.folder = tempfile.TemporaryDirectory()
        import account
        import hints
        import network
        import settings
        cls.files = [(account, 'STORAGE_FILE'), (hints, 'STORAGE_FILE'), (network, 'SESSION_FILE'),
                     (settings, 'STORAGE_FILE')]
        cls.saved = [getattr(module, name) for module, name in cls.files]
        for module, name in cls.files:
            setattr(module, name, os.path.join(cls.folder.name, module.__name__ + '.json'))
        hints._saved = None
        settings._values = None
        cls.settings = settings
        import main
        cls.main = main
        cls.mouse = [(0, 0)]
        cls.realGetPos = p.mouse.get_pos
        p.mouse.get_pos = lambda: cls.mouse[0]  # the game reads the mouse position, not the event's

    @classmethod
    def tearDownClass(cls):
        p.mouse.get_pos = cls.realGetPos
        for (module, name), value in zip(cls.files, cls.saved):
            setattr(module, name, value)
        os.chdir(cls.cwd)
        cls.folder.cleanup()

    def square(self, row, col):
        return (col * self.main.SQ_SIZE + self.main.SQ_SIZE // 2, row * self.main.SQ_SIZE + self.main.SQ_SIZE // 2)

    async def click(self, pos, wait=0.3):
        self.mouse[0] = pos
        p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=pos))
        await asyncio.sleep(wait)

    async def move(self, start, end, wait=0.5):
        await self.click(self.square(*start), 0.1)
        await self.click(self.square(*end), wait)

    def pixel(self, row, col):
        """Color near the top-left corner of a square, clear of the piece drawn on it."""
        return tuple(p.display.get_surface().get_at((col * self.main.SQ_SIZE + 6, row * self.main.SQ_SIZE + 6)))[:3]

    def test_fools_mate_and_the_result_card(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[1].center, 0.5)
            for start, end in (((6, 5), (5, 5)), ((1, 4), (3, 4)), ((6, 6), (4, 6)), ((0, 3), (4, 7))):
                await self.move(start, end)
            await asyncio.sleep(0.5)
            seen['king square'] = self.pixel(7, 4)
            seen['card'] = self.pixel(4, 2)  # c4, under the result card
            await self.click(self.square(0, 0))  # beside the card: hides it
            seen['card hidden'] = self.pixel(4, 2)
            await self.click(self.square(0, 0))  # and back
            seen['card back'] = self.pixel(4, 2)
            newGame = main.resultCardLayout("Black wins by checkmate", ['new'])[2]['new']
            await self.click(newGame.center, 0.5)
            seen['after new game'] = (self.pixel(7, 4), self.pixel(4, 2))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        red, green, blue = seen['king square']
        self.assertGreater(red, 150, "the mated king's square should be red")
        self.assertLess(green, 100)
        light, dark = tuple(main.BOARD_COLORS[0]), tuple(main.BOARD_COLORS[1])
        self.assertLess(max(seen['card']), 100, "the result card should cover the board")
        self.assertEqual(seen['card hidden'], light)
        self.assertLess(max(seen['card back']), 100)
        self.assertEqual(seen['after new game'], (dark, light), "a new game: e1 no longer red, no card")

    def test_presence_status(self):
        status = self.main.presenceStatus
        self.assertTrue(status('host', None, 500, 'SYNC HEALTHY')[0].startswith("Waiting for your opponent"))
        self.assertTrue(status('client', None, 500, 'SYNC HEALTHY')[0].startswith("Waiting for the host"))
        self.assertEqual(status('host', 470, 500, 'SYNC HEALTHY')[:2], ("Opponent connected", "darkgreen"))
        self.assertIsNone(status('host', 470, 500, 'SYNC HEALTHY')[2])
        gone = status('client', 100, 100 + 3 * 60 + 5, 'SYNC HEALTHY')
        self.assertIn("3 min", gone[0])
        self.assertEqual(gone[2], "may have left")
        self.assertTrue(status('host', 470, 500, 'RETRYING')[0].startswith("Connecting"))

    def test_resign_and_restart_ask_first(self):
        main = self.main
        seen = {}
        _, yes, no = main.promptRects()

        async def key(k, text):
            p.event.post(p.event.Event(p.KEYDOWN, key=k, unicode=text, mod=0, scancode=0))
            await asyncio.sleep(0.3)

        async def script():
            await asyncio.sleep(1.0)
            await self.move((6, 4), (4, 4), 2.5)  # 1.e4 and the computer's reply
            resign = main.panelLayout(0, False)['resign'].center
            await self.click(resign)
            await self.click(no.center)
            seen['after cancel'] = self.pixel(4, 2)  # c4: empty, under the result card once the game ends
            await key(p.K_r, 'r')
            await self.click(no.center)
            seen['after restart cancelled'] = self.pixel(4, 2)
            await self.click(resign)
            await self.click(yes.center, 0.5)
            seen['after resigning'] = self.pixel(4, 2)
            await key(p.K_r, 'r')  # the game is over: a new one starts without asking
            seen['after r'] = self.pixel(4, 2)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        light = tuple(main.BOARD_COLORS[0])
        self.assertEqual(seen['after cancel'], light)
        self.assertEqual(seen['after restart cancelled'], light)
        self.assertLess(max(seen['after resigning']), 100, "the result card should cover the board")
        self.assertEqual(seen['after r'], light)

    def test_settings_change_the_board_and_are_remembered(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            seen['before'] = self.pixel(4, 2)
            await self.click(main.panelLayout(0, False)['settings'].center)
            rects = main.settingsLayout()
            await self.click(rects['board:Brown'].center)
            await self.click(rects['pieces:Classic'].center)
            await self.click(rects['close'].center)
            seen['after'] = self.pixel(4, 2)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        try:
            asyncio.run(run())
            self.assertEqual(seen['before'], tuple(main.BOARD_THEMES['Green'][0]))
            self.assertEqual(seen['after'], tuple(main.BOARD_THEMES['Brown'][0]))
            self.settings._values = None  # read back from the file, as on the next start
            self.assertEqual((self.settings.get('board'), self.settings.get('pieces')), ('Brown', 'Classic'))
        finally:
            self.settings.put('board', 'Green')
            self.settings.put('pieces', 'Modern')
            main.setBoardTheme('Green')
            main.loadImages('Modern')

    def test_help_window_navigation(self):
        main = self.main
        rects = main.helpLayout()
        last = len(main.HELP_PAGES) - 1
        self.assertEqual(main.helpClick(0, rects['next'].center), 1)
        self.assertEqual(main.helpClick(0, rects['prev'].center), 0)
        self.assertEqual(main.helpClick(last, rects['next'].center), last)
        self.assertIsNone(main.helpClick(2, rects['close'].center))
        self.assertIsNone(main.helpKey(1, p.K_ESCAPE))
        self.assertEqual(main.helpKey(1, p.K_RIGHT), 2)

    def test_help_pages_fit_above_their_buttons(self):
        main = self.main
        box, buttonsTop = main.ACCOUNT_BOX, main.helpLayout()['prev'].y
        x, width = box.x + 40, box.width - 80
        font = main.get_font(17, False)
        for title, items in main.HELP_PAGES:
            y = box.y + 82
            for icon, heading, text in items:
                textX = x + (main.HELP_ICON_SIZE + 12 if icon else 0)
                top = y
                y += 24 + 20 * len(main.wrapText(text, font, x + width - textX))
                y = max(y, top + (main.HELP_ICON_SIZE if icon else 0)) + 12
            self.assertLessEqual(y - 12, buttonsTop - 6, title)

    def test_promotion_picker(self):
        main = self.main
        screen = p.display.get_surface()
        main.loadImages()

        async def pick(color, row, col, flip, clickAt):
            async def clicker():
                await asyncio.sleep(0.1)
                if clickAt == 'escape':
                    p.event.post(p.event.Event(p.KEYDOWN, key=p.K_ESCAPE, unicode='', mod=0, scancode=0))
                else:
                    await self.click(clickAt, 0)
            choice, _ = await asyncio.gather(main.pawnPromotionPopup(screen, color, row, col, flip), clicker())
            return choice

        SQ = main.SQ_SIZE
        # White promoting on c8: queen, rook, bishop, knight from the top of the c-file down
        self.assertEqual(asyncio.run(pick('w', 0, 2, False, (2 * SQ + 5, 1 * SQ + 5))), 'R')
        # Black promoting on f1 with Black at the bottom: f1 is drawn at the top, third column
        self.assertEqual(asyncio.run(pick('b', 7, 5, True, (2 * SQ + 5, 3 * SQ + 5))), 'N')
        self.assertIsNone(asyncio.run(pick('w', 0, 2, False, (600, 600))))
        self.assertIsNone(asyncio.run(pick('w', 0, 2, False, 'escape')))


if __name__ == '__main__':
    unittest.main()
