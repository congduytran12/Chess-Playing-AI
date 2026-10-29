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

    def menuItem(self, name, mode=0, connected=False, reviewing=False):
        """Rect of a menu item, with the menu opened from its button in that panel layout."""
        return self.main.menuItemRects(self.main.panelLayout(mode, connected, False, reviewing)['menu'])[name]

    async def openMenuItem(self, name, mode=0, connected=False, reviewing=False, wait=0.3):
        """Opens the menu and clicks one of its items."""
        await self.click(self.main.panelLayout(mode, connected, False, reviewing)['menu'].center, 0.2)
        await self.click(self.menuItem(name, mode, connected, reviewing).center, wait)

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
        self.assertEqual(status('host', 470, 500, 'SYNC HEALTHY')[:2], ("Opponent connected", 'success'))
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
            await self.openMenuItem('settings')
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

    def test_dark_theme_is_chosen_in_settings_and_remembered(self):
        main = self.main
        seen = {}
        panelPixel = (main.PANEL_X + 5, 200)  # side panel background, between the move log and the controls

        async def script():
            await asyncio.sleep(1.0)
            seen['light'] = tuple(p.display.get_surface().get_at(panelPixel))[:3]
            await self.openMenuItem('settings')
            await self.click(main.settingsLayout()['tab:game'].center)  # the theme is on the Game tab
            await self.click(main.settingsLayout('game')['uiTheme:dark'].center)
            await self.click(main.settingsLayout('game')['close'].center)
            seen['dark'] = tuple(p.display.get_surface().get_at(panelPixel))[:3]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        try:
            asyncio.run(run())
            self.assertEqual(seen['light'], tuple(main.PALETTES['light']['panel']))
            self.assertEqual(seen['dark'], tuple(main.PALETTES['dark']['panel']))
            self.settings._values = None  # read back from the file, as on the next start
            self.assertEqual(self.settings.get('uiTheme'), 'dark')
        finally:
            self.settings.put('uiTheme', 'light')
            main.setUiTheme('light')

    def test_set_ui_theme(self):
        main = self.main
        try:
            main.setUiTheme('dark')
            self.assertEqual(main.UI, main.PALETTES['dark'])
            main.setUiTheme('no such theme')  # an unknown saved name falls back to light
            self.assertEqual(main.UI, main.PALETTES['light'])
        finally:
            main.setUiTheme('light')
        self.assertEqual(set(main.PALETTES['light']), set(main.PALETTES['dark']), "both themes define every color")

    def test_even_labels_per_panel_row(self):
        main = self.main
        rows = main.panelRows(0, False)
        layout = main.panelLayout(0, False)
        labels = {'mode': "Mode: Local vs AI", 'level': "AI: Normal", 'side': "Play as: White", 'clock': "Clock: Off",
                  'hint': "Hint (5 left)", 'resign': "Resign", 'draw': "Offer Draw", 'undo': "Undo",
                  'restart': "Restart", 'account': "Sign in", 'menu': ""}
        sizes = main.evenLabelSizes(rows, layout, labels)
        self.assertEqual(set(sizes), set(layout))
        for row in rows:
            self.assertEqual(len({sizes[name] for name in row}), 1, row)
            for name in row:  # every label of the row fits its button at the row's size
                width = main.get_font(sizes[name], True, True).size(labels[name])[0]
                self.assertLessEqual(width, main.buttonTextWidth(layout[name], name in main.DROPDOWNS), name)
            # the largest size that fits: one size up, some label of the row wouldn't fit
            size = sizes[row[0]]
            if size < main.BUTTON_LABEL_SIZE:
                self.assertTrue(any(main.get_font(size + 1, True, True).size(labels[n])[0]
                                    > main.buttonTextWidth(layout[n], n in main.DROPDOWNS) for n in row if labels[n]),
                                row)
        # the menu's items read evenly too, and all fit
        rects = main.menuItemRects(layout['menu'])
        menuLabels = dict(main.MENU_ITEMS)
        menuSizes = main.evenLabelSizes([list(rects)], rects, menuLabels)
        self.assertEqual(len(set(menuSizes.values())), 1)
        for name, rect in rects.items():
            self.assertLessEqual(main.get_font(menuSizes[name], True, True).size(menuLabels[name])[0],
                                 main.buttonTextWidth(rect), name)

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


    # --- step 2: Settings switches, tooltips, reasons for disabled controls, the hand cursor

    def boardSurface(self):
        p.init()  # fonts, for the coordinates
        self.main.loadImages()
        return p.Surface((self.main.BOARD_WIDTH, self.main.BOARD_HEIGHT))

    def resetSwitches(self):
        for name in ('coordinates', 'moveMarkers', 'lastMove', 'animation', 'sound', 'volume'):
            self.settings.put(name, self.settings.DEFAULTS[name])
        self.main.applySoundSettings()

    def test_board_switches_change_the_drawing(self):
        main, settings = self.main, self.settings
        surface = self.boardSurface()
        SQ = main.SQ_SIZE
        light, dark = tuple(main.BOARD_COLORS[0]), tuple(main.BOARD_COLORS[1])

        def colors(x, y, w, h):
            return {tuple(surface.get_at((i, j)))[:3] for i in range(x, x + w) for j in range(y, y + h)}

        def corner(row, col):
            return tuple(surface.get_at((col * SQ + 6, row * SQ + 6)))[:3]

        try:
            gs = support.GameState()
            # coordinates: a5 (dark, empty at the start) has its rank label "5" in its top left corner
            main.drawGameState(surface, gs, [], ())
            self.assertIn(light, colors(2, 3 * SQ + 2, 16, 20))
            settings.put('coordinates', False)
            main.drawGameState(surface, gs, [], ())
            self.assertEqual(colors(2, 3 * SQ + 2, 16, 20), {dark})
            # move hints: with e2 selected, a dot in the middle of e3
            moves = gs.getValidMoves()
            e3 = (4 * SQ + SQ // 2, 5 * SQ + SQ // 2)
            main.drawGameState(surface, gs, moves, (6, 4))
            self.assertNotEqual(tuple(surface.get_at(e3))[:3], dark)
            settings.put('moveMarkers', False)
            main.drawGameState(surface, gs, moves, (6, 4))
            self.assertEqual(tuple(surface.get_at(e3))[:3], dark)
            # last move: after 1.e4 the e2 square is tinted
            support.play(gs, "e2e4")
            main.drawGameState(surface, gs, [], ())
            self.assertNotEqual(corner(6, 4), light)
            settings.put('lastMove', False)
            main.drawGameState(surface, gs, [], ())
            self.assertEqual(corner(6, 4), light)
        finally:
            self.resetSwitches()

    def test_animation_speed(self):
        main, settings = self.main, self.settings
        surface = self.boardSurface()
        gs = support.GameState()
        move = support.Move((6, 4), (4, 4), gs.board)
        normal = main.animationDuration(move, 'normal')
        self.assertEqual(normal, main.ANIMATION_BASE_MS + 2 * main.ANIMATION_MS_PER_SQUARE)
        self.assertAlmostEqual(main.animationDuration(move, 'fast'), normal * 0.5)
        self.assertAlmostEqual(main.animationDuration(move, 'slow'), normal * 1.7)
        self.assertEqual(main.animationDuration(move, 'off'), 0)
        try:
            settings.put('animation', 'off')
            surface.fill((1, 2, 3))
            asyncio.run(main.animateMove(move, surface, gs.board, p.time.Clock()))
            self.assertEqual(tuple(surface.get_at((10, 10)))[:3], (1, 2, 3), "no slide is drawn")
            settings.put('animation', 'slow')
            self.assertAlmostEqual(main.animationDuration(move), normal * 1.7)  # the saved speed by default
        finally:
            self.resetSwitches()

    def test_settings_tabs_volume_and_sound(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            seen['start'] = main.SOUNDS['move'].get_volume()
            await self.openMenuItem('settings')
            board = main.settingsLayout('board')
            game = main.settingsLayout('game')
            await self.click(board['tab:game'].center)
            for _ in range(3):
                await self.click(game['volume:-'].center, 0.15)
            seen['volume 50'] = main.SOUNDS['capture'].get_volume()
            await self.click(game['sound:off'].center)
            seen['sound off'] = main.SOUNDS['promote'].get_volume()
            await self.click(game['figurines:on'].center)
            await self.click(game['premoves:off'].center)
            await self.click(game['close'].center)
            # it opens again on the Game tab: its sound switch is where the Board tab has none
            await self.openMenuItem('settings')
            await self.click(game['sound:on'].center)
            seen['sound on'] = main.SOUNDS['move'].get_volume()
            p.event.post(p.event.Event(p.KEYDOWN, key=p.K_TAB, unicode='\t', mod=0, scancode=0))
            await asyncio.sleep(0.2)
            await self.click(board['animation:fast'].center)  # Tab switched back to the Board tab
            p.event.post(p.event.Event(p.KEYDOWN, key=p.K_ESCAPE, unicode='', mod=0, scancode=0))
            await asyncio.sleep(0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        try:
            asyncio.run(run())
            self.assertAlmostEqual(seen['start'], 0.8, places=2)
            self.assertAlmostEqual(seen['volume 50'], 0.5, places=2)
            self.assertEqual(seen['sound off'], 0)
            self.assertAlmostEqual(seen['sound on'], 0.5, places=2)
            self.settings._values = None  # read back from the file, as on the next start
            self.assertEqual([self.settings.get(name) for name in ('volume', 'sound', 'figurines', 'premoves', 'animation')],
                             [50, True, True, False, 'fast'])
        finally:
            self.resetSwitches()
            self.settings.put('figurines', False)
            self.settings.put('premoves', True)

    def test_tooltip_texts_and_disabled_reasons(self):
        main = self.main
        reason = main.disabledReason
        self.assertEqual(main.tooltipText('undo'), "Undo (Z)")
        self.assertEqual(main.tooltipText('restart'), "Restart (R)")
        self.assertEqual(main.tooltipText('help'), "How to play (H)")
        self.assertEqual(main.tooltipText('prev'), "Previous move (Left)")
        self.assertEqual(main.tooltipText('restart', connected=True), "Leave the room")
        for mode, connected, reviewing in ((0, False, False), (1, False, True), (2, False, False), (2, True, True)):
            for row in main.panelRows(mode, connected, True, reviewing):
                for name in row:
                    if name != 'roomInfo':
                        self.assertTrue(main.tooltipText(name), name)
        self.assertEqual(reason('hint', hintsLeft=0), "No hints left today")
        self.assertEqual(reason('hint', humanTurn=False), "Wait for your turn")
        self.assertEqual(reason('hint', online=True), "Hints are off in online games")
        self.assertEqual(reason('hint', gameOver=True), "The game is over")
        self.assertIsNone(reason('hint'))
        self.assertEqual(reason('save'), "Make a move first")
        self.assertEqual(reason('load', online=True), "Leave online play first")
        self.assertEqual(reason('resign', gameOver=True), "The game is over")
        self.assertEqual(reason('draw', gameOver=True), "The game is over")
        self.assertEqual(reason('undo', online=True), "No game yet")
        self.assertIsNone(reason('undo', online=True, connected=True))
        self.assertEqual(reason('join'), "Type a room code first")
        self.assertIsNone(reason('join', roomCode="AB12"))
        screen = (main.BOARD_WIDTH + main.MOVE_LOG_PANEL_WIDTH, main.BOARD_HEIGHT)
        for pos in ((0, 0), (screen[0] - 1, screen[1] - 1), (screen[0] - 1, 0), (0, screen[1] - 1)):
            rect = main.tooltipRect("Hints are off in online games", pos, screen)
            self.assertTrue(p.Rect(0, 0, *screen).contains(rect), pos)
            self.assertFalse(rect.collidepoint(pos), "the tooltip doesn't cover the pointer")

    def test_tooltip_and_hand_cursor(self):
        main = self.main
        seen = {}
        menuButton = main.panelLayout(0, False)['menu'].center
        screenSize = (main.BOARD_WIDTH + main.MOVE_LOG_PANEL_WIDTH, main.BOARD_HEIGHT)
        tip = main.tooltipRect(main.tooltipText('menu'), menuButton, screenSize)

        def tipPixel():
            return tuple(p.display.get_surface().get_at((tip.x + 3, tip.centery)))[:3]

        async def hover(pos, wait):
            self.mouse[0] = pos
            p.event.post(p.event.Event(p.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
            await asyncio.sleep(wait)

        async def script():
            await asyncio.sleep(1.0)
            await hover(menuButton, 0.2)
            seen['menu early'] = (tipPixel(), main.CURSOR[0])
            await asyncio.sleep(0.8)
            seen['menu later'] = tipPixel()
            await hover(self.square(4, 4), 0.2)  # an empty square
            seen['empty square'] = main.CURSOR[0]
            await hover(self.square(6, 4), 0.2)  # White's e-pawn, White to move
            seen['own pawn'] = main.CURSOR[0]
            await hover(self.square(1, 4), 0.2)  # Black's
            seen['their pawn'] = main.CURSOR[0]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        tooltipBg = tuple(main.UI['tooltipBg'])
        self.assertNotEqual(seen['menu early'][0], tooltipBg, "the tooltip waits a moment")
        self.assertEqual(seen['menu early'][1], 'hand')
        self.assertEqual(seen['menu later'], tooltipBg)
        self.assertEqual(seen['empty square'], 'arrow')
        self.assertEqual(seen['own pawn'], 'hand')
        self.assertEqual(seen['their pawn'], 'arrow')

    def test_disabled_hint_says_why(self):
        main = self.main
        import hints
        for _ in range(hints.HINTS_PER_DAY):
            hints.use()
        shown = {'status': [], 'tooltip': []}
        realStatus, realTooltip = main.drawStatus, main.drawTooltip

        def recordStatus(screen, rect, text):
            shown['status'].append(text)
            realStatus(screen, rect, text)

        def recordTooltip(screen, text, pos):
            shown['tooltip'].append(text)
            return realTooltip(screen, text, pos)

        async def script():
            await asyncio.sleep(1.0)
            hint = main.panelLayout(0, False)['hint'].center
            self.mouse[0] = hint
            await asyncio.sleep(0.9)
            await self.click(hint)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        main.drawStatus, main.drawTooltip = recordStatus, recordTooltip
        try:
            asyncio.run(run())
        finally:
            main.drawStatus, main.drawTooltip = realStatus, realTooltip
            hints._store({})
            hints._saved = None
        self.assertIn("No hints left today", shown['tooltip'])
        self.assertIn("No hints left today", shown['status'])
        self.assertNotIn("Looking for a good move...", shown['status'])

    # --- step 3: the menu, Flip board, no Resign / Draw before an online game

    def recordShown(self):
        """Records the texts passed to drawStatus and drawTooltip; returns (shown, restore)."""
        main = self.main
        shown = {'status': [], 'tooltip': []}
        realStatus, realTooltip = main.drawStatus, main.drawTooltip

        def recordStatus(screen, rect, text):
            shown['status'].append(text)
            realStatus(screen, rect, text)

        def recordTooltip(screen, text, pos):
            shown['tooltip'].append(text)
            return realTooltip(screen, text, pos)

        def restore():
            main.drawStatus, main.drawTooltip = realStatus, realTooltip
        main.drawStatus, main.drawTooltip = recordStatus, recordTooltip
        return shown, restore

    async def key(self, k, text='', wait=0.3):
        p.event.post(p.event.Event(p.KEYDOWN, key=k, unicode=text, mod=0, scancode=0))
        await asyncio.sleep(wait)

    def squareSample(self, surface, row, col):
        """Pixels across the middle of a square (clear of the coordinates), to tell which piece is drawn there."""
        SQ = self.main.SQ_SIZE
        return [tuple(surface.get_at((col * SQ + x, row * SQ + SQ // 2)))[:3] for x in range(8, SQ - 8, 3)]

    def startBoards(self):
        """The start position drawn the usual way round and flipped, for comparing with the screen."""
        surface = p.Surface((self.main.BOARD_WIDTH, self.main.BOARD_HEIGHT))
        boards = []
        for flip in (False, True):
            self.main.drawGameState(surface, support.GameState(), [], (), flip)
            boards.append(self.squareSample(surface, 0, 0))
        return boards

    def test_menu_opens_closes_and_says_why_an_item_is_disabled(self):
        main = self.main
        seen = {}
        menu = main.panelLayout(0, False)['menu'].center
        load = self.menuItem('load')
        # on the Load item, in a gap between two panel rows, so it's the panel's color while the menu is closed
        layout = main.panelLayout(0, False)
        probe = next((load.x + 10, y) for y in range(load.y + 6, load.bottom - 6)
                     if not any(rect.collidepoint(load.x + 10, y) for rect in layout.values()))

        def probeColor():
            return tuple(p.display.get_surface().get_at(probe))[:3]

        async def script():
            await asyncio.sleep(1.0)
            seen['closed'] = probeColor()
            await self.click(menu)
            seen['open'] = probeColor()
            await self.key(p.K_ESCAPE)
            seen['after Esc'] = probeColor()
            await self.click(menu)
            await self.click(self.square(4, 4))  # outside: only closes it
            seen['after outside click'] = probeColor()
            await self.click(menu)
            await self.click(menu)  # its own button closes it again
            seen['after button again'] = probeColor()
            # Save is disabled before the first move: its tooltip and a click say why, and the menu stays open
            await self.click(menu)
            save = self.menuItem('save').center
            self.mouse[0] = save
            await asyncio.sleep(0.9)
            await self.click(save)
            seen['after disabled click'] = probeColor()
            await self.click(self.menuItem('flip').center, 0.4)  # Flip board runs and closes the menu
            seen['after flip'] = probeColor()
            seen['corner'] = self.squareSample(p.display.get_surface(), 0, 0)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        shown, restore = self.recordShown()
        try:
            asyncio.run(run())
        finally:
            restore()
        panel, button = tuple(main.UI['panel']), tuple(main.UI['button'])
        self.assertEqual(seen['closed'], panel)
        self.assertEqual(seen['open'], button, "Load game is enabled against the computer")
        self.assertEqual(seen['after Esc'], panel)
        self.assertEqual(seen['after outside click'], panel)
        self.assertEqual(seen['after button again'], panel)
        self.assertEqual(seen['after disabled click'], button)
        self.assertEqual(seen['after flip'], panel)
        self.assertIn("Make a move first", shown['tooltip'])
        self.assertIn("Make a move first", shown['status'])
        _, flipped = self.startBoards()
        self.assertEqual(seen['corner'], flipped, "h1's white rook is in the top left corner")
        for name, _ in main.MENU_ITEMS:
            self.assertTrue(main.tooltipText(name), name)

    def test_f_flips_the_board_until_a_new_game(self):
        main = self.main
        seen = {}

        def corner():
            return self.squareSample(p.display.get_surface(), 0, 0)

        async def script():
            await asyncio.sleep(1.0)
            seen['start'] = corner()
            await self.key(p.K_f, 'f')
            seen['F'] = corner()
            await self.key(p.K_f, 'f')
            seen['F again'] = corner()
            await self.key(p.K_f, 'f')
            await self.key(p.K_r, 'r')  # no moves yet: a new game starts without asking
            seen['new game'] = corner()
            # flipped, the squares are clicked where they are drawn: e2-e4 is row 1 -> row 3 of column d
            await self.key(p.K_f, 'f')
            await self.move((1, 3), (3, 3), 0.6)
            seen['e4'] = self.squareSample(p.display.get_surface(), 3, 3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        usual, flipped = self.startBoards()
        self.assertNotEqual(usual, flipped)
        self.assertEqual(seen['start'], usual)
        self.assertEqual(seen['F'], flipped)
        self.assertEqual(seen['F again'], usual)
        self.assertEqual(seen['new game'], usual, "a new game is the usual way round")
        self.assertNotEqual(seen['e4'], [tuple(main.BOARD_COLORS[(3 + 3) % 2])] * len(seen['e4']),
                            "the pawn moved to e4, drawn at row 3 column d when flipped")

    def test_online_setup_has_no_resign_or_draw(self):
        main = self.main
        setup = main.panelLayout(2, False)
        self.assertNotIn('resign', setup)
        self.assertNotIn('draw', setup)
        for name in ('undo', 'restart', 'account', 'menu'):
            self.assertIn(name, setup)
        for mode, connected in ((0, False), (1, False), (2, True)):
            self.assertIn('resign', main.panelLayout(mode, connected), mode)
        # the move log gets the freed row: mode, room and clock, host and join, and the bottom row
        self.assertEqual(len(main.panelRows(2, False)), 4)
        self.assertEqual(min(r.y for r in setup.values()),
                         main.BOARD_HEIGHT - main.PANEL_PADDING - 4 * main.ROW_HEIGHT - 3 * main.ROW_GAP)
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(setup['undo'].center)
            seen['undo color'] = tuple(p.display.get_surface().get_at((setup['undo'].x + 6, setup['undo'].centery)))[:3]
            # the board can't be played before there is a room
            await self.move((6, 4), (4, 4))
            seen['e4'] = self.squareSample(p.display.get_surface(), 4, 4)
            # Load game is disabled online, and says so
            await self.openMenuItem('load', mode=2)
            await self.key(p.K_ESCAPE)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        shown, restore = self.recordShown()
        try:
            asyncio.run(run())
        finally:
            restore()
        self.assertIn("No game yet", shown['status'])
        self.assertIn("Leave online play first", shown['status'])
        self.assertEqual(seen['undo color'], tuple(main.UI['buttonDisabled']))
        self.assertIn("Host or join a room to start a game", shown['status'])
        self.assertEqual(seen['e4'], [tuple(main.BOARD_COLORS[0])] * len(seen['e4']), "e4 stays empty")

    # --- step 4: drag and drop, refused moves, right-button marks and arrows

    async def chooseTwoPlayers(self):
        modeRect = self.main.panelLayout(0, False)['mode']
        await self.click(modeRect.center)
        await self.click(self.main.dropdownOptionRects(modeRect, len(self.main.MODE_OPTIONS))[1].center, 0.5)

    async def dragPiece(self, start, end, steps=5, release=True, wait=0.4):
        """Presses on square start, moves the pointer to end in steps with the button held, and lets go."""
        await self.click(self.square(*start), 0.05)
        (x0, y0), (x1, y1) = self.square(*start), self.square(*end)
        for i in range(1, steps + 1):
            pos = (round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps))
            self.mouse[0] = pos
            p.event.post(p.event.Event(p.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0)))
            await asyncio.sleep(0.04)
        if release:
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(wait)

    async def rightClick(self, start, end=None, mods=0, wait=0.2):
        """Right button down on square start and up on end (the same square by default), with mods held."""
        p.key.set_mods(mods)
        self.mouse[0] = self.square(*start)
        p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=3, pos=self.mouse[0]))
        await asyncio.sleep(0.05)
        self.mouse[0] = self.square(*(end or start))
        p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=3, pos=self.mouse[0]))
        await asyncio.sleep(wait)
        p.key.set_mods(0)

    def emptySquare(self, row, col):
        sample = self.squareSample(p.display.get_surface(), row, col)
        return len(set(sample)) == 1

    def test_drag_and_drop(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            await self.chooseTwoPlayers()
            # e2-e4 by dragging; while held, e2 is empty and the pawn follows the pointer
            await self.dragPiece((6, 4), (4, 4), release=False)
            await asyncio.sleep(0.1)
            seen['held'] = (self.emptySquare(6, 4), main.CURSOR[0])
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(0.4)
            seen['e4'] = (self.emptySquare(6, 4), self.emptySquare(4, 4))
            # a drop where the piece can't go: d7-d4 returns it, still selected, so a click on d5 plays d7-d5
            await self.dragPiece((1, 3), (4, 3))
            seen['returned'] = (self.emptySquare(1, 3), self.emptySquare(4, 3))
            await self.click(self.square(3, 3), 0.5)
            seen['d5'] = (self.emptySquare(1, 3), self.emptySquare(3, 3))
            # Esc while dragging puts the knight back; the release after it does nothing
            await self.dragPiece((7, 6), (5, 5), release=False)
            await self.key(p.K_ESCAPE, wait=0.1)
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(0.3)
            seen['after Esc'] = (self.emptySquare(7, 6), self.emptySquare(5, 5))
            # so does the right button
            await self.dragPiece((7, 6), (5, 5), release=False)
            await self.rightClick((5, 5))
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(0.3)
            seen['after right'] = (self.emptySquare(7, 6), self.emptySquare(5, 5))
            # two clicks still play a move: Ng1-f3
            await self.move((7, 6), (5, 5))
            seen['Nf3'] = (self.emptySquare(7, 6), self.emptySquare(5, 5))
            # flipped (F), Black's e7 pawn is drawn at row 6, column 3: drag it to e6 (row 5)
            await self.key(p.K_f, 'f')
            await self.dragPiece((6, 3), (5, 3))
            seen['flipped e6'] = (self.emptySquare(6, 3), self.emptySquare(5, 3))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        self.assertEqual(seen['held'], (True, 'hand'), "the dragged pawn left e2, and a hand holds it")
        self.assertEqual(seen['e4'], (True, False))
        self.assertEqual(seen['returned'], (False, True), "the pawn is back on d7, d4 stays empty")
        self.assertEqual(seen['d5'], (True, False))
        self.assertEqual(seen['after Esc'], (False, True))
        self.assertEqual(seen['after right'], (False, True))
        self.assertEqual(seen['Nf3'], (True, False))
        self.assertEqual(seen['flipped e6'], (True, False))

    def test_refusal_reason(self):
        main = self.main
        # the e2 knight is pinned by the e7 rook: it may not move at all
        gs = support.fromFen('4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1')
        self.assertEqual(main.refusalReason(gs, (6, 4), (4, 5)), main.REFUSED_EXPOSES_KING)
        self.assertIsNone(main.refusalReason(gs, (6, 4), (5, 4)), "not a knight move: just a new selection")
        self.assertIsNone(main.refusalReason(gs, (7, 4), (7, 3)), "a legal king move")
        self.assertEqual(gs.pins, [], "the position's own state is left alone")
        # in check from the a1 rook: the a2 pawn may not advance; the king may not stay on the rank
        gs = support.fromFen('4k3/8/8/8/8/8/P7/r3K3 w - - 0 1')
        gs.getValidMoves()
        self.assertEqual(main.refusalReason(gs, (6, 0), (5, 0)), main.REFUSED_IN_CHECK)
        self.assertIsNone(main.refusalReason(gs, (7, 4), (6, 4)), "out of check")
        self.assertIsNone(main.refusalReason(gs, (7, 4), (7, 3)), "the king's own moves are already filtered")
        self.assertIsNone(main.refusalReason(gs, (1, 4), (2, 4)), "not the side to move")
        self.assertTrue(gs.inCheck)

    def test_refused_move_says_why(self):
        main = self.main

        async def script():
            await asyncio.sleep(1.0)
            await self.chooseTwoPlayers()
            # 1.e4 d5 2.c4 e6 3.d3 Bb4+: White is in check
            for start, end in (((6, 4), (4, 4)), ((1, 3), (3, 3)), ((6, 2), (4, 2)), ((1, 4), (2, 4)),
                               ((6, 3), (5, 3)), ((0, 5), (4, 1))):
                await self.move(start, end)
            await self.move((6, 0), (5, 0))  # a3 doesn't answer the check
            await self.move((7, 1), (5, 2))  # Nc3 does, and is pinned now
            await self.move((1, 0), (2, 0))  # ...a6
            await self.dragPiece((5, 2), (3, 3))  # Nxd5 would leave the king in check
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        shown, restore = self.recordShown()
        try:
            asyncio.run(run())
        finally:
            restore()
        self.assertIn(main.REFUSED_IN_CHECK, shown['status'])
        self.assertIn(main.REFUSED_EXPOSES_KING, shown['status'])

    def test_king_flash_and_arrow_colors(self):
        main = self.main
        surface = self.boardSurface()
        SQ = main.SQ_SIZE
        surface.fill((0, 0, 0))
        main.drawKingFlash(surface, (7, 4), 0)
        red, green, blue = tuple(surface.get_at((4 * SQ + 2, 7 * SQ + SQ // 2)))[:3]
        self.assertGreater(red, 150, "the outline of the king's square is red")
        surface.fill((0, 0, 0))
        main.drawKingFlash(surface, (7, 4), main.KING_FLASH_MS)
        self.assertEqual(tuple(surface.get_at((4 * SQ + 2, 7 * SQ + SQ // 2)))[:3], (0, 0, 0), "it's over")
        # arrows: hints keep ARROW_COLOR, the player's are drawn in theirs
        mid = (4 * SQ + SQ // 2, 5 * SQ)  # on the shaft of an arrow from e2 to e5
        surface.fill((0, 0, 0))
        main.drawArrow(surface, (6, 4), (3, 4))
        hint = tuple(surface.get_at(mid))[:3]
        surface.fill((0, 0, 0))
        main.drawArrow(surface, (6, 4), (3, 4), color=(250, 0, 0, 255))
        self.assertEqual(tuple(surface.get_at(mid))[:3], (250, 0, 0))
        self.assertGreater(hint[2], hint[0], "the hint arrow is blue")
        self.assertEqual(main.annotationColor(0), 'green')
        self.assertEqual(main.annotationColor(p.KMOD_LSHIFT), 'red')
        self.assertEqual(main.annotationColor(p.KMOD_LCTRL), 'blue')
        self.assertEqual(main.annotationColor(p.KMOD_LALT), 'blue')
        store = {}
        main.toggleAnnotation(store, 'a', 'green')
        main.toggleAnnotation(store, 'a', 'red')
        self.assertEqual(store, {'a': 'red'}, "another color replaces it")
        main.toggleAnnotation(store, 'a', 'red')
        self.assertEqual(store, {}, "the same color again removes it")
        self.assertEqual(main.boardSquare((10, 10), True), (7, 7))

    def test_right_button_marks_and_arrows(self):
        main = self.main
        SQ = main.SQ_SIZE
        seen = {}
        ringPixel = (4 * SQ + SQ // 2, 4 * SQ + 5)  # e4, on its ring's top
        arrowPixel = (3 * SQ + SQ // 2, 5 * SQ + SQ // 2)  # d3, on an arrow from a3 to h3

        def at(pos):
            return tuple(p.display.get_surface().get_at(pos))[:3]

        async def script():
            await asyncio.sleep(1.0)
            seen['before'] = (at(ringPixel), at(arrowPixel))
            await self.rightClick((4, 4))
            await self.rightClick((5, 0), (5, 7))
            seen['green'] = (at(ringPixel), at(arrowPixel))
            await self.rightClick((4, 4), mods=p.KMOD_LSHIFT)  # a red ring replaces the green one
            await self.rightClick((5, 0), (5, 7), mods=p.KMOD_LCTRL)
            seen['red and blue'] = (at(ringPixel), at(arrowPixel))
            await self.click(self.square(3, 2))  # a left click on the board (an empty square) clears them
            seen['cleared'] = (at(ringPixel), at(arrowPixel))
            await self.rightClick((4, 4))
            await self.rightClick((4, 4))  # the same mark again removes it
            seen['toggled off'] = at(ringPixel)
            await self.rightClick((4, 4))
            await self.move((6, 4), (4, 4), 2.5)  # a move clears them (and the computer replies)
            await self.rightClick((5, 0), (5, 7))
            await self.key(p.K_z, 'z')  # and so does taking it back
            seen['after undo'] = at(arrowPixel)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        asyncio.run(run())
        light, dark = tuple(main.BOARD_COLORS[0]), tuple(main.BOARD_COLORS[1])
        self.assertEqual(seen['before'], (light, light))
        ring, arrow = seen['green']
        self.assertTrue(ring[1] > ring[0] and ring[1] > ring[2], "a green ring on e4: %s" % (ring,))
        self.assertTrue(arrow[1] > arrow[0] and arrow[1] > arrow[2], "a green arrow over d3: %s" % (arrow,))
        ring, arrow = seen['red and blue']
        self.assertTrue(ring[0] > ring[1] and ring[0] > ring[2], "Shift: red %s" % (ring,))
        self.assertTrue(arrow[2] > arrow[0] and arrow[2] > arrow[1], "Ctrl: blue %s" % (arrow,))
        self.assertEqual(seen['cleared'], (light, light))
        self.assertEqual(seen['toggled off'], light)
        self.assertEqual(seen['after undo'], light)

    # --- step 5: looking back during the game, premoves

    def recordBoards(self):
        """Records what each drawGameState call draws: (codes of the shown position's moves, premove squares).
        Returns (frames, restore); frames[-1] is the latest frame's board."""
        main = self.main
        frames = []
        real = main.drawGameState

        def record(screen, gs, *args, **kwargs):
            premove = kwargs.get('premove')
            frames.append(([m.getCode() for m in gs.moveLog], list(premove['squares']) if premove else []))
            return real(screen, gs, *args, **kwargs)

        def restore():
            main.drawGameState = real
        main.drawGameState = record
        return frames, restore

    def runGame(self, script, thinkMs=None):
        """Runs the game loop with script; thinkMs makes the computer take at least that long per move."""
        main = self.main
        savedThink = main.AI_MIN_THINK_MS

        async def run():
            await asyncio.gather(main.main(), script())
        if thinkMs is not None:
            main.AI_MIN_THINK_MS = thinkMs
        try:
            asyncio.run(run())
        finally:
            main.AI_MIN_THINK_MS = savedThink

    def premoveTinted(self, row, col):
        """The square's corner shows the premove's purple (more blue than green), not a board color."""
        SQ = self.main.SQ_SIZE
        r, g, b = tuple(p.display.get_surface().get_at((col * SQ + SQ - 8, row * SQ + 8)))[:3]  # clear of the labels
        return b > g + 20 and r > g

    def test_premove_moves_and_resolving_them(self):
        main = self.main
        # 1.e4 e5 2.Bc4, Black to move: White may premove Bxf7+ (legal if it were White's turn)
        gs = support.play(support.GameState(), "e2e4 e7e5 f1c4")
        moves = [m.getCode() for m in main.premoveMoves(gs)]
        self.assertIn("c4f7", moves)
        self.assertIn("a2a3", moves)
        self.assertNotIn("e7e6", moves, "Black's moves aren't premoves for White")
        self.assertTrue(gs.whiteToMove is False and len(gs.moveLog) == 3, "the game itself is left alone")
        # Black answers 2...Nf6: Bxf7+ is still legal and is played
        after = support.play(support.play(support.GameState(), "e2e4 e7e5 f1c4"), "g8f6")
        move = main.resolvePremove(((4, 2), (1, 5)), after.getValidMoves())
        self.assertEqual(move.getCode(), "c4f7")
        # 2...d5 blocks the diagonal: the premove isn't legal any more, so it's dropped
        blocked = support.play(support.GameState(), "e2e4 e7e5 f1c4 d7d5")
        self.assertIsNone(main.resolvePremove(((4, 2), (1, 5)), blocked.getValidMoves()))
        # en passant can't be premoved, and taking a king in check never becomes legal
        gs = support.fromFen('4k3/8/8/3pP3/8/8/8/4K3 b - d6 0 1')  # Black to move; White's e5 pawn could take d6
        self.assertNotIn("e5d6", [m.getCode() for m in main.premoveMoves(gs)])
        gs = support.fromFen('4k3/8/8/8/8/8/8/4KQ2 b - - 0 1')
        gs.whiteToMove = False
        gs.board[1][4] = 'wQ'  # a queen on e7 gives check
        gs.board[7][5] = '--'
        self.assertNotIn("e7e8", [m.getCode() for m in main.premoveMoves(gs)])
        # a promotion premove stays a queen
        gs = support.fromFen('7k/P7/8/8/8/8/8/K7 w - - 0 1')
        self.assertEqual(main.resolvePremove(((1, 0), (0, 0)), gs.getValidMoves()).getCode(), "a7a8q")

    def test_premove_is_played_when_the_computer_replies(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            await self.move((6, 4), (4, 4), 0.4)  # 1.e4; the computer thinks for at least 1.5 s
            await self.move((6, 0), (5, 0), 0.3)  # premove a2-a3
            seen['chosen'] = (frames[-1][0], frames[-1][1], self.premoveTinted(5, 0), self.emptySquare(5, 0),
                              self.emptySquare(6, 0))
            await asyncio.sleep(2.0)
            seen['after reply'] = (frames[-1][0], self.emptySquare(5, 0), self.emptySquare(6, 0))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        try:
            self.runGame(script, thinkMs=1500)
        finally:
            restore()
        log, squares, tinted, a3Empty, a2Empty = seen['chosen']
        self.assertEqual(log, ["e2e4"], "the computer is still thinking")
        self.assertEqual(squares, [(6, 0), (5, 0)])
        self.assertTrue(tinted, "a3 shows the premove's color")
        self.assertEqual((a3Empty, a2Empty), (True, False), "the pawn stays on a2 until it's played")
        log, a3Empty, a2Empty = seen['after reply']
        self.assertGreaterEqual(len(log), 3, log)
        self.assertEqual(log[2], "a2a3", "played right after the computer's reply")
        self.assertEqual((a3Empty, a2Empty), (False, True))

    def test_premove_cancel_and_the_setting(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            await self.move((6, 4), (4, 4), 0.4)  # 1.e4; the computer thinks for 6 s
            await self.move((6, 0), (5, 0), 0.2)
            seen['set'] = frames[-1][1]
            await self.rightClick((2, 2))  # anywhere on the board
            seen['right'] = (frames[-1][1], self.pixel(2, 2))
            await self.dragPiece((7, 6), (5, 5))  # by dragging: Ng1-f3
            seen['dragged'] = frames[-1][1]
            await self.key(p.K_ESCAPE)
            seen['Esc'] = frames[-1][1]
            await self.move((6, 3), (4, 3), 0.2)  # d2-d4, then a click on the d2 pawn again cancels it
            await self.click(self.square(6, 3))
            seen['clicked again'] = frames[-1][1]
            await self.move((6, 1), (5, 1), 0.2)  # b2-b3, replaced by c2-c3
            await self.move((6, 2), (5, 2), 0.2)
            seen['replaced'] = frames[-1][1]
            await self.key(p.K_z, 'z')  # taking back 1.e4 drops it
            seen['undo'] = frames[-1]
            # switched off: a click during the computer's turn chooses nothing
            self.settings.put('premoves', False)
            await self.move((6, 4), (4, 4), 0.4)
            await self.move((6, 0), (5, 0), 0.2)
            seen['off'] = (frames[-1][1], self.premoveTinted(5, 0))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        try:
            self.runGame(script, thinkMs=6000)
        finally:
            restore()
            self.settings.put('premoves', True)
        self.assertEqual(seen['set'], [(6, 0), (5, 0)])
        squares, c6 = seen['right']
        self.assertEqual(squares, [], "the right button cancels it")
        self.assertEqual(c6, tuple(main.BOARD_COLORS[0]), "and draws no mark")
        self.assertEqual(seen['dragged'], [(7, 6), (5, 5)])
        self.assertEqual(seen['Esc'], [])
        self.assertEqual(seen['clicked again'], [])
        self.assertEqual(seen['replaced'], [(6, 2), (5, 2)])
        self.assertEqual(seen['undo'], ([], []))
        self.assertEqual(seen['off'], ([], False))

    def test_online_premove_is_played_after_the_opponents_move(self):
        main = self.main
        import network
        net = network.net
        sent = []
        seen = {}
        realSetTopic, realSend = net.set_topic, net.send

        def fakeSetTopic(topic):  # no internet: a room that only this test talks to
            net.topic = "chess_app_multiplayer_" + str(topic)
            net.running = True
            net.last_status = "SYNC HEALTHY"

        async def fakeSend(data):
            sent.append(dict(data))

        def lastMoves():
            states = [m for m in sent if m.get('type') == 'state']
            return states[-1]['moves'] if states else None

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['host'].center, 0.5)  # the host plays White
            await self.move((6, 4), (4, 4), 0.5)
            await self.move((6, 3), (4, 3), 0.3)  # premove d2-d4 while the guest is to move
            seen['before'] = (lastMoves(), frames[-1][1])
            state = [m for m in sent if m.get('type') == 'state'][-1]
            net.incoming_messages.append({'type': 'state', 'game': state['game'], 'version': state['version'] + 1,
                                          'gid': state['gid'], 'moves': "e2e4 e7e5", 'tc': None, 'clocks': None,
                                          'result': None, 'role': 'client', 'sender': 'guest'})
            await asyncio.sleep(0.8)
            seen['after'] = (lastMoves(), frames[-1][0])
            await self.click(main.panelLayout(2, True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        net.set_topic, net.send = fakeSetTopic, fakeSend
        try:
            self.runGame(script)
        finally:
            restore()
            net.set_topic, net.send = realSetTopic, realSend
            net.running = False
            if os.path.exists(network.SESSION_FILE):
                os.remove(network.SESSION_FILE)  # no Rejoin row for the other tests
        self.assertEqual(seen['before'], ("e2e4", [(6, 3), (4, 3)]))
        self.assertEqual(seen['after'], ("e2e4 e7e5 d2d4", ["e2e4", "e7e5", "d2d4"]),
                         "the premove was played and sent as soon as the opponent's move came in")

    def test_looking_back_during_the_game(self):
        main = self.main
        seen = {}
        bannerPixel = (4, 4)  # top left corner of the board, under the banner

        def at(pos):
            return tuple(p.display.get_surface().get_at(pos))[:3]

        async def script():
            await asyncio.sleep(1.0)
            await self.move((6, 4), (4, 4), 2.5)  # 1.e4 and the computer's reply
            seen['live'] = (frames[-1][0], at(bannerPixel))
            await self.key(p.K_LEFT)
            seen['Left'] = (frames[-1][0], at(bannerPixel))
            await self.key(p.K_HOME)
            seen['Home'] = (frames[-1][0], self.emptySquare(4, 4), self.emptySquare(6, 4))
            await self.click(self.square(6, 3))  # a click on the board returns, and plays nothing
            seen['clicked'] = (frames[-1][0], self.emptySquare(4, 4), at(bannerPixel))
            await self.click(self.square(6, 3))  # now it selects d2 as usual
            # clicking the first move in the log shows the position after it
            await self.click((main.PANEL_X + 60, main.STRIP_HEIGHT + 18))
            seen['log click'] = frames[-1][0]
            await self.key(p.K_END)
            seen['End'] = frames[-1][0]
            # the computer's move while looking back returns to the game
            await self.move((6, 3), (4, 3), 0.4)  # 2.d4; the computer thinks for 1.5 s
            await self.key(p.K_HOME)
            seen['looking'] = frames[-1][0]
            await asyncio.sleep(2.0)
            seen['reply'] = frames[-1][0]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        try:
            self.runGame(script, thinkMs=1500)
        finally:
            restore()
        log, before = seen['live']
        self.assertEqual(len(log), 2)
        self.assertEqual(seen['Left'][0], log[:1], "Left: the position after 1.e4")
        self.assertNotEqual(seen['Left'][1], before, "the banner is over the board")
        self.assertEqual(seen['Home'], ([], True, False), "Home: the start position")
        self.assertEqual(seen['clicked'], (log, False, before), "back to the game, no move made")
        self.assertEqual(seen['log click'], log[:1])
        self.assertEqual(seen['End'], log)
        self.assertEqual(seen['looking'], [])
        self.assertEqual(len(seen['reply']), 4, "the computer's move returned to the game")
        gs = support.GameState()
        for code in ("e2e4", "e7e5"):
            moves = gs.getValidMoves()
            gs.makeMoveWithSan(gs.findMoveByCode(code, moves), moves)
        self.assertEqual(main.lookBackText(gs.moveLog, 2),
                         "Looking back: after 1... e5  -  click here or press End to return")
        self.assertTrue(main.lookBackText(gs.moveLog, 1).startswith("Looking back: after 1. e4  -"))
        self.assertTrue(main.lookBackText([], 0).startswith("Looking back: the start position"))


if __name__ == '__main__':
    unittest.main()
