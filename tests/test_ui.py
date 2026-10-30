# Runs the real game loop without a window: scripted clicks and keys, checked against the drawn screen
import asyncio
import base64
import json
import math
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
        settings.put('seenHelp', True)  # How to play opens by itself only on the first visit (its own tests)
        cls.settings = settings
        import main
        cls.main = main
        p.init()  # fonts and the display, for the tests that draw without running the game
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
        diagrams = 0
        for page, (title, items) in enumerate(main.HELP_PAGES):
            layout = main.helpPageLayout(page)
            self.assertEqual(len(layout), len(items))
            y = box.y + 82
            for item, placed in zip(items, layout):
                icon, heading, text = item[:3]
                textX = x + (main.HELP_ICON_SIZE + 12 if icon else 0)
                self.assertEqual((placed['top'], placed['textX']), (y, textX), title)
                right = x + width
                diagram = placed['diagram']
                if len(item) > 3:  # a diagram at the right, beside the text and clear of everything else
                    diagrams += 1
                    self.assertEqual(diagram.size, main.diagramSize(item[3]))
                    self.assertEqual(diagram.right, x + width, heading)
                    self.assertGreaterEqual(diagram.y, y, heading)
                    self.assertLessEqual(diagram.bottom, placed['bottom'], heading)
                    right = diagram.x - main.HELP_DIAGRAM_GAP
                else:
                    self.assertIsNone(diagram)
                self.assertEqual(placed['lines'], main.wrapText(text, font, right - textX))
                self.assertEqual(" ".join(placed['lines']), " ".join(text.split()), "no word is lost")
                for line in placed['lines']:
                    self.assertLessEqual(textX + font.size(line)[0], right, heading)
                self.assertLessEqual(textX + main.get_font(19, True).size(heading)[0], right, heading)
                self.assertGreaterEqual(placed['bottom'], y + 24 + 20 * len(placed['lines']))
                y = placed['bottom'] + 12
            self.assertLessEqual(y - 12, buttonsTop - 6, title)
        self.assertEqual(diagrams, 4, "castling, en passant, promotion and check")

    def test_help_diagrams_name_real_squares_and_pieces(self):
        main = self.main
        for name in ('CHECK_DIAGRAM', 'PROMOTION_DIAGRAM', 'CASTLING_DIAGRAM', 'EN_PASSANT_DIAGRAM'):
            diagram = getattr(main, name)
            files, ranks = diagram['files'], diagram['ranks']
            squares = (list(diagram['pieces']) + list(diagram.get('ghosts', {})) + list(diagram.get('rings', ()))
                       + list(diagram.get('tints', ())) + ([diagram['check']] if diagram.get('check') else [])
                       + [square for arrow in diagram.get('arrows', ()) for square in arrow[:2]])
            for square in squares:
                self.assertIn(square[0], files, name)
                self.assertIn(square[1], ranks, name)
            for piece in list(diagram['pieces'].values()) + list(diagram.get('ghosts', {}).values()):
                self.assertIn(piece, main.PIECES, name)
            if diagram.get('check'):
                self.assertEqual(diagram['pieces'][diagram['check']][1], 'K', "the king is the one in check")

    def test_help_diagram_uses_the_board_colors_and_pieces(self):
        main = self.main
        diagram = main.EN_PASSANT_DIAGRAM  # files d-f, ranks 7-5: d7 tinted, d5 / e5 pawns, e5 -> d6 arrow
        sq = main.HELP_DIAGRAM_SQ
        main.loadImages()
        try:
            for board in main.BOARD_THEMES:
                main.setBoardTheme(board)
                surface = p.Surface(main.diagramSize(diagram))
                surface.fill((1, 2, 3))
                main.drawMiniBoard(surface, (0, 0), diagram)
                left = main.HELP_DIAGRAM_LABEL
                light, dark = main.BOARD_THEMES[board]
                # f7 is light, f6 dark (a1 is dark); corners stay clear of pieces and arrows
                self.assertEqual(tuple(surface.get_at((left + 2 * sq + 3, 3)))[:3], tuple(light), board)
                self.assertEqual(tuple(surface.get_at((left + 2 * sq + 3, sq + 3)))[:3], tuple(dark), board)
                self.assertNotEqual(tuple(surface.get_at((left + 3, 3)))[:3], tuple(light), "d7 shows the last move")
                # the white pawn on e5 is drawn in the middle of its square
                self.assertNotIn(tuple(surface.get_at((left + sq + sq // 2, 2 * sq + sq // 2 + 6)))[:3],
                                 (tuple(light), tuple(dark)))
        finally:
            main.setBoardTheme(self.settings.get('board'))

    def test_help_window_draws_its_diagrams(self):
        main = self.main
        drawn = []
        realMini = main.drawMiniBoard

        def record(screen, pos, diagram):
            drawn.append((tuple(pos), diagram))
            return realMini(screen, pos, diagram)
        main.drawMiniBoard = record
        main.loadImages()
        try:
            for page, (title, items) in enumerate(main.HELP_PAGES):
                del drawn[:]
                main.drawHelpWindow(p.Surface((main.WINDOW_SIZE)), page, (-1, -1))
                expected = [(tuple(placed['diagram'].topleft), item[3])
                            for item, placed in zip(items, main.helpPageLayout(page)) if len(item) > 3]
                self.assertEqual(drawn, expected, title)
        finally:
            main.drawMiniBoard = realMini

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
        self.assertEqual(reason('hint', online=True), "Join a room first")
        self.assertIsNone(reason('hint', online=True, connected=True), "hints work in an online game")
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
            rect = main.tooltipRect("Ask your opponent to undo (Z)", pos, screen)
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

    def test_a_tap_shows_no_tooltip(self):
        """A touch screen's tap lands and clicks in the same frame: the tapped control's tooltip stays hidden."""
        main = self.main
        shown, restore = self.recordShown()
        seen = {}
        undo = main.panelLayout(0, False)['undo'].center

        async def script():
            await asyncio.sleep(1.0)
            self.mouse[0] = self.square(4, 4)
            await asyncio.sleep(0.2)
            await self.tap(undo, 1.0)  # nothing to take back yet: the tap changes nothing
            seen['after the tap'] = list(shown['tooltip'])
            self.mouse[0] = self.square(4, 4)
            await asyncio.sleep(0.2)
            self.mouse[0] = undo
            await asyncio.sleep(0.9)
            seen['resting on it'] = list(shown['tooltip'])
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        async def run():
            await asyncio.gather(main.main(), script())

        try:
            asyncio.run(run())
        finally:
            restore()
        self.assertEqual(seen['after the tap'], [], "no tooltip after a tap")
        self.assertIn(main.tooltipText('undo'), seen['resting on it'], "the pointer resting on it still shows it")

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

    def test_admin_has_unlimited_hints(self):
        main = self.main
        import hints
        from account import account
        for _ in range(hints.HINTS_PER_DAY):
            hints.use()
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            hint = main.panelLayout(0, False)['hint'].center
            await self.click(hint, 2.5)
            seen['first'] = any(text.startswith("Hint: ") for text in shown['status'])
            await self.move((6, 4), (4, 4), 3.0)  # the computer answers
            shown['status'].clear()
            await self.click(hint, 2.5)
            seen['second'] = any(text.startswith("Hint: ") for text in shown['status'])
            seen['left'] = hints.remaining()
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        shown, restore = self.recordShown()
        account.profile = {'id': 'A', 'username': 'congduytran12', 'rating': 1200, 'rated_games': 0, 'admin': True}
        try:
            self.assertTrue(account.isAdmin)
            self.assertEqual(main.hintsLeft(), math.inf)
            self.runGame(script)
        finally:
            account.profile = None
            restore()
            hints._store({})
            hints._saved = None
        self.assertTrue(seen['first'] and seen['second'], "two hints")
        self.assertNotIn("No hints left today", shown['status'])
        self.assertEqual(seen['left'], 0, "the day's count is left alone")
        self.assertFalse(account.isAdmin, "signed out")

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

    async def tap(self, pos, wait=0.3):
        """A full click: the button goes down and up at pos (the move list selects on release)."""
        self.mouse[0] = pos
        p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=pos))
        p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=pos))
        await asyncio.sleep(wait)

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
        light = tuple(main.BOARD_COLORS[0])
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

    def test_a_tap_on_the_prompts_box_selects_no_move_under_it(self):
        main = self.main
        seen = {}
        moves = [((6, 4), (4, 4)), ((1, 4), (3, 4)), ((7, 6), (5, 5)), ((0, 1), (2, 2)), ((7, 5), (4, 2)),
                 ((0, 5), (3, 2)), ((6, 2), (5, 2)), ((0, 6), (2, 5)), ((6, 3), (5, 3)), ((1, 3), (2, 3)),
                 ((6, 7), (5, 7)), ((1, 7), (2, 7)), ((6, 0), (5, 0)), ((1, 0), (2, 0)), ((6, 1), (4, 1)),
                 ((3, 2), (1, 0))]

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[1].center, 0.5)
            for start, end in moves:
                await self.move(start, end, 0.15)
            layout = main.panelLayout(1, False)
            await self.click(layout['draw'].center, 0.3)  # White offers a draw
            box, accept, decline = main.promptRects()
            listTop, listBottom = main.panelAreas(min(r.y for r in layout.values()), False)['list']
            cells = main.moveListLayout(len(moves), listTop, listBottom)['cells']
            points = [(box.centerx, accept.centery), (accept.centerx, accept.bottom + 5)]  # between, below the buttons
            seen['over moves'] = [any(rect.collidepoint(point) for rect, _ in cells) for point in points]
            for point in points:
                await self.tap(point, 0.3)
            seen['shown'] = len(frames[-1][0])
            await self.click(decline.center, 0.3)  # the prompt was still open
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        shown, restoreShown = self.recordShown()
        try:
            self.runGame(script)
        finally:
            restoreShown()
            restore()
        self.assertEqual(seen['over moves'], [True, True], "the taps are over moves in the list")
        self.assertEqual(seen['shown'], len(moves), "no looking back")
        self.assertIn("Draw declined", shown['status'])

    def test_how_to_play_closes_an_open_dropdown(self):
        # H opens How to play over an open dropdown: the options go (in portrait they'd cover its buttons)
        main = self.main
        seen = {}
        marks = []
        realMark = main.drawCheckMark

        def recordMark(screen, rect):
            marks.append(p.time.get_ticks())
            return realMark(screen, rect)

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.panelLayout(0, False)['clock'].center, 0.3)
            seen['open'] = bool(marks)
            await self.key(p.K_h, 'h', 0.3)
            del marks[:]
            await asyncio.sleep(0.2)
            seen['help'] = (pages[-1], len(marks))
            await self.key(p.K_ESCAPE, '', 0.3)
            del marks[:]
            await asyncio.sleep(0.2)
            seen['closed'] = (pages[-1], len(marks))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        pages, restore = self.recordHelpPages()
        main.drawCheckMark = recordMark
        try:
            self.runGame(script)
        finally:
            main.drawCheckMark = realMark
            restore()
        self.assertTrue(seen['open'], "the Clock dropdown's options showed")
        self.assertEqual(seen['help'], (0, 0), "How to play, and no options over it")
        self.assertEqual(seen['closed'], (None, 0), "nor after it closes")

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
            # clicking the first move in the log shows the position after it (on release: a drag would scroll)
            await self.tap(main.moveListLayout(2, main.STRIP_HEIGHT, 400)['cells'][0][0].center)
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

    # --- step 6: sounds and the "Your move" alert

    def fakeSounds(self):
        """Replaces the game's sounds with recorders; returns (plays, restore). plays lists the names played."""
        main = self.main
        plays = []

        class FakeSound:
            def __init__(self, name):
                self.name, self.volume = name, 1.0

            def set_volume(self, volume):
                self.volume = volume

            def get_volume(self):
                return self.volume

            def play(self):
                plays.append(self.name)

        saved = dict(main.SOUNDS)
        main.SOUNDS.clear()
        main.SOUNDS.update({name: FakeSound(name) for name in main.SOUND_FILES})

        def restore():
            main.SOUNDS.clear()
            main.SOUNDS.update(saved)
        return plays, restore

    def test_new_sounds_are_loaded(self):
        for name in ('move', 'capture', 'promote', 'check', 'game-start', 'game-end', 'low-time', 'notify'):
            self.assertIn(name, self.main.SOUNDS)
            self.assertLess(self.main.SOUNDS[name].get_length(), 0.7, name)

    def test_move_sound_names(self):
        main = self.main

        def soundOf(fen, code):
            gs = support.fromFen(fen)
            moves = gs.getValidMoves()
            move = gs.findMoveByCode(code, moves)
            gs.makeMoveWithSan(move, moves)
            return main.moveSoundName(move)

        start = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        self.assertEqual(soundOf(start, "e2e4"), 'move')
        self.assertEqual(soundOf('4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1', "e4d5"), 'capture')
        self.assertEqual(soundOf('8/P7/7k/8/8/8/8/K7 w - - 0 1', "a7a8q"), 'promote')
        self.assertEqual(soundOf('4k3/8/8/8/8/8/8/R3K3 w - - 0 1', "a1a8"), 'check')
        self.assertEqual(soundOf('3qk3/8/8/8/8/8/8/3RK3 w - - 0 1', "d1d8"), 'check', "a capture giving check")
        self.assertEqual(soundOf('6k1/P7/8/8/8/8/8/K7 w - - 0 1', "a7a8q"), 'check', "a promotion giving check")

    def test_play_sound_respects_sound_and_volume(self):
        main = self.main
        plays, restore = self.fakeSounds()
        try:
            self.settings.put('volume', 30)
            self.assertTrue(main.playSound('check'))
            self.assertAlmostEqual(main.SOUNDS['check'].volume, 0.3)
            self.settings.put('sound', False)
            self.assertFalse(main.playSound('move'))
            self.settings.put('sound', True)
            self.settings.put('volume', 0)
            self.assertFalse(main.playSound('move'))
            self.settings.put('volume', 80)
            self.assertFalse(main.playSound('no such sound'))

            def broken():
                raise RuntimeError("no device")
            main.SOUNDS['notify'].play = broken
            self.assertFalse(main.playSound('notify'), "a failing sound doesn't raise")
            self.assertEqual(plays, ['check'])
        finally:
            restore()
            self.resetSwitches()

    def test_low_time_sides(self):
        sides = self.main.lowTimeSides
        self.assertEqual(sides({'w': 9000, 'b': 9000}, 'wb', set()), ['w', 'b'])
        self.assertEqual(sides({'w': 9000, 'b': 9000}, 'w', set()), ['w'], "only this device's players")
        self.assertEqual(sides({'w': 9000, 'b': 20000}, 'wb', {'w'}), [], "once per side")
        self.assertEqual(sides({'w': 0, 'b': 10000}, 'wb', set()), [], "a fallen flag or 10 s exactly isn't low")

    def test_game_sounds_start_end_and_low_time(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            seen['launch'] = list(plays)
            await self.chooseTwoPlayers()  # a mode change starts a game
            seen['mode'] = list(plays)
            del plays[:]
            for start, end in (((6, 5), (5, 5)), ((1, 4), (3, 4)), ((6, 6), (4, 6)), ((0, 3), (4, 7))):
                await self.move(start, end)
            await asyncio.sleep(0.3)
            seen['mate'] = list(plays)
            await self.click(self.square(0, 0))  # hides and shows the result card: no more sounds
            await self.click(self.square(0, 0))
            await self.key(p.K_z, 'z')  # take the mate back and give it again: still the same game
            await self.move((0, 3), (4, 7), 0.5)
            seen['mate again'] = list(plays)
            del plays[:]
            newGame = main.resultCardLayout("Black wins by checkmate", ['new'])[2]['new']
            await self.click(newGame.center, 0.5)
            seen['new game'] = list(plays)
            # a 1+0 clock with "low" set just under a minute: each side's clock goes low once
            clockRect = main.panelLayout(1, False)['clock']
            await self.click(clockRect.center)
            await self.click(main.dropdownOptionRects(clockRect, len(main.CLOCK_OPTIONS))[1].center, 0.3)
            del plays[:]
            await self.move((6, 4), (4, 4), 0.8)  # the clocks start with the first move: Black's runs
            await self.move((1, 4), (3, 4), 0.8)
            await self.move((6, 3), (4, 3), 0.8)
            await self.move((1, 3), (3, 3), 0.8)
            seen['low time'] = list(plays)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        plays, restore = self.fakeSounds()
        savedLow = main.LOW_TIME_MS
        main.LOW_TIME_MS = 59500
        try:
            self.runGame(script)
        finally:
            restore()
            main.LOW_TIME_MS = savedLow
        self.assertEqual(seen['launch'], [], "opening the game is quiet")
        self.assertEqual(seen['mode'], ['game-start'])
        self.assertEqual(seen['mate'], ['move', 'move', 'move', 'check', 'game-end'])
        self.assertEqual(seen['mate again'].count('game-end'), 1, "the end is heard once per game")
        self.assertEqual(seen['new game'], ['game-start'])
        self.assertEqual(seen['low time'].count('low-time'), 2, seen['low time'])

    def test_your_move_title_when_the_window_is_not_focused(self):
        main = self.main
        seen = {}

        def focus(gained):
            p.event.post(p.event.Event(main.WINDOW_FOCUS_GAINED if gained else main.WINDOW_FOCUS_LOST))

        async def script():
            await asyncio.sleep(1.0)
            seen['start'] = p.display.get_caption()[0]
            await self.move((6, 4), (4, 4), 0.2)  # 1.e4, and the player looks at another window
            focus(False)
            await asyncio.sleep(2.0)
            seen['away'] = (p.display.get_caption()[0], list(plays))
            focus(True)
            await asyncio.sleep(0.3)
            seen['back'] = p.display.get_caption()[0]
            # away again: the alert goes when the player moves (the turn passes), even without focus
            await self.move((6, 3), (4, 3), 0.2)
            focus(False)
            await asyncio.sleep(2.0)
            seen['away again'] = p.display.get_caption()[0]
            await self.move((7, 6), (5, 5), 0.3)
            seen['moved'] = p.display.get_caption()[0]
            focus(True)
            # focused: the computer's reply changes nothing
            await asyncio.sleep(2.0)
            seen['focused'] = (p.display.get_caption()[0], plays.count('notify'))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        plays, restore = self.fakeSounds()
        try:
            self.runGame(script, thinkMs=1000)
        finally:
            restore()
        self.assertEqual(seen['start'], main.GAME_TITLE)
        title, played = seen['away']
        self.assertEqual(title, "Your move · Chess Playing AI")
        self.assertEqual(played.count('notify'), 1)
        self.assertEqual(seen['back'], main.GAME_TITLE)
        self.assertEqual(seen['away again'], main.YOUR_MOVE_TITLE)
        self.assertEqual(seen['moved'], main.GAME_TITLE)
        self.assertEqual(seen['focused'], (main.GAME_TITLE, 2))

    def test_premove_while_away_is_not_your_move(self):
        # the premove is played for the player, so the computer's reply doesn't call them back
        import browser
        main = self.main
        seen = {}
        titles = []
        realTitle = browser.setTitle

        async def script():
            await asyncio.sleep(1.0)
            await self.move((6, 4), (4, 4), 0.4)  # 1.e4; the computer thinks for at least 1.5 s
            await self.move((6, 0), (5, 0), 0.3)  # premove a2-a3, then look at another window
            p.event.post(p.event.Event(main.WINDOW_FOCUS_LOST))
            await asyncio.sleep(2.5)
            seen['away'] = (frames[-1][0], list(plays), list(titles))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restoreBoards = self.recordBoards()
        plays, restoreSounds = self.fakeSounds()
        browser.setTitle = lambda text: titles.append(text) or realTitle(text)
        try:
            self.runGame(script, thinkMs=1500)
        finally:
            browser.setTitle = realTitle
            restoreSounds()
            restoreBoards()
        log, played, changed = seen['away']
        self.assertEqual(log[2:3], ["a2a3"], "the premove was played")
        self.assertNotIn('notify', played)
        self.assertNotIn(main.YOUR_MOVE_TITLE, changed)

    def test_turn_arrived(self):
        arrived = self.main.turnArrived
        self.assertTrue(arrived(0, True, 1, 2, False), "the computer moved")
        self.assertTrue(arrived(2, True, 3, 4, False), "the online opponent moved")
        self.assertFalse(arrived(1, True, 1, 2, False), "two players on one screen")
        self.assertFalse(arrived(0, False, 0, 1, False), "the player's own move")
        self.assertFalse(arrived(0, True, 2, 0, False), "a new game or an undo")
        self.assertFalse(arrived(0, True, 1, 2, True), "the game is over")

    def test_online_sounds_and_your_move_alert(self):
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

        def opponentState(**changes):
            state = dict([m for m in sent if m.get('type') == 'state'][-1])
            state.update({'role': 'client', 'sender': 'guest'})
            state.update(changes)
            return state

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            seen['online mode'] = list(plays)  # no room yet, so no game
            await self.click(main.panelLayout(2, False)['host'].center, 0.5)  # the host plays White
            seen['hosted'] = list(plays)
            await self.move((6, 4), (4, 4), 0.5)
            p.event.post(p.event.Event(main.WINDOW_FOCUS_LOST))  # the host looks at another window
            await asyncio.sleep(0.2)
            del plays[:]
            state = opponentState()
            net.incoming_messages.append(opponentState(version=state['version'] + 1, moves="e2e4 e7e5"))
            await asyncio.sleep(0.6)
            seen['their move'] = (p.display.get_caption()[0], list(plays))
            p.event.post(p.event.Event(main.WINDOW_FOCUS_GAINED))
            await asyncio.sleep(0.3)
            seen['back'] = p.display.get_caption()[0]
            # they resign; the same state again (a heartbeat) changes nothing
            del plays[:]
            resigned = opponentState(version=state['version'] + 2, moves="e2e4 e7e5",
                                     result=["White wins by resignation", "1-0"])
            net.incoming_messages.append(resigned)
            await asyncio.sleep(0.5)
            net.incoming_messages.append(dict(resigned))
            await asyncio.sleep(0.5)
            seen['resigned'] = list(plays)
            # and start the next game
            del plays[:]
            net.incoming_messages.append(opponentState(game=resigned['game'] + 1, version=0, moves="", result=None,
                                                       gid="nextgame"))
            await asyncio.sleep(0.5)
            seen['next game'] = list(plays)
            del plays[:]
            await self.click(main.panelLayout(2, True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            seen['left'] = list(plays)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        plays, restore = self.fakeSounds()
        net.set_topic, net.send = fakeSetTopic, fakeSend
        try:
            self.runGame(script)
        finally:
            restore()
            net.set_topic, net.send = realSetTopic, realSend
            net.running = False
            if os.path.exists(network.SESSION_FILE):
                os.remove(network.SESSION_FILE)  # no Rejoin row for the other tests
        self.assertEqual(seen['online mode'], [])
        self.assertEqual(seen['hosted'], ['game-start'], "hosting a room starts a game")
        self.assertEqual(seen['their move'], (main.YOUR_MOVE_TITLE, ['move', 'notify']))
        self.assertEqual(seen['back'], main.GAME_TITLE)
        self.assertEqual(seen['resigned'], ['game-end'], "an online result is heard once")
        self.assertEqual(seen['next game'], ['game-start'])
        self.assertEqual(seen['left'], [], "leaving the room starts no game")

    def test_joining_a_room_plays_the_start_once(self):
        main = self.main
        import network
        net = network.net
        seen = {}
        realSetTopic, realSend = net.set_topic, net.send

        def fakeSetTopic(topic):
            net.topic = "chess_app_multiplayer_" + str(topic)
            net.running = True
            net.last_status = "SYNC HEALTHY"

        async def fakeSend(data):
            pass

        def hostState(game, version, moves):
            return {'type': 'state', 'game': game, 'version': version, 'role': 'host', 'sender': 'host-of-test',
                    'gid': "game%d" % game, 'moves': moves, 'tc': None, 'clocks': None, 'result': None}

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['room'].center)
            for letter in "ab12":
                await self.key(getattr(p, 'K_' + letter), letter, 0.05)
            del plays[:]
            await self.click(main.panelLayout(2, False)['join'].center, 0.3)
            seen['joined'] = list(plays)
            # the host is already on its third game, with no moves yet: catching up with it isn't another start
            net.incoming_messages.append(hostState(2, 0, ""))
            await asyncio.sleep(0.5)
            seen['caught up'] = list(plays)
            del plays[:]
            net.incoming_messages.append(hostState(3, 0, ""))  # the host starts the next game
            await asyncio.sleep(0.5)
            seen['next game'] = list(plays)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        plays, restore = self.fakeSounds()
        net.set_topic, net.send = fakeSetTopic, fakeSend
        try:
            self.runGame(script)
        finally:
            restore()
            net.set_topic, net.send = realSetTopic, realSend
            net.running = False
            if os.path.exists(network.SESSION_FILE):
                os.remove(network.SESSION_FILE)  # no Rejoin row for the other tests
        self.assertEqual(seen['joined'], ['game-start'], "joining a room starts a game")
        self.assertEqual(seen['caught up'], ['game-start'], "and catching up doesn't play it again")
        self.assertEqual(seen['next game'], ['game-start'])


    # --- step D: the move list, figurines, the evaluation graph and the analysis summary

    def longGamePgn(self, plies=70):
        """PGN text of a made-up game of plies random moves that isn't over, and its final GameState."""
        import random
        import pgn
        main = self.main
        for seed in range(100):
            rng = random.Random(seed)
            gs = support.GameState()
            moves = gs.getValidMoves()
            history = [gs.getPositionKey()]
            for _ in range(plies):
                if not moves:
                    break
                moves = gs.makeMoveWithSan(rng.choice(moves), moves)
                main.updatePositionHistory(gs, history)
            if len(gs.moveLog) == plies and moves and main.getOutcome(gs, history, None) is None:
                return pgn.buildPgn(gs.moveLog, [("White", "A"), ("Black", "B"), ("Result", "*")], '*'), gs
        self.fail("no unfinished random game")

    def test_move_list_layout(self):
        main = self.main
        top = main.STRIP_HEIGHT
        layout = main.moveListLayout(5, top, 600)
        self.assertEqual((layout['rows'], layout['first'], layout['track']), (3, 0, None), "all fits: no scrollbar")
        cells = dict((ply, rect) for rect, ply in layout['cells'])
        self.assertEqual(sorted(cells), [0, 1, 2, 3, 4])
        for ply, rect in cells.items():  # one row per move number: White's move left, Black's right
            self.assertEqual(rect.x, main.MOVE_COLUMNS[ply % 2], ply)
            self.assertEqual(rect.y, top + main.MOVE_LIST_PADDING + ply // 2 * main.MOVE_ROW_HEIGHT, ply)
            self.assertEqual(main.moveListPly(layout, rect.center), ply)
        self.assertEqual([number for number, _ in layout['numbers']], [1, 2, 3])
        self.assertIsNone(main.moveListPly(layout, (main.MOVE_COLUMNS[1] + 10, cells[4].centery)), "no 3... yet")
        self.assertIsNone(main.moveListPly(layout, (main.PANEL_X + 10, cells[0].centery)), "the move number")
        # a long game: newest rows at the bottom, scrolled back from there, and following the shown move
        bottom = top + main.MOVE_LIST_PADDING + 5 * main.MOVE_ROW_HEIGHT
        newest = main.moveListLayout(70, top, bottom)
        self.assertEqual((newest['rows'], newest['visible'], newest['first'], newest['scroll']), (35, 5, 30, 0))
        self.assertEqual(newest['cells'][-1][1], 69)
        self.assertEqual(main.moveListLayout(70, top, bottom, 4)['first'], 26)
        self.assertEqual(main.moveListLayout(70, top, bottom, 99)['scroll'], 30, "clamped")
        self.assertEqual(main.moveListLayout(70, top, bottom, -3)['scroll'], 0)
        self.assertEqual(main.moveListLayout(70, top, bottom, 0, follow=0)['first'], 0)
        self.assertEqual(main.moveListLayout(70, top, bottom, 0, follow=-1)['first'], 0, "the start position")
        self.assertEqual(main.moveListLayout(70, top, bottom, 30, follow=69)['first'], 30)
        self.assertEqual(main.moveListLayout(70, top, bottom, 10, follow=41)['first'], 20, "already in view")
        self.assertEqual(main.moveListLayout(70, top, bottom, 10, follow=51)['first'], 21, "scrolls just enough")

    def test_scrollbar_geometry(self):
        main = self.main
        top = main.STRIP_HEIGHT
        bottom = top + main.MOVE_LIST_PADDING + 8 * main.MOVE_ROW_HEIGHT
        newest = main.moveListLayout(80, top, bottom)  # 40 rows, 8 shown
        track, thumb = newest['track'], newest['thumb']
        self.assertTrue(track.right <= main.PANEL_X + main.MOVE_LOG_PANEL_WIDTH - 8 and track.width <= 8, "thin")
        self.assertTrue(track.contains(thumb))
        self.assertAlmostEqual(thumb.height, track.height * 8 / 40, delta=1)
        self.assertEqual(thumb.bottom, track.bottom, "the newest rows: the thumb at the bottom")
        self.assertEqual(main.moveListLayout(80, top, bottom, 32)['thumb'].top, track.top)
        for scroll in range(33):  # dragging the thumb to where it is keeps the scroll
            layout = main.moveListLayout(80, top, bottom, scroll)
            self.assertEqual(main.scrollForThumb(layout, layout['thumb'].y), scroll)
        self.assertEqual(main.scrollForThumb(newest, -500), 32)
        self.assertEqual(main.scrollForThumb(newest, 5000), 0)
        middle = main.moveListLayout(80, top, bottom, 16)
        thumb = middle['thumb']
        self.assertEqual(main.scrollbarPart(middle, thumb.center), 'thumb')
        self.assertEqual(main.scrollbarPart(middle, (thumb.centerx + 6, thumb.centery)), 'thumb', "a wider grip")
        self.assertEqual(main.scrollbarPart(middle, (thumb.centerx, thumb.top - 3)), 'before')
        self.assertEqual(main.scrollbarPart(middle, (thumb.centerx, thumb.bottom + 3)), 'after')
        self.assertIsNone(main.scrollbarPart(middle, (thumb.centerx - 40, thumb.centery)))
        self.assertIsNone(main.scrollbarPart(main.moveListLayout(6, top, bottom), (thumb.centerx, thumb.centery)))
        self.assertEqual(main.scrollForPage(middle, 'before'), 24, "a page of older moves")
        self.assertEqual(main.scrollForPage(middle, 'after'), 8)
        self.assertEqual(main.scrollForListDrag(5, 2 * main.MOVE_ROW_HEIGHT + 3), 7, "down: older moves")
        self.assertEqual(main.scrollForListDrag(5, -main.MOVE_ROW_HEIGHT), 4)

    def test_move_list_scrolls_with_the_wheel_thumb_track_and_drags(self):
        main = self.main
        import pgn
        text, final = self.longGamePgn(70)
        lists = []
        realDraw = main.drawMoveList
        seen = {}

        def record(screen, layout, *args, **kwargs):
            lists.append(layout)
            return realDraw(screen, layout, *args, **kwargs)

        async def wheel(steps):
            self.mouse[0] = (main.PANEL_X + 150, 200)
            for _ in range(abs(steps)):
                p.event.post(p.event.Event(p.MOUSEWHEEL, x=0, y=1 if steps > 0 else -1, flipped=False))
            await asyncio.sleep(0.3)

        async def pressDrag(start, end, steps=6):
            self.mouse[0] = start
            p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=start))
            await asyncio.sleep(0.1)
            for i in range(1, steps + 1):
                pos = (round(start[0] + (end[0] - start[0]) * i / steps),
                       round(start[1] + (end[1] - start[1]) * i / steps))
                self.mouse[0] = pos
                p.event.post(p.event.Event(p.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0)))
                await asyncio.sleep(0.04)
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=end))
            await asyncio.sleep(0.3)

        async def script():
            await asyncio.sleep(1.0)
            await self.chooseTwoPlayers()
            pgn._loadedText = text
            await asyncio.sleep(0.6)
            seen['loaded'] = (lists[-1]['rows'], lists[-1]['first'] + lists[-1]['visible'],
                              lists[-1]['track'] is not None)
            first = lists[-1]['first']
            await wheel(3)
            seen['wheel'] = first - lists[-1]['first']
            thumb = lists[-1]['thumb']
            await pressDrag(thumb.center, (thumb.centerx, 0))
            seen['thumb'] = lists[-1]['first']
            track = lists[-1]['track']
            await self.tap((track.centerx, track.bottom - 2))
            seen['page'] = (lists[-1]['first'], lists[-1]['visible'])
            before = lists[-1]['first']
            await pressDrag((main.PANEL_X + 150, 200), (main.PANEL_X + 150, 200 - 2 * main.MOVE_ROW_HEIGHT - 4))
            seen['list drag'] = (lists[-1]['first'] - before, len(frames[-1][0]))
            rect, ply = lists[-1]['cells'][3]
            await self.tap(rect.center)
            seen['tap'] = (len(frames[-1][0]), ply + 1)
            await self.key(p.K_END)
            await wheel(2)
            before = lists[-1]['first']
            move = next(m for m in final.getValidMoves() if not m.isPawnPromotion)
            await self.move((move.startRow, move.startCol), (move.endRow, move.endCol))
            seen['new move'] = (len(frames[-1][0]), before, lists[-1]['first'])
            await wheel(-5)
            seen['back down'] = lists[-1]['first'] + lists[-1]['visible']
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        main.drawMoveList = record
        try:
            self.runGame(script)
        finally:
            restore()
            main.drawMoveList = realDraw
        self.assertEqual(seen['loaded'], (35, 35, True), "the newest row shows, with a scrollbar")
        self.assertEqual(seen['wheel'], 3)
        self.assertEqual(seen['thumb'], 0, "the thumb dragged to the top: the first moves")
        self.assertEqual(seen['page'][0], seen['page'][1], "a click below the thumb pages down")
        self.assertEqual(seen['list drag'], (2, 70), "dragging the list up shows newer moves and selects nothing")
        self.assertEqual(seen['tap'][0], seen['tap'][1], "a tap on a move shows the position after it")
        self.assertEqual(seen['new move'][0], 71)
        self.assertEqual(seen['new move'][1], seen['new move'][2], "scrolled back, a new row leaves the view alone")
        self.assertEqual(seen['back down'], 36, "and scrolled down again, the newest row shows")

    def test_figurine_notation(self):
        main, settings = self.main, self.settings
        p.init()
        main.loadImages()
        self.assertEqual(main.sanParts("Nf3"), [('piece', 'N'), ('text', "f3")])
        self.assertEqual(main.sanParts("Bxb7+"), [('piece', 'B'), ('text', "xb7+")])
        self.assertEqual(main.sanParts("exd8=Q#"), [('text', "exd8="), ('piece', 'Q'), ('text', "#")])
        self.assertEqual(main.sanParts("O-O-O"), [('text', "O-O-O")])
        black = (0, 0, 0)

        def bright(surface):  # pixels of a white piece's light body (the text is black)
            w, h = surface.get_size()
            return sum(1 for x in range(w) for y in range(h)
                       if surface.get_at((x, y))[3] > 200 and min(surface.get_at((x, y))[:3]) > 200)

        letters = main.sanSurface("Nf3", 'w', 19, black, figurines=False)
        self.assertIs(letters, main.get_text_surface("Nf3", 19, black, False))
        figure = main.sanSurface("Nf3", 'w', 19, black, figurines=True)
        self.assertIs(figure, main.sanSurface("Nf3", 'w', 19, black, figurines=True), "cached")
        self.assertGreater(bright(figure), 10, "a white knight is drawn")
        self.assertEqual(bright(letters), 0)
        self.assertEqual(bright(main.sanSurface("Nf3", 'b', 19, black, figurines=True)), 0, "a black one for Black")
        self.assertGreater(bright(main.sanSurface("e8=Q", 'w', 19, black, figurines=True)), 10, "the promotion piece")
        self.assertIs(main.sanSurface("e4", 'w', 19, black, figurines=True),
                      main.get_text_surface("e4", 19, black, False), "a pawn move has no piece letter")
        # the move list follows the Notation switch
        gs = support.GameState()
        moves = gs.getValidMoves()
        gs.makeMoveWithSan(gs.findMoveBySan("Nf3", moves), moves)
        layout = main.moveListLayout(1, main.STRIP_HEIGHT, 400)
        cell = layout['cells'][0][0]
        saved = dict(main.UI)
        try:
            main.UI['text'] = black
            for value in (False, True):
                settings.put('figurines', value)
                surface = p.Surface((main.BOARD_WIDTH + main.MOVE_LOG_PANEL_WIDTH, main.BOARD_HEIGHT))
                main.drawMoveList(surface, layout, gs.moveLog)
                self.assertEqual(bright(surface.subsurface(cell)) > 10, value, value)
        finally:
            settings.put('figurines', settings.DEFAULTS['figurines'])
            main.UI.clear()
            main.UI.update(saved)

    def test_eval_graph_geometry_and_panel_rows(self):
        main = self.main
        rows = main.panelRows(0, False, reviewing=True)
        graphRows = main.panelRows(0, False, reviewing=True, graph=True)
        self.assertEqual(rows[3], ['analyze'])
        self.assertEqual(graphRows[3], ['graph'], "the graph takes the Analyze game row's place")
        self.assertEqual(rows[:3] + rows[4:], graphRows[:3] + graphRows[4:])
        before, after = main.panelLayout(0, False, False, True), main.panelLayout(0, False, False, True, True)
        graph = after['graph']
        self.assertEqual((graph.height, graph.width), (main.GRAPH_HEIGHT, main.CONTROL_WIDTH))
        self.assertGreaterEqual(main.GRAPH_HEIGHT, 2 * main.ROW_HEIGHT)
        for name in ('first', 'undo', 'menu'):
            self.assertEqual(before[name], after[name], name)
        self.assertEqual(before['mode'].y - after['mode'].y, main.GRAPH_HEIGHT - main.ROW_HEIGHT)
        self.assertEqual(graph.bottom + main.ROW_GAP, after['first'].y)
        self.assertTrue(main.tooltipText('graph'))
        chart = main.graphChart(graph)
        self.assertTrue(graph.contains(chart))
        plies = 41
        xs = [main.graphX(graph, ply, plies) for ply in range(plies + 1)]
        self.assertEqual((xs[0], xs[-1]), (chart.x, chart.right - 1))
        self.assertEqual(xs, sorted(xs))
        for ply, x in enumerate(xs):
            self.assertEqual(main.graphPly(graph, plies, x), ply)
        self.assertEqual(main.graphPly(graph, plies, graph.x - 50), 0)
        self.assertEqual(main.graphPly(graph, plies, graph.right + 50), plies)
        self.assertEqual(main.graphPly(graph, 0, graph.centerx), 0)
        self.assertAlmostEqual(main.graphY(graph, 0), chart.centery, delta=1)
        self.assertEqual(main.graphY(graph, 500), chart.y, "capped: a mate is the top")
        self.assertEqual(main.graphY(graph, main.EVAL_CAP), chart.y)
        self.assertEqual(main.graphY(graph, -main.EVAL_CAP - 3), chart.bottom - 1)
        ys = [main.graphY(graph, score / 2) for score in range(-24, 25)]
        self.assertEqual(ys, sorted(ys, reverse=True), "White's advantage is up")
        self.assertLess(main.graphY(graph, 1), main.graphY(graph, 0) - 5, "a pawn up shows")

    def test_eval_graph_fills_in_and_a_click_shows_that_move(self):
        main = self.main
        seen = {}
        graphs = []
        realGraph = main.drawEvalGraph
        savedSeconds = main.ANALYSIS_SECONDS

        def record(screen, rect, evals, plies, marks, shownPly, done=True):
            graphs.append((len(evals), plies, shownPly, done))
            return realGraph(screen, rect, evals, plies, marks, shownPly, done)

        async def script():
            await asyncio.sleep(1.0)
            await self.chooseTwoPlayers()
            for start, end in (((6, 5), (5, 5)), ((1, 4), (3, 4)), ((6, 6), (4, 6)), ((0, 3), (4, 7))):
                await self.move(start, end)
            await asyncio.sleep(0.3)
            seen['before'] = len(graphs)
            await self.tap(main.panelLayout(1, False, False, True)['analyze'].center, 0.05)
            seen['first frame'] = graphs[0] if graphs else None
            for _ in range(100):
                if graphs and graphs[-1][3]:
                    break
                await asyncio.sleep(0.1)
            seen['done'] = graphs[-1]
            rect = main.panelLayout(1, False, False, True, True)['graph']
            await self.tap((main.graphX(rect, 1, 4), rect.centery))
            seen['click'] = (frames[-1][0], graphs[-1][2])
            start = (main.graphX(rect, 1, 4), rect.centery)
            self.mouse[0] = start
            p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=start))
            await asyncio.sleep(0.1)
            for ply in (2, 3):
                self.mouse[0] = (main.graphX(rect, ply, 4), rect.centery + 30)  # below the graph still follows x
                p.event.post(p.event.Event(p.MOUSEMOTION, pos=self.mouse[0], rel=(0, 0), buttons=(1, 0, 0)))
                await asyncio.sleep(0.1)
            seen['drag'] = len(frames[-1][0])
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(0.1)
            self.mouse[0] = (main.graphX(rect, 0, 4), rect.centery)
            p.event.post(p.event.Event(p.MOUSEMOTION, pos=self.mouse[0], rel=(0, 0), buttons=(0, 0, 0)))
            await asyncio.sleep(0.2)
            seen['released'] = len(frames[-1][0])
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordBoards()
        main.drawEvalGraph = record
        main.ANALYSIS_SECONDS = 0.05
        try:
            self.runGame(script)
        finally:
            restore()
            main.drawEvalGraph = realGraph
            main.ANALYSIS_SECONDS = savedSeconds
        self.assertEqual(seen['before'], 0, "no graph before Analyze game")
        self.assertIsNotNone(seen['first frame'])
        self.assertFalse(seen['first frame'][3], "the graph shows while the analysis runs")
        self.assertLess(seen['first frame'][0], 5)
        self.assertEqual(seen['done'][:2], (5, 4))
        self.assertEqual(seen['click'], (["f2f3"], 1), "a click shows the position at that point")
        self.assertEqual(seen['drag'], 3, "dragging follows the pointer")
        self.assertEqual(seen['released'], 3, "and stops when the button is let go")

    def test_analysis_summary(self):
        main = self.main
        self.assertEqual(main.analysisSummary({}), "No mistakes found")
        marks = {0: ("??", 3.2), 2: ("?", 1.6), 4: ("?", 2.0), 3: ("?!", 0.9)}
        self.assertEqual(main.analysisSummary(marks), "White: 1 blunder, 2 mistakes · Black: 1 inaccuracy")
        self.assertEqual(main.analysisSummary({1: ("?!", 1.0), 5: ("?!", 0.8), 7: ("??", 4.0)}),
                         "White: no mistakes · Black: 1 blunder, 2 inaccuracies")
        self.assertEqual(main.analysisSummary(marks, compact=True), "White 1??, 2? · Black 1?!")
        self.assertEqual(main.analysisSummary({1: ("?", 2.0)}, compact=True), "White none · Black 1?")


    # --- step 7: text fields, paste, the account window, forgot password

    def recordAccountWindow(self):
        """Records drawAccountWindow's view, message, scroll and form fields each frame; returns (frames, restore)."""
        main = self.main
        frames = []
        real = main.drawAccountWindow

        def record(screen, view, fields, focus, message, busy, account, rows, mouse_pos, tone='error', scroll=0,
                   showPassword=False, thumbHeld=False, resetEmail=None):
            frames.append({'view': view, 'message': message, 'tone': tone, 'scroll': scroll, 'rows': len(rows),
                           'focus': focus, 'values': {name: field.value for name, field in fields.items()},
                           'caret': fields[focus].caret if focus in fields else None, 'shown': showPassword,
                           'resetEmail': resetEmail})
            return real(screen, view, fields, focus, message, busy, account, rows, mouse_pos, tone, scroll,
                        showPassword, thumbHeld, resetEmail)

        def restore():
            main.drawAccountWindow = real
        main.drawAccountWindow = record
        return frames, restore

    def fakeAccount(self, **methods):
        """Replaces account methods with the given functions until the returned restore() is called."""
        from account import account
        saved = {name: getattr(account, name) for name in methods}
        saved.update(profile=account.profile, stats=account.stats)
        for name, function in methods.items():
            setattr(account, name, function)

        def restore():
            for name in methods:
                delattr(account, name)  # back to the class's method
            account.profile, account.stats = saved['profile'], saved['stats']
        return account, restore

    async def typeText(self, text, wait=0.02):
        for ch in text:
            await self.key(ord(ch.lower()) if ch.isalpha() else ord(ch), ch, wait)
        await asyncio.sleep(0.1)

    def test_room_code_from_pasted_text(self):
        main = self.main
        self.assertEqual(main.roomCodeFromText("https://chess-playing-ai.vercel.app/?room=AB12CD"), "AB12CD")
        self.assertEqual(main.roomCodeFromText("Join me! https://x.app/?lang=en&room=qx7rt2#top"), "QX7RT2")
        self.assertEqual(main.roomCodeFromText("  ab-12 cd\n"), "AB-12CD")
        self.assertEqual(main.roomCodeFromText("https://example.com/somewhere"), "", "a link without a room")
        self.assertEqual(main.roomCodeFromText("x" * 30), "X" * main.ROOM_CODE_LENGTH)
        from textfield import TextField
        field = TextField("ZZ", maxLength=main.ROOM_CODE_LENGTH, allowed=main.ROOM_CODE_CHARACTERS,
                          transform=str.upper, onPaste=main.pasteRoomCode)
        field.paste("https://chess-playing-ai.vercel.app/?room=AB12CD")
        self.assertEqual(field.value, "AB12CD", "an invite link replaces the box's text with its code")
        field.moveCaret(2)
        field.paste("x y")
        self.assertEqual((field.value, field.caret), ("ABXY12CD", 4), "a plain code goes in at the caret")

    def test_reset_link_from_hash(self):
        main = self.main
        self.assertEqual(main.resetLinkFromHash("#access_token=a.b.c&expires_in=3600&refresh_token=r1"
                                                "&token_type=bearer&type=recovery"),
                         {'token': 'a.b.c', 'refresh': 'r1'})
        self.assertIsNone(main.resetLinkFromHash("access_token=a&refresh_token=r&type=signup"))
        self.assertIsNone(main.resetLinkFromHash(""))
        expired = main.resetLinkFromHash("error=access_denied&error_code=otp_expired&error_description=Email+link")
        self.assertIn("expired", expired['error'])
        # anyone can link to the site with any text after the #: it is never shown
        made = main.resetLinkFromHash("error_code=x&error_description=Your+account+is+locked.+Visit+evil.example")
        self.assertEqual(made, {'error': "That email link didn't work. Ask for a new one"})
        email = base64.urlsafe_b64encode(json.dumps({'email': "duy@example.com"}).encode()).decode().rstrip('=')
        self.assertEqual(main.resetLinkFromHash("access_token=h.%s.s&refresh_token=r&type=recovery" % email),
                         {'token': "h.%s.s" % email, 'refresh': 'r', 'email': "duy@example.com"})
        self.assertIsNone(main.tokenEmail("h.!!.s"))
        self.assertTrue(main.hashHasSignIn("#access_token=a&refresh_token=r&type=signup"), "a confirmation link")
        self.assertFalse(main.hashHasSignIn("#error_code=otp_expired"))
        self.assertFalse(main.hashHasSignIn(""))

    def test_account_windows_fit_their_content(self):
        main = self.main
        for view in main.ACCOUNT_FORMS + ('profile', 'games', 'leaderboard'):
            with self.subTest(view=view):
                rects = main.accountLayout(view, 5)
                box = rects['box']
                self.assertTrue(p.Rect(0, 0, main.BOARD_WIDTH, main.BOARD_HEIGHT).contains(box), "over the board")
                controls = {name: rect for name, rect in rects.items() if name not in ('box', 'close', 'signOut')
                            and not name.startswith('toggle:')}
                for name, rect in controls.items():
                    self.assertTrue(box.contains(rect), name)
                above = max(rect.bottom for rect in controls.values())
                self.assertLessEqual(rects['close'].top - above, 3 * main.ROW_GAP, "no empty gap above Close")
                self.assertEqual(box.bottom - rects['close'].bottom, 24)
        signin = main.accountLayout('signin')
        self.assertLess(signin['box'].height, 500, "the sign-in form is shorter than the old fixed window")
        self.assertTrue(signin['field:password'].contains(signin['toggle:password']), "Show sits in the field")
        self.assertGreater(signin['forgot'].top, signin['switch'].bottom, "Forgot password? under the form")
        self.assertEqual(main.accountLayout('profile', 1)['box'].height + 4 * main.ACCOUNT_STAT_ROW,
                         main.accountLayout('profile', 5)['box'].height, "the profile grows with its results")

    def test_saved_games_list_geometry(self):
        main = self.main
        visible = main.ACCOUNT_LIST_ROWS['games']
        top = main.accountListLayout('games', 50, 0)
        self.assertEqual((top['first'], len(top['cells'])), (0, visible))
        self.assertTrue(top['track'].contains(top['thumb']) and top['thumb'].top == top['track'].top)
        bottom = main.accountListLayout('games', 50, 999)
        self.assertEqual(bottom['first'], 50 - visible, "clamped to the last page")
        self.assertEqual(bottom['thumb'].bottom, bottom['track'].bottom)
        for scroll in range(0, 50 - visible + 1):  # dragging the thumb to where it is keeps the scroll
            layout = main.accountListLayout('games', 50, scroll)
            self.assertEqual(main.firstRowForThumb(layout, layout['thumb'].y), scroll)
        few = main.accountListLayout('games', 3, 5)
        self.assertEqual((few['first'], few['track'], len(few['cells'])), (0, None, 3))
        rects = main.accountLayout('games', 50, 10)
        self.assertIn('row:10', rects)
        self.assertNotIn('row:9', rects)

    def test_sign_in_fields_caret_show_password_and_paste(self):
        main = self.main
        import browser
        seen = {}
        realClipboard = browser.clipboardText

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.panelLayout(0, False)['account'].center, 0.3)
            seen['view'] = frames[-1]['view']
            await self.typeText("duy@example.com")
            login = main.accountLayout('signin')['field:login']
            font = main.get_font(main.FIELD_TEXT_SIZE, False)
            await self.click((login.x + main.FIELD_PADDING + font.size("duy")[0] + 1, login.centery), 0.1)
            await self.typeText("_t")
            seen['caret'] = (frames[-1]['values']['login'], frames[-1]['caret'])
            p.event.post(p.event.Event(p.KEYDOWN, key=p.K_TAB, unicode="\t", mod=0, scancode=0))
            browser.clipboardText = lambda: "pass word\n"
            p.event.post(p.event.Event(p.KEYDOWN, key=p.K_v, unicode="\x16", mod=p.KMOD_LCTRL, scancode=0))
            await asyncio.sleep(0.3)
            seen['paste'] = (frames[-1]['focus'], frames[-1]['values']['password'], frames[-1]['shown'])
            self.mouse[0] = main.accountLayout('signin')['field:login'].center
            await asyncio.sleep(0.2)
            seen['ibeam'] = main.CURSOR[0]
            await self.click(main.accountLayout('signin')['toggle:password'].center, 0.2)
            seen['shown'] = frames[-1]['shown']
            seen['toggle cursor'] = main.CURSOR[0]
            await self.key(p.K_ESCAPE)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordAccountWindow()
        try:
            self.runGame(script)
        finally:
            restore()
            browser.clipboardText = realClipboard
        self.assertEqual(seen['view'], 'signin')
        self.assertEqual(seen['caret'], ("duy_t@example.com", 5), "a click put the caret after 'duy'")
        self.assertEqual(seen['paste'], ('password', "pass word", False), "Ctrl+V pasted into the focused field")
        self.assertEqual(seen['ibeam'], 'ibeam')
        self.assertTrue(seen['shown'], "Show reveals the password")
        self.assertEqual(seen['toggle cursor'], 'hand', "Show is a button in the field")

    def test_forgot_password_view(self):
        main = self.main
        import browser
        calls = []
        seen = {}

        async def recover(email, redirectTo=None):
            calls.append((email, redirectTo))

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.panelLayout(0, False)['account'].center, 0.3)
            await self.typeText("someone@")
            await self.click(main.accountLayout('signin')['forgot'].center, 0.3)
            seen['open'] = (frames[-1]['view'], frames[-1]['values']['email'])
            await self.key(p.K_RETURN, "\r")
            seen['invalid'] = (frames[-1]['message'], list(calls))
            await self.typeText("someone@example.com")
            seen['typing clears it'] = frames[-1]['message']
            await self.click(main.accountLayout('forgot')['submit'].center, 0.4)
            seen['sent'] = (frames[-1]['message'], frames[-1]['tone'], list(calls))
            await self.click(main.accountLayout('forgot')['switch'].center, 0.3)
            seen['back'] = frames[-1]['view']
            await self.key(p.K_ESCAPE)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordAccountWindow()
        account, restoreAccount = self.fakeAccount(recover=recover)
        try:
            self.runGame(script)
        finally:
            restore()
            restoreAccount()
        self.assertEqual(seen['open'], ('forgot', ""), "a login without a full email isn't copied over")
        self.assertEqual(seen['invalid'], ("That doesn't look like an email address", []))
        self.assertEqual(seen['typing clears it'], "")
        self.assertEqual(seen['sent'], (main.RESET_LINK_SENT, 'success',
                                        [("someone@example.com", browser.siteUrl())]))
        self.assertEqual(seen['back'], 'signin')

    def test_reset_link_opens_the_new_password_view(self):
        import browser
        calls = []
        cleared = []
        seen = {}
        realHash, realClear = browser.locationHash, browser.clearLocationHash

        async def setPassword(token, password, refresh=None):
            calls.append((token, password, refresh))
            account.profile = {'id': 'U1', 'username': 'Duy_T', 'rating': 1200, 'rated_games': 0}

        async def loadStats():
            pass

        async def script():
            await asyncio.sleep(1.0)
            seen['start'] = (frames[-1]['view'], frames[-1]['resetEmail'], list(cleared))
            await self.typeText("short")
            await self.key(p.K_RETURN, "\r")
            seen['short'] = (frames[-1]['message'], list(calls))
            await self.typeText("-but-ok")
            await self.key(p.K_RETURN, "\r", 0.5)
            seen['saved'] = (frames[-1]['view'], list(calls), list(cleared))
            await self.key(p.K_ESCAPE)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        token = "h." + base64.urlsafe_b64encode(json.dumps({'email': "duy@example.com"}).encode()).decode().rstrip('=')
        browser.locationHash = lambda: "access_token=%s.s&refresh_token=ref&type=recovery" % token
        browser.clearLocationHash = lambda: cleared.append(True)
        frames, restore = self.recordAccountWindow()
        account, restoreAccount = self.fakeAccount(setPassword=setPassword, loadStats=loadStats)
        try:
            self.runGame(script)
        finally:
            restore()
            restoreAccount()
            browser.locationHash, browser.clearLocationHash = realHash, realClear
        self.assertEqual(seen['start'], ('newPassword', "duy@example.com", [True]),
                         "the page opened from the reset email asks for the password of the account it names, and "
                         "the link left the address bar at once")
        self.assertEqual(seen['short'], ("Passwords need at least 8 characters", []))
        self.assertEqual(seen['saved'], ('profile', [(token + ".s", "short-but-ok", "ref")], [True]),
                         "saved and signed in")

    def test_saved_games_scroll_and_open(self):
        main = self.main
        seen = {}
        opened = []
        windowFrames = []  # frames drawn with the account window open, per frame of the game
        rows = [{'id': i, 'played_at': '2026-10-01', 'mode': 'local', 'result': '1-0', 'color': None,
                 'opponent': 'Game %d' % i} for i in range(50)]

        async def listGames():
            return rows

        async def loadStats():
            pass

        async def loadGame(gameId):
            opened.append(gameId)
            return '[Result "*"]\n\n1. e4 *\n'

        async def wheel(steps):
            for _ in range(abs(steps)):
                p.event.post(p.event.Event(p.MOUSEWHEEL, x=0, y=1 if steps > 0 else -1, flipped=False))
            await asyncio.sleep(0.3)

        async def pressDrag(start, end, steps=8):
            self.mouse[0] = start
            p.event.post(p.event.Event(p.MOUSEBUTTONDOWN, button=1, pos=start))
            await asyncio.sleep(0.1)
            for i in range(1, steps + 1):
                self.mouse[0] = (round(start[0] + (end[0] - start[0]) * i / steps),
                                 round(start[1] + (end[1] - start[1]) * i / steps))
                p.event.post(p.event.Event(p.MOUSEMOTION, pos=self.mouse[0], rel=(0, 0), buttons=(1, 0, 0)))
                await asyncio.sleep(0.03)
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=end))
            await asyncio.sleep(0.3)

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.panelLayout(0, False)['account'].center, 0.3)
            await self.tap(main.accountLayout('profile', 0)['games'].center, 0.4)
            seen['open'] = (frames[-1]['view'], frames[-1]['rows'], frames[-1]['scroll'])
            self.mouse[0] = main.accountLayout('games', 50)['list'].center
            await wheel(-3)
            seen['wheel'] = frames[-1]['scroll']
            await wheel(10)
            seen['wheel back'] = frames[-1]['scroll']
            layout = main.accountListLayout('games', 50, 0)
            thumb = layout['thumb']
            await pressDrag(thumb.center, (thumb.centerx, layout['track'].bottom + 40))
            seen['thumb'] = frames[-1]['scroll']
            # dragging the list down shows newer games and opens nothing
            start = main.accountListLayout('games', 50, seen['thumb'])['cells'][2][0].center
            await pressDrag(start, (start[0], start[1] + 4 * main.ACCOUNT_ROW_HEIGHT))
            seen['list drag'] = (frames[-1]['scroll'], list(opened))
            rect, index = main.accountListLayout('games', 50, frames[-1]['scroll'])['cells'][0]
            await self.tap(rect.center, 0.5)
            seen['tap'] = (index, list(opened), windowFrames[-1])
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        frames, restore = self.recordAccountWindow()
        account, restoreAccount = self.fakeAccount(listGames=listGames, loadStats=loadStats, loadGame=loadGame)
        account.profile = {'id': 'U1', 'username': 'Duy_T', 'rating': 1200, 'rated_games': 0}
        account.stats = {}
        realFrame = main.drawGameState
        counted = [0]

        def countFrames(*args, **kwargs):  # whether the window was drawn since the last board
            windowFrames.append(len(frames) != counted[0])
            counted[0] = len(frames)
            return realFrame(*args, **kwargs)
        main.drawGameState = countFrames
        try:
            self.runGame(script)
        finally:
            restore()
            restoreAccount()
            main.drawGameState = realFrame
        visible = main.ACCOUNT_LIST_ROWS['games']
        self.assertEqual(seen['open'], ('games', 50, 0))
        self.assertEqual(seen['wheel'], 3 * main.ACCOUNT_LIST_WHEEL, "the wheel scrolls down to older games")
        self.assertEqual(seen['wheel back'], 0, "and back up, stopping at the newest")
        self.assertEqual(seen['thumb'], 50 - visible, "the thumb dragged to the bottom: the oldest games")
        self.assertEqual(seen['list drag'], (50 - visible - 4, []), "dragging scrolled and opened nothing")
        self.assertEqual(seen['tap'][:2], (50 - visible - 4, [50 - visible - 4]), "a tap opens that game")
        self.assertFalse(seen['tap'][2], "and the window closed")

    def test_room_box_typing_caret_and_pasted_invite_link(self):
        main = self.main
        import browser
        import network
        net = network.net
        seen = {}
        values = []
        topics = []
        realDraw = main.drawTextField
        realClipboard = browser.clipboardText
        realSetTopic, realSend = net.set_topic, net.send

        def record(screen, rect, field, focused, *args, **kwargs):
            if kwargs.get('placeholder'):
                values.append((field.value, field.caret, focused))
            return realDraw(screen, rect, field, focused, *args, **kwargs)

        def fakeSetTopic(topic):
            topics.append(topic)
            net.topic = "chess_app_multiplayer_" + str(topic)
            net.running = True
            net.last_status = "SYNC HEALTHY"

        async def fakeSend(data):
            pass

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            room = main.panelLayout(2, False)['room']
            self.mouse[0] = room.center
            await asyncio.sleep(0.2)
            seen['cursor'] = main.CURSOR[0]
            await self.click(room.center, 0.2)
            await self.typeText("ab-1 2!")
            seen['typed'] = values[-1]
            await self.key(p.K_HOME)
            await self.typeText("z")
            seen['home'] = values[-1]
            browser.clipboardText = lambda: "https://chess-playing-ai.vercel.app/?room=QX7RT2"
            p.event.post(p.event.Event(p.KEYDOWN, key=p.K_v, unicode="\x16", mod=p.KMOD_CTRL, scancode=0))
            await asyncio.sleep(0.3)
            seen['pasted'] = values[-1]
            await self.key(p.K_RETURN, "\r")
            seen['enter'] = values[-1]
            await self.click(main.panelLayout(2, False)['join'].center, 0.3)
            await self.click(main.panelLayout(2, True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        main.drawTextField = record
        net.set_topic, net.send = fakeSetTopic, fakeSend
        try:
            self.runGame(script)
        finally:
            main.drawTextField = realDraw
            browser.clipboardText = realClipboard
            net.set_topic, net.send = realSetTopic, realSend
            net.running = False
            if os.path.exists(network.SESSION_FILE):
                os.remove(network.SESSION_FILE)  # no Rejoin row for the other tests
        self.assertEqual(seen['cursor'], 'ibeam')
        self.assertEqual(seen['typed'], ("AB-12", 5, True), "uppercase, only room code characters")
        self.assertEqual(seen['home'], ("ZAB-12", 1, True), "typed at the caret")
        self.assertEqual(seen['pasted'][:2], ("QX7RT2", 6), "the invite link's code replaced the text")
        self.assertFalse(seen['enter'][2], "Enter leaves the box")
        self.assertEqual(topics, ["QX7RT2"], "Join used the pasted code")

    # --- step 8: invite links, joining from a link, quick chat

    def offlineRoom(self, echo=True):
        """Replaces ntfy with a room only this test talks to; returns (sent, topics, restore). Like ntfy, it hands
        our sync_request back to us (stamped with the room's latest time), unless echo is False."""
        import network
        net = network.net
        sent, topics = [], []
        realSetTopic, realSend = net.set_topic, net.send

        def fakeSetTopic(topic):
            topics.append(topic)
            net.topic = "chess_app_multiplayer_" + str(topic)
            net.running = True
            net.last_status = "SYNC HEALTHY"
            net.server_time = 0

        async def fakeSend(data):
            sent.append(dict(data))
            if echo and data.get('type') == 'sync_request':
                net.incoming_messages.append(dict(data, _time=net.server_time))

        def restore():
            net.set_topic, net.send = realSetTopic, realSend
            net.running = False
            if os.path.exists(network.SESSION_FILE):
                os.remove(network.SESSION_FILE)  # no Rejoin row for the other tests
        net.set_topic, net.send = fakeSetTopic, fakeSend
        return sent, topics, restore

    def openedWithRoomParam(self, value):
        """Makes the game start as if the page's address had ?room=value; returns (removed, restore)."""
        import browser
        params = {'room': value}
        removed = []
        realQuery, realRemove = browser.queryParam, browser.removeQueryParam

        def removeQueryParam(name):
            removed.append(name)
            params.pop(name, None)
        browser.queryParam = lambda name: params.get(name)
        browser.removeQueryParam = removeQueryParam

        def restore():
            browser.queryParam, browser.removeQueryParam = realQuery, realRemove
        return removed, restore

    def test_invite_url_is_built_and_read_back(self):
        main = self.main
        import browser
        site = "https://chess-playing-ai.vercel.app/"
        self.assertEqual(main.inviteUrl(site, "AB12CD"), "https://chess-playing-ai.vercel.app/?room=AB12CD")
        self.assertEqual(main.inviteUrl("http://127.0.0.1:8870/index.html", "x-_9"),
                         "http://127.0.0.1:8870/index.html?room=x-_9")
        self.assertEqual(main.inviteUrl("https://a.app/?lang=en", "Q1"), "https://a.app/?lang=en&room=Q1")
        for code in ("AB12CD", "QX7-RT_2", "Z" * main.ROOM_CODE_LENGTH):
            self.assertEqual(main.roomCodeFromText(main.inviteUrl(site, code)), code)
        self.assertEqual(browser.siteUrl(), browser.SITE_URL, "on desktop the link points at the public site")
        self.assertEqual(browser.paramFromUrl(main.inviteUrl(site, "AB12CD"), 'room'), "AB12CD")

    def test_incoming_chat_filter(self):
        main = self.main
        chat = main.incomingChat

        def msg(**changes):
            message = {'type': 'chat', 'id': 2, 'role': 'client', '_time': 1000}
            message.update(changes)
            return message
        self.assertEqual(chat(msg(), 'client', 1000, 990), 2)
        self.assertEqual(chat(msg(), 'client', 1000 + main.CHAT_FRESH_SECONDS, 990), 2, "30 s old still shows")
        self.assertIsNone(chat(msg(), 'client', 1001 + main.CHAT_FRESH_SECONDS, 990), "history replayed on joining")
        self.assertIsNone(chat(msg(), 'host', 1000, 990), "our own role")
        self.assertIsNone(chat(msg(role=None), 'client', 1000, 990))
        self.assertIsNone(chat(msg(type='ping'), 'client', 1000, 990))
        for bad in (-1, len(main.QUICK_CHAT), "2", 2.0, True, None):
            self.assertIsNone(chat(msg(id=bad), 'client', 1000, 990), bad)
        self.assertEqual(chat(msg(id=len(main.QUICK_CHAT) - 1), 'client', 1000, 990), len(main.QUICK_CHAT) - 1)
        self.assertIsNone(chat(msg(_time=None), 'client', 1000, 990), "no server time: can't tell how old it is")
        self.assertIsNone(chat(msg(), 'client', None, 990))
        # the room's newest message may be an old chat: it is history if it came before we joined
        self.assertIsNone(chat(msg(), 'client', 1000, None), "our sync_request hasn't come back yet")
        self.assertIsNone(chat(msg(), 'client', 1000, 1600), "sent 10 min before we joined")
        self.assertEqual(chat(msg(), 'client', 1000, 1000 + main.CHAT_FRESH_SECONDS), 2, "just before we joined")

    def test_malformed_online_messages_are_ignored(self):
        # anyone with the room's code can post to it: nothing they send may stop the game
        main = self.main
        info = main.onlinePlayerInfo
        self.assertEqual(info({'uid': "u1", 'name': "alice_9", 'rating': 1500}),
                         {'uid': "u1", 'name': "alice_9", 'rating': 1500})
        self.assertEqual(info({'uid': "u1", 'name': "a\x00b\u202ec", 'rating': 1500})['name'], "abc",
                         "a name keeps only the characters usernames have (a NUL can't be drawn)")
        self.assertEqual(info({'uid': "u1", 'name': "\x00"})['name'], "?")
        for rating in (json.loads("1e999"), float('nan'), "1500", True, [1]):
            self.assertIsNone(info({'uid': "u1", 'name': "x", 'rating': rating}), rating)
        self.assertIsNone(info({'name': "x"}), "no account")
        self.assertIsNone(info("player"))

        good = {'type': 'state', 'game': 0, 'version': 3, 'moves': "e2e4 e7e5", 'tc': [300, 0],
                'clocks': {'w': 290000, 'b': 300000.5}, 'result': ["White wins by resignation", "1-0"]}
        self.assertTrue(main.wellFormedState(good))
        self.assertTrue(main.wellFormedState(dict(good, tc=None, clocks=None, result=None, moves=None)))
        for change in ({'tc': ["5+0", 0]}, {'tc': [300]}, {'tc': [json.loads("1e999"), 0]}, {'tc': [-1, 0]},
                       {'tc': "300"}, {'clocks': {'w': "x"}}, {'clocks': {'w': float('nan')}}, {'clocks': [1, 2]},
                       {'result': ["White\x00", "1-0"]}, {'result': ["White wins", 1]}, {'result': "1-0"},
                       {'moves': ["e2e4"]}):
            self.assertFalse(main.wellFormedState(dict(good, **change)), change)

    def test_chat_rate_limit_and_bubble_layout(self):
        main = self.main
        p.font.init()  # the bubble is measured in its font
        self.assertTrue(main.chatReady(500, None), "nothing sent yet")
        self.assertFalse(main.chatReady(10000, 10000))
        self.assertFalse(main.chatReady(10000 + main.CHAT_INTERVAL_MS - 1, 10000))
        self.assertTrue(main.chatReady(10000 + main.CHAT_INTERVAL_MS, 10000))
        self.assertEqual(main.disabledReason('chat', chatWait=True), "Wait a moment")
        self.assertIsNone(main.disabledReason('chat'))
        panel = p.Rect(main.PANEL_X, 0, main.MOVE_LOG_PANEL_WIDTH, main.BOARD_HEIGHT)
        stripY = 450
        for text in main.QUICK_CHAT:
            top, tail = main.chatBubbleLayout(text, 0, True)
            self.assertTrue(panel.contains(top), "never over the board")
            self.assertGreater(top.top, main.STRIP_HEIGHT, "below the upper strip")
            self.assertTrue(all(y >= main.STRIP_HEIGHT - 1 for _, y in tail), "its tail reaches up to the strip")
            bottom, tail = main.chatBubbleLayout(text, stripY, False)
            self.assertTrue(panel.contains(bottom))
            self.assertLess(bottom.bottom, stripY, "above the lower strip")
            self.assertTrue(all(y <= stripY for _, y in tail))
            fits = main.get_font(main.CHAT_TEXT_SIZE, True, True).size(text)[0] <= bottom.width - 28
            self.assertTrue(fits, text)
            lifted, _ = main.chatBubbleLayout(text, stripY, False, lift=50)
            self.assertEqual(lifted.bottom, bottom.bottom - 50, "it rises above a status message")
        # the lower bubble clears the status message, and after the game the review info (the result) too
        controlsTop = min(rect.y for rect in main.panelLayout(2, True).values())
        for gameOver in (False, True):
            areas = main.panelAreas(controlsTop, gameOver)
            stripY = areas['bottomStrip'].y
            for statusShown in (False, True):
                rect, _ = main.chatBubbleLayout("Good game!", stripY, False,
                                                main.chatBubbleLift(areas, statusShown, gameOver))
                where = (gameOver, statusShown)
                if gameOver:
                    self.assertFalse(rect.colliderect(areas['info']), (where, "the result stays readable"))
                if statusShown:
                    self.assertFalse(rect.colliderect(areas['status']), where)
        host = main.panelLayout(2, True)
        self.assertIn('invite', host)
        guest = main.panelLayout(2, True, guest=True)
        self.assertNotIn('invite', guest, "only the host invites")
        self.assertEqual((host['chat'].y, host['hint'].y), (host['invite'].y, host['invite'].y), "one row")
        self.assertEqual(guest['chat'].y, guest['hint'].y)
        self.assertAlmostEqual(guest['chat'].width, guest['hint'].width, delta=1, msg="half the row each")
        for layout in (host, guest):
            for rect in main.chatItemRects(layout['chat']).values():
                self.assertTrue(panel.contains(rect), "the chat list stays in the panel")
                self.assertLess(rect.bottom, layout['chat'].top)
        self.assertTrue(main.tooltipText('invite') and main.tooltipText('chat'))

    def test_invite_link_opens_the_join_prompt(self):
        main = self.main
        texts = []
        seen = {}
        realFitting = main.get_fitting_text

        def recordText(text, *args, **kwargs):
            texts.append(text)
            return realFitting(text, *args, **kwargs)

        async def script():
            await asyncio.sleep(1.0)
            seen['start'] = ("Join room TEST12 as Black?" in texts, list(removed), list(topics))
            _, join, _ = main.promptRects()
            self.mouse[0] = join.center
            await asyncio.sleep(0.2)
            seen['cursor'] = main.CURSOR[0]
            await self.click(join.center, 0.5)
            seen['joined'] = (list(topics), [m['role'] for m in sent if m.get('type') == 'sync_request'])
            await self.click(main.panelLayout(2, True, guest=True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        removed, restoreParam = self.openedWithRoomParam("test12")
        main.get_fitting_text = recordText
        try:
            self.runGame(script)
        finally:
            main.get_fitting_text = realFitting
            restoreParam()
            restoreRoom()
        self.assertEqual(seen['start'], (True, ['room'], []), "the prompt asks first; the link left the address")
        self.assertEqual(seen['cursor'], 'hand')
        self.assertEqual(seen['joined'], (["TEST12"], ['client']), "Join connects as the guest")

    def test_invite_link_prompt_cancel_keeps_the_code(self):
        main = self.main
        values = []
        seen = {}
        realDraw = main.drawTextField

        def record(screen, rect, field, focused, *args, **kwargs):
            values.append(field.value)
            return realDraw(screen, rect, field, focused, *args, **kwargs)

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.promptRects()[2].center, 0.4)  # Cancel
            seen['cancelled'] = (values[-1], list(topics))
            await self.click(main.panelLayout(2, False)['join'].center, 0.4)  # the code is there to join with
            seen['joined'] = list(topics)
            await self.click(main.panelLayout(2, True, guest=True)['restart'].center)
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        removed, restoreParam = self.openedWithRoomParam("https://example.app/?room=ab-12")
        main.drawTextField = record
        try:
            self.runGame(script)
        finally:
            main.drawTextField = realDraw
            restoreParam()
            restoreRoom()
        self.assertEqual(seen['cancelled'], ("AB-12", []), "online setup with the room box filled in")
        self.assertEqual(seen['joined'], ["AB-12"])

    def test_invite_link_cancel_then_host_makes_a_new_room(self):
        # the invited room is the friend's: hosting instead (to play White) must not join it as a second host
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            await self.click(main.promptRects()[2].center, 0.4)  # Cancel
            await self.click(main.panelLayout(2, False)['host'].center, 0.4)
            seen['hosted'] = list(topics)
            await self.click(main.panelLayout(2, True)['restart'].center)
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        removed, restoreParam = self.openedWithRoomParam("FRIEND")
        try:
            self.runGame(script)
        finally:
            restoreParam()
            restoreRoom()
        self.assertEqual(len(seen['hosted']), 1)
        self.assertNotEqual(seen['hosted'][0], "FRIEND", "a room of its own")
        self.assertEqual(len(seen['hosted'][0]), 6)

    def test_chat_from_the_rooms_history_stays_hidden(self):
        # the backlog's newest message is an old chat (both players left after 'Good game!'); only when our own
        # sync_request comes back does the room's clock say how old it is
        main = self.main
        import network
        net = network.net
        seen = {}
        bubbles = []
        realBubble = main.drawChatBubble

        def recordBubble(screen, text, *args, **kwargs):
            bubbles.append(text)
            return realBubble(screen, text, *args, **kwargs)

        def hostMessage(**fields):
            message = {'role': 'host', 'sender': 'host-of-test', 'game': 0, 'version': 1}
            message.update(fields)
            net.server_time = max(net.server_time, fields['_time'])
            net.incoming_messages.append(message)

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['room'].center)
            for letter in "ab12":
                await self.key(getattr(p, 'K_' + letter), letter, 0.05)
            await self.click(main.panelLayout(2, False)['join'].center, 0.3)
            # the backlog: the host's game, then their chat
            hostMessage(type='state', gid="old", moves="e2e4", tc=None, clocks=None, result=None, _time=1000)
            hostMessage(type='chat', id=2, _time=1005)
            await asyncio.sleep(0.4)
            seen['backlog'] = list(bubbles)
            echo = dict([m for m in sent if m.get('type') == 'sync_request'][-1], _time=1600)
            net.server_time = 1600
            net.incoming_messages.append(echo)  # our sync_request comes back, 10 min later
            await asyncio.sleep(0.3)
            hostMessage(type='chat', id=0, _time=1601)  # a fresh one shows
            await asyncio.sleep(0.4)
            seen['fresh'] = sorted(set(bubbles))
            await self.click(main.panelLayout(2, True, guest=True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom(echo=False)
        main.drawChatBubble = recordBubble
        try:
            self.runGame(script)
        finally:
            main.drawChatBubble = realBubble
            restoreRoom()
        self.assertEqual(seen['backlog'], [], "the old 'Good game!' doesn't pop up")
        self.assertEqual(seen['fresh'], ["Hello!"])

    def test_next_game_started_by_the_guest_plays_the_start(self):
        # the host never adopted a state of the guest's (it resigned before the guest moved), yet the guest's new
        # game is a start, not catching up
        main = self.main
        import network
        net = network.net
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['host'].center, 0.5)
            await self.move((6, 4), (4, 4), 0.4)
            await self.click(main.panelLayout(2, True)['resign'].center)
            await self.click(main.promptRects()[1].center, 0.4)
            state = dict([m for m in sent if m.get('type') == 'state'][-1])
            seen['result'] = state.get('result')
            del plays[:]
            state.update({'role': 'client', 'sender': 'guest', 'game': state['game'] + 1, 'version': 0,
                          'moves': "", 'result': None, 'gid': "nextgame"})
            net.incoming_messages.append(state)
            await asyncio.sleep(0.5)
            seen['next game'] = list(plays)
            await self.click(main.panelLayout(2, True)['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        plays, restore = self.fakeSounds()
        try:
            self.runGame(script)
        finally:
            restore()
            restoreRoom()
        self.assertIsNotNone(seen['result'], "the host resigned")
        self.assertEqual(seen['next game'], ['game-start'])

    def test_hint_in_an_online_game(self):
        main = self.main
        import hints
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['host'].center, 0.5)
            layout = main.panelLayout(2, True)
            await self.click(layout['hint'].center, 2.5)  # the host plays White: their turn
            seen['hint'] = {text for text in shown['status'] if text.startswith("Hint: ")}
            seen['left'] = hints.remaining()
            await self.move((6, 4), (4, 4), 0.5)
            await self.click(layout['hint'].center, 0.3)  # now it's the guest's turn
            seen['waiting'] = shown['status'][-1]
            await self.click(layout['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        shown, restoreShown = self.recordShown()
        try:
            self.runGame(script)
        finally:
            restoreShown()
            restoreRoom()
            hints._store({})
            hints._saved = None
        self.assertEqual(len(seen['hint']), 1, "the hint was shown")
        self.assertEqual(seen['left'], hints.HINTS_PER_DAY - 1, "and counted")
        self.assertEqual(seen['waiting'], "Wait for your turn")

    def test_copy_link_and_quick_chat(self):
        main = self.main
        import browser
        import network
        net = network.net
        seen = {}
        copied = []
        copyWorks = [True]
        bubbles = []  # (ticks, text, below) of every bubble drawn
        realCopy, realResult, realBubble = browser.copyText, browser.copyResult, main.drawChatBubble
        answers = []  # the browser's later answers to a copy (copyText returned None)
        saved = (main.CHAT_BUBBLE_MS, main.CHAT_INTERVAL_MS)

        def fakeCopy(text):
            copied.append(text)
            return copyWorks[0]

        def fakeCopyResult():
            return answers.pop(0) if answers else None

        def recordBubble(screen, text, stripY, below, age=0, lift=0, span=None):
            bubbles.append((p.time.get_ticks(), text, below))
            return realBubble(screen, text, stripY, below, age, lift, span)

        def bubblesSince(ticks):
            return sorted({(text, below) for at, text, below in bubbles if at >= ticks})

        def opponentChat(index, sentAt):
            message = {'type': 'chat', 'id': index, 'role': 'client', 'sender': 'guest', 'game': 0, 'version': 0,
                       '_time': sentAt}
            net.server_time = max(net.server_time, sentAt)
            net.incoming_messages.append(message)

        async def script():
            await asyncio.sleep(1.0)
            modeRect = main.panelLayout(0, False)['mode']
            await self.click(modeRect.center)
            await self.click(main.dropdownOptionRects(modeRect, len(main.MODE_OPTIONS))[2].center, 0.5)
            await self.click(main.panelLayout(2, False)['host'].center, 0.5)
            layout = main.panelLayout(2, True)
            await self.click(layout['invite'].center, 0.3)
            copyWorks[0] = False
            await self.click(layout['invite'].center, 0.3)
            seen['refused'] = shown['status'][-1]
            copyWorks[0] = None  # a browser that answers later: no answer for two frames, then copied
            answers[:] = [None, None, True]
            await self.click(layout['invite'].center, 0.3)
            seen['later'] = shown['status'][-1]
            seen['copied'] = list(copied)
            seen['room'] = topics[-1]
            await self.click(layout['chat'].center, 0.3)
            await self.click(main.chatItemRects(layout['chat'])[1].center, 0.3)
            seen['sent'] = [(m['id'], m['role']) for m in sent if m.get('type') == 'chat']
            seen['own'] = bubblesSince(p.time.get_ticks() - 200)
            await self.click(layout['chat'].center, 0.3)  # too soon: it says why, and sends nothing
            await self.click(main.chatItemRects(layout['chat'])[2].center, 0.3)
            seen['too soon'] = len([m for m in sent if m.get('type') == 'chat'])
            opponentChat(4, 1000)
            opponentChat(2, 900)  # older than 30 s: the room's history
            await asyncio.sleep(0.3)
            seen['both'] = bubblesSince(p.time.get_ticks() - 150)
            await asyncio.sleep(main.CHAT_BUBBLE_MS / 1000 + 0.2)
            seen['gone'] = bubblesSince(p.time.get_ticks() - 150)
            await self.click(layout['chat'].center, 0.3)  # ready again
            await self.click(main.chatItemRects(layout['chat'])[6].center, 0.3)
            seen['again'] = [m['id'] for m in sent if m.get('type') == 'chat']
            await self.click(layout['restart'].center)  # leave the room
            await self.click(main.promptRects()[1].center, 0.3)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.5)

        sent, topics, restoreRoom = self.offlineRoom()
        shown, restoreShown = self.recordShown()
        browser.copyText, browser.copyResult, main.drawChatBubble = fakeCopy, fakeCopyResult, recordBubble
        main.CHAT_BUBBLE_MS, main.CHAT_INTERVAL_MS = 2000, 2500
        try:
            self.runGame(script)
        finally:
            browser.copyText, browser.copyResult, main.drawChatBubble = realCopy, realResult, realBubble
            main.CHAT_BUBBLE_MS, main.CHAT_INTERVAL_MS = saved
            restoreShown()
            restoreRoom()
        link = main.inviteUrl(browser.SITE_URL, seen['room'])
        self.assertEqual(seen['copied'], [link, link, link])
        self.assertIn("Invite link copied: send it to your friend", shown['status'])
        self.assertEqual(seen['refused'], "Couldn't copy the link: share the room code " + seen['room'])
        self.assertEqual(seen['later'], "Invite link copied: send it to your friend", "the browser's later answer")
        self.assertEqual(seen['sent'], [(1, 'host')])
        self.assertEqual(seen['own'], [("Good luck!", False)], "by our own strip, at the bottom")
        self.assertIn("Wait a moment", shown['status'])
        self.assertEqual(seen['too soon'], 1)
        self.assertEqual(seen['both'], [("Good luck!", False), ("Well played!", True)],
                         "the opponent's by their strip at the top; the old one isn't shown")
        self.assertEqual(seen['gone'], [], "the bubbles time out")
        self.assertEqual(seen['again'], [1, 6])

    # --- step 9: How to play on the first visit, captured pieces readable in both themes, the desktop window

    def recordHelpPages(self):
        """Records the page drawHelpWindow shows each frame (None when the window is closed); returns (pages, restore)."""
        main = self.main
        pages = []
        realHelp, realDraw = main.drawHelpWindow, main.drawGameState

        def recordHelp(screen, page, mouse_pos):
            pages[-1] = page
            return realHelp(screen, page, mouse_pos)

        def recordFrame(*args, **kwargs):  # every frame draws the board first
            pages.append(None)
            return realDraw(*args, **kwargs)
        main.drawHelpWindow, main.drawGameState = recordHelp, recordFrame

        def restore():
            main.drawHelpWindow, main.drawGameState = realHelp, realDraw
        return pages, restore

    def test_how_to_play_opens_on_the_first_visit(self):
        main = self.main
        seen = {}

        async def firstVisit():
            await asyncio.sleep(0.8)
            seen['opened'] = (pages[-1], self.settings.get('seenHelp'))
            await self.key(p.K_RIGHT)
            await self.click(main.helpLayout()['close'].center, 0.4)  # closing it in any way
            seen['closed'] = (pages[-1], self.settings.get('seenHelp'))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        async def nextVisit():
            await asyncio.sleep(0.8)
            seen['next'] = [page for page in pages if page is not None]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        async def escape():
            await asyncio.sleep(0.8)
            await self.key(p.K_ESCAPE)
            seen['escaped'] = (pages[-1], self.settings.get('seenHelp'))
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        pages, restore = self.recordHelpPages()
        try:
            self.settings.put('seenHelp', False)
            self.runGame(firstVisit)
            self.settings._values = None  # as on the next start
            del pages[:]
            self.runGame(nextVisit)
            self.settings.put('seenHelp', False)
            self.runGame(escape)
        finally:
            restore()
            self.settings.put('seenHelp', True)
        self.assertEqual(seen['opened'], (0, False), "How to play opens by itself, on its first page")
        self.assertEqual(seen['closed'], (None, True), "closing it marks it seen")
        self.assertEqual(seen['next'], [], "and it doesn't open again")
        self.assertEqual(seen['escaped'], (None, True), "Esc counts as closing too")

    def test_first_visit_help_waits_for_the_invite_prompt(self):
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(0.8)
            seen['prompt'] = ([page for page in pages if page is not None], self.settings.get('seenHelp'))
            await self.click(main.promptRects()[2].center, 0.4)  # Cancel
            seen['after'] = pages[-1]
            await self.key(p.K_ESCAPE)
            seen['closed'] = self.settings.get('seenHelp')
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        pages, restore = self.recordHelpPages()
        sent, topics, restoreRoom = self.offlineRoom()
        removed, restoreParam = self.openedWithRoomParam("test12")
        try:
            self.settings.put('seenHelp', False)
            self.runGame(script)
        finally:
            restore()
            restoreParam()
            restoreRoom()
            self.settings.put('seenHelp', True)
        self.assertEqual(seen['prompt'], ([], False), "the Join prompt comes first")
        self.assertEqual(seen['after'], 0, "How to play opens once it is answered")
        self.assertTrue(seen['closed'])

    def test_first_visit_help_opened_by_hand_under_the_prompt(self):
        # read (H) and closed while the Join prompt waited: answering the prompt doesn't open it a second time
        main = self.main
        seen = {}

        async def script():
            await asyncio.sleep(0.8)
            await self.key(p.K_h, 'h', 0.3)
            seen['opened'] = pages[-1]
            await self.key(p.K_ESCAPE)
            seen['closed'] = (pages[-1], self.settings.get('seenHelp'))
            await self.click(main.promptRects()[2].center, 0.6)  # Cancel
            seen['after'] = pages[-1]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        pages, restore = self.recordHelpPages()
        sent, topics, restoreRoom = self.offlineRoom()
        removed, restoreParam = self.openedWithRoomParam("test12")
        try:
            self.settings.put('seenHelp', False)
            self.runGame(script)
        finally:
            restore()
            restoreParam()
            restoreRoom()
            self.settings.put('seenHelp', True)
        self.assertEqual(seen['opened'], 0)
        self.assertEqual(seen['closed'], (None, True))
        self.assertIsNone(seen['after'], "How to play doesn't open again")

    def test_first_visit_help_skips_a_password_reset(self):
        import browser
        seen = {}
        realHash, realClear = browser.locationHash, browser.clearLocationHash

        async def script():
            await asyncio.sleep(0.8)
            seen['view'] = frames[-1]['view']
            await self.key(p.K_ESCAPE)
            await asyncio.sleep(0.3)
            seen['help'] = [page for page in pages if page is not None]
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        browser.locationHash = lambda: "access_token=tok&refresh_token=ref&type=recovery"
        browser.clearLocationHash = lambda: None
        frames, restoreAccount = self.recordAccountWindow()
        pages, restore = self.recordHelpPages()
        try:
            self.settings.put('seenHelp', False)
            self.runGame(script)
            seen['seen'] = self.settings.get('seenHelp')
        finally:
            restore()
            restoreAccount()
            browser.locationHash, browser.clearLocationHash = realHash, realClear
            self.settings.put('seenHelp', True)
        self.assertEqual(seen['view'], 'newPassword')
        self.assertEqual(seen['help'], [], "How to play doesn't follow the password reset")
        self.assertFalse(seen['seen'], "it waits for a later visit")

    def test_captured_pieces_have_a_halo_for_the_dark_theme(self):
        main = self.main
        main.loadImages()
        try:
            for theme in ('light', 'dark'):
                main.setUiTheme(theme)
                halo = tuple(main.UI['capturedHalo'])
                for piece in ('bQ', 'bp', 'wQ', 'wp'):
                    icon = main.capturedIcon(piece)
                    self.assertEqual(icon.get_size(), (main.SMALL_PIECE_SIZE + 2,) * 2)
                    colors = {tuple(icon.get_at((x, y))) for x in range(icon.get_width()) for y in range(icon.get_height())}
                    self.assertEqual(halo + (255,) in colors, piece[0] == 'b', (theme, piece))
                self.assertIs(main.capturedIcon('bQ'), main.capturedIcon('bQ'), "made once")
            # on the dark theme's strip, Black's pieces stand out by their halo
            strip = main.PALETTES['dark']['strip']
            icon = main.capturedIcon('bp')
            edge = [tuple(icon.get_at((x, y)))[:3] for x in range(icon.get_width()) for y in range(icon.get_height())
                    if icon.get_at((x, y))[3] == 255]
            lightest = max(sum(color) for color in edge)
            self.assertGreater(lightest - sum(strip), 200)
        finally:
            main.setUiTheme(self.settings.get('uiTheme'))

    def test_player_strip_draws_captured_pieces_with_their_halo(self):
        main = self.main
        main.loadImages()
        try:
            main.setUiTheme('dark')
            screen = p.Surface(main.WINDOW_SIZE)
            main.drawPlayerStrip(screen, 0, 'w', "White", ['bQ'], 9, None, False)
            x0, y0 = main.PANEL_X + 10 - 1, 26
            halo = tuple(main.UI['capturedHalo'])
            area = {tuple(screen.get_at((x, y)))[:3] for x in range(x0, x0 + main.SMALL_PIECE_SIZE + 2)
                    for y in range(y0, y0 + main.SMALL_PIECE_SIZE + 2)}
            self.assertIn(halo, area)
        finally:
            main.setUiTheme(self.settings.get('uiTheme'))

    def test_starting_window_size(self):
        main = self.main
        size = main.WINDOW_SIZE
        frame = (22, 56)
        self.assertEqual(main.startingWindowSize(size, (1920, 1040), frame), size, "fits: as it is")
        self.assertEqual(main.startingWindowSize(size, (2880, 1620), frame), (2 * size[0], 2 * size[1]),
                         "a large screen: the largest whole scale, so it stays crisp")
        self.assertEqual(main.startingWindowSize(size, (2880, 1560), frame), size,
                         "twice as large plus the frame wouldn't fit")
        small = main.startingWindowSize(size, (1366, 728), frame)
        self.assertEqual(small, (1000, 672), "a laptop: smaller, frame included, same shape")
        self.assertLessEqual(small[1] + frame[1], 728)
        narrow = main.startingWindowSize(size, (1024, 1000), frame)
        self.assertLessEqual(narrow[0] + frame[0], 1024)
        self.assertAlmostEqual(narrow[0] / narrow[1], size[0] / size[1], places=2)
        tiny = main.startingWindowSize(size, (400, 300), frame)
        self.assertEqual(tiny, (round(size[0] * main.WINDOW_MIN_SCALE), round(size[1] * main.WINDOW_MIN_SCALE)),
                         "never smaller than the smallest the window can be made")

    def test_picture_rect_and_the_black_bars(self):
        main = self.main
        size = main.WINDOW_SIZE
        self.assertEqual(main.pictureRect(size, size), p.Rect((0, 0), size), "the game's own shape: no bars")
        maximized = main.pictureRect((1920, 1009), size)  # a maximized window on a 1920x1080 screen
        self.assertEqual((maximized.y, maximized.height), (0, 1009))
        self.assertAlmostEqual(maximized.x, (1920 - maximized.width) / 2, delta=1)
        self.assertAlmostEqual(maximized.width / maximized.height, size[0] / size[1], places=2)
        self.assertFalse(maximized.collidepoint(60, 568), "the left bar is outside the picture")
        self.assertTrue(maximized.collidepoint(272, 820), "a2")
        tall = main.pictureRect((1200, 1000), size)
        self.assertEqual((tall.x, tall.width), (0, 1200))
        self.assertFalse(tall.collidepoint(5, 5), "the bar above the board")
        self.assertEqual(main.pointerPos(), p.mouse.get_pos(), "no scaled desktop window: pygame's own")

    def test_open_window_keeps_the_plain_window_headless(self):
        main = self.main
        p.display.init()
        self.assertEqual(p.display.get_driver(), 'dummy')
        screen = main.openWindow()
        self.assertEqual(screen.get_size(), main.WINDOW_SIZE)
        self.assertFalse(screen.get_flags() & p.SCALED, "the tests' dummy driver keeps the plain window")


    # --- step 10: the portrait layout (a browser window taller than wide)

    def portrait(self, viewport=(390, 844)):
        """Makes the game start in portrait as in a browser window of viewport; returns restore()."""
        import browser
        main = self.main
        real = browser.viewportSize
        size = [viewport]
        browser.viewportSize = lambda: size[0]

        def restore():
            browser.viewportSize = real
            main.setLayout('landscape')
        self.viewport = size  # a test can turn the window: self.viewport[0] = (w, h)
        return restore

    def boardPoint(self, row, col):
        """The canvas point at the middle of a square in the live layout (White at the bottom)."""
        board, SQ = self.main.LAYOUT.board, self.main.SQ_SIZE
        return (board.x + col * SQ + SQ // 2, board.y + row * SQ + SQ // 2)

    def test_layout_follows_the_window_shape(self):
        main = self.main
        self.assertEqual(main.layoutFor(None), ('landscape', None), "desktop")
        self.assertEqual(main.layoutFor((1280, 800)), ('landscape', None))
        self.assertEqual(main.layoutFor((844, 390)), ('landscape', None), "a phone held sideways")
        self.assertEqual(main.layoutFor((600, 600)), ('landscape', None), "square: landscape")
        self.assertEqual(main.layoutFor((390, 844)), ('portrait', round(768 * 844 / 390)))
        self.assertEqual(main.layoutFor((412, 915)), ('portrait', main.PORTRAIT_HEIGHTS[1]), "clamped")
        self.assertEqual(main.layoutFor((768, 1024)), ('portrait', main.PORTRAIT_HEIGHTS[0]), "a tablet: clamped")

    def test_landscape_layout_keeps_the_old_geometry(self):
        main = self.main
        layout = main.Layout()
        self.assertIs(main.LAYOUT.kind, 'landscape')
        self.assertEqual(layout.size, main.WINDOW_SIZE)
        self.assertEqual(layout.board, p.Rect(0, 0, main.BOARD_WIDTH, main.BOARD_HEIGHT))
        self.assertEqual(layout.panel, p.Rect(main.PANEL_X, 0, main.MOVE_LOG_PANEL_WIDTH, main.MOVE_LOG_PANEL_HEIGHT))
        self.assertEqual((layout.controlsX, layout.controlsWidth, layout.controlsBottom),
                         (main.PANEL_X + main.PANEL_PADDING, main.CONTROL_WIDTH, main.BOARD_HEIGHT - main.PANEL_PADDING))
        self.assertEqual((layout.rowHeight, layout.rowGap, layout.graphHeight, layout.stripHeight),
                         (main.ROW_HEIGHT, main.ROW_GAP, main.GRAPH_HEIGHT, main.STRIP_HEIGHT))
        self.assertEqual((layout.labelSize, layout.labelMin), (main.BUTTON_LABEL_SIZE, main.BUTTON_LABEL_MIN))
        self.assertEqual((layout.moveRow, layout.moveText, layout.movePadding),
                         (main.MOVE_ROW_HEIGHT, main.MOVE_TEXT_SIZE, main.MOVE_LIST_PADDING))
        self.assertEqual(layout.moveColumns, main.MOVE_COLUMNS)
        self.assertEqual((layout.moveNumberRight, layout.scrollbarX), (main.MOVE_NUMBER_RIGHT, main.SCROLLBAR_X))
        self.assertEqual(layout.banner, main.LOOK_BACK_BANNER)
        self.assertEqual(main.windowTransform(main.ACCOUNT_BOX), (1, (0, 0)), "windows as laid out")
        # the panel's parts as the game loop placed them before there were layouts
        controlsTop = 500
        stripY = controlsTop - main.ROW_GAP - main.STRIP_HEIGHT
        for gameOver in (False, True):
            areas = main.panelAreas(controlsTop, gameOver)
            info = p.Rect(main.PANEL_X + 10, stripY - 60, main.MOVE_LOG_PANEL_WIDTH - 20, 54)
            status = p.Rect(main.PANEL_X + 10, (info.y if gameOver else stripY) - main.STATUS_HEIGHT - 4,
                            main.MOVE_LOG_PANEL_WIDTH - 20, main.STATUS_HEIGHT)
            self.assertEqual(areas['bottomStrip'].y, stripY)
            self.assertEqual(areas['topStrip'].y, 0)
            self.assertEqual(areas['status'], status)
            self.assertEqual(areas['info'], info)
            self.assertEqual(areas['list'], (main.STRIP_HEIGHT, status.y - 2))

    def allPanelLayouts(self):
        """(arguments, rects) of every panel the game can show."""
        main = self.main
        found = []
        for mode in (0, 1, 2):
            for connected in ((False, True) if mode == 2 else (False,)):
                for canRejoin in ((False, True) if mode == 2 and not connected else (False,)):
                    for reviewing, graph in ((False, False), (True, False), (True, True)):
                        for guest in ((False, True) if connected else (False,)):
                            if reviewing and mode == 2 and not connected:
                                continue  # online without a room there is no game to review
                            args = (mode, connected, canRejoin, reviewing, graph, guest)
                            found.append((args, main.panelLayout(*args)))
        return found

    def test_portrait_layouts_fit_the_canvas(self):
        main = self.main
        try:
            for height in (main.PORTRAIT_HEIGHTS[0], 1500, 1662, main.PORTRAIT_HEIGHTS[1]):
                layout = main.setLayout('portrait', height)
                canvas = p.Rect((0, 0), layout.size)
                self.assertEqual(layout.size, (main.PORTRAIT_WIDTH, height))
                self.assertGreaterEqual(layout.scale, main.PORTRAIT_SCALES[0])
                self.assertLessEqual(layout.scale, main.PORTRAIT_SCALES[1])
                self.assertTrue(canvas.contains(layout.board))
                self.assertEqual(layout.board.width, main.BOARD_WIDTH, "the board keeps its size")
                for fill in layout.panelFill:
                    self.assertFalse(fill.colliderect(layout.board), "the panel's background leaves the board")
                for args, rects in self.allPanelLayouts():
                    where = (height, args)
                    reviewing = args[3]
                    top = min(rect.y for rect in rects.values())
                    areas = main.panelAreas(top, reviewing)
                    strips = [areas['topStrip'], areas['bottomStrip']]
                    self.assertEqual(areas['topStrip'].bottom, layout.board.top, where)
                    self.assertEqual(areas['bottomStrip'].top, layout.board.bottom, where)
                    listTop, listBottom = areas['list']
                    rows = (listBottom - listTop - layout.movePadding) // layout.moveRow
                    self.assertGreaterEqual(rows, main.PORTRAIT_MIN_LIST_ROWS if height >= 1500 else 1, where)
                    self.assertGreaterEqual(listTop, areas['status'].bottom, where)
                    if reviewing:
                        self.assertGreaterEqual(areas['info'].y, listBottom, where)
                        self.assertLess(areas['info'].bottom, top, where)
                    for name, rect in rects.items():
                        self.assertTrue(canvas.contains(rect), (where, name))
                        self.assertGreaterEqual(rect.height, main.ROW_HEIGHT, (where, name, "touch-sized"))
                        for other in [layout.board, areas['status']] + strips:
                            self.assertFalse(rect.colliderect(other), (where, name))
                        for otherName, other in rects.items():
                            if otherName != name:
                                self.assertFalse(rect.colliderect(other), (where, name, otherName))
                    # what opens from the controls stays on the canvas
                    for name in main.DROPDOWNS:
                        if name in rects:
                            for option in main.dropdownOptionRects(rects[name], len(main.dropdownLabels(name))):
                                self.assertTrue(canvas.contains(option), (where, name))
                    self.assertTrue(canvas.contains(main.menuBoxRect(rects['menu'])), where)
                    if 'chat' in rects:
                        self.assertTrue(canvas.contains(main.popupBoxRect(main.chatItemRects(rects['chat']))), where)
                prompt, yes, no = main.promptRects()
                self.assertTrue(canvas.contains(prompt))
                self.assertFalse(prompt.colliderect(layout.board), "the prompt doesn't cover the board")
                self.assertTrue(prompt.contains(yes) and prompt.contains(no))
                card = main.resultCardLayout("Black wins by checkmate", ['new', 'switch'])[2]
                self.assertTrue(layout.board.contains(card['card']))
                self.assertEqual(card['card'].center, layout.board.center)
                # the windows are shown larger, inside the canvas; a point maps back into the same control
                boxes = [main.helpLayout(), main.settingsLayout('board'), main.settingsLayout('game')]
                boxes += [main.accountLayout(view, 5) for view in ('signin', 'register', 'forgot', 'profile', 'games')]
                for rects in boxes:
                    box = rects['box']
                    shown = main.fromWindow(box, box)
                    self.assertTrue(canvas.contains(shown), (height, box))
                    self.assertGreater(shown.width, box.width, "scaled up")
                    for name, rect in rects.items():
                        self.assertTrue(rect.collidepoint(main.toWindow(main.fromWindow(rect, box).center, box)),
                                        (height, name))
                self.assertGreater(main.LAYOUT.labelSize, main.BUTTON_LABEL_SIZE if height >= 1500 else 0)
        finally:
            main.setLayout('landscape')
        self.assertEqual(main.LAYOUT.size, main.WINDOW_SIZE)

    def test_portrait_move_list_and_strip(self):
        main = self.main
        main.loadImages()
        try:
            layout = main.setLayout('portrait', 1662)
            moves = main.moveListLayout(70, 1000, 1300)
            for rect, _ in moves['cells']:
                self.assertTrue(layout.panel.contains(rect))
                self.assertEqual(rect.height, layout.moveRow - 2)
            self.assertEqual(moves['area'].width, layout.panel.width)
            self.assertIsNotNone(moves['track'], "70 plies don't fit: the scrollbar shows")
            self.assertLessEqual(moves['track'].right, layout.panel.right)
            self.assertEqual(main.scrollForListDrag(0, 3 * layout.moveRow), 3)
            # the strip spans the canvas, its clock at the right edge
            screen = p.Surface(layout.size)
            screen.fill((1, 2, 3))
            main.drawPlayerStrip(screen, 0, 'w', "White", [], 0, 60000, True)
            self.assertNotEqual(tuple(screen.get_at((layout.size[0] - main.scaled(12) - 5, main.scaled(20))))[:3],
                                (1, 2, 3))
            self.assertEqual(tuple(screen.get_at((5, layout.stripHeight + 2)))[:3], (1, 2, 3), "no taller than its strip")
        finally:
            main.setLayout('landscape')

    def test_portrait_prompt_leaves_the_status_slot_free(self):
        # a message shown while a question is open (a disabled button's reason, say) mustn't cover the question
        main = self.main
        try:
            for height in (main.PORTRAIT_HEIGHTS[0], 1500, 1662, main.PORTRAIT_HEIGHTS[1]):
                main.setLayout('portrait', height)
                for gameOver, reviewing in ((False, False), (True, True)):
                    rects = main.panelLayout(1, False, reviewing=reviewing, graph=reviewing)
                    areas = main.panelAreas(min(rect.y for rect in rects.values()), gameOver)
                    box = main.promptRects()[0]
                    where = (height, gameOver)
                    self.assertFalse(box.colliderect(areas['status']), where)
                    self.assertFalse(box.colliderect(main.LAYOUT.board), where)
                    self.assertFalse(any(box.colliderect(rect) for rect in rects.values()), (where, "the controls"))
        finally:
            main.setLayout('landscape')

    def test_portrait_chat_bubbles_stay_in_the_strips(self):
        main = self.main
        main.loadImages()
        try:
            layout = main.setLayout('portrait', 1662)
            screen = p.Surface(layout.size)
            top = p.Rect(0, 0, layout.size[0], layout.stripHeight)
            bottom = p.Rect(0, layout.board.bottom, layout.size[0], layout.stripHeight)
            for strip, name, note, clock in ((top, "Opponent", "may have left", 60000), (top, "Opponent", None, None),
                                             (bottom, "You", None, 60000)):
                span = main.drawPlayerStrip(screen, strip.y, 'w', name, [], 0, clock, False, note)
                nameObj = main.get_text_surface(name, main.scaled(18), (0, 0, 0))
                self.assertGreaterEqual(span[0], strip.x + main.scaled(32) + nameObj.get_width(), "after the name")
                self.assertLess(span[1], strip.right)
                for text in main.QUICK_CHAT:
                    where = (name, note, clock, text)
                    rect, tail = main.chatBubbleLayout(text, strip.y, strip is top, span=span)
                    self.assertTrue(strip.contains(rect), where)
                    self.assertFalse(rect.colliderect(layout.board), (where, "never over the board"))
                    self.assertGreaterEqual(min(x for x, _ in tail), span[0], (where, "its tail stops short of the name"))
                    self.assertLessEqual(rect.right, span[1], (where, "it leaves the clock alone"))
                    textWidth = main.get_font(main.scaled(main.CHAT_TEXT_SIZE), True, True).size(text)[0]
                    self.assertLessEqual(textWidth, rect.width - main.scaled(28), (where, "the text fits"))
                    drawn = main.drawChatBubble(screen, text, strip.y, strip is top, span=span)
                    self.assertEqual(drawn, rect)
            # a name of 20 wide letters leaves almost no room: the bubble still keeps off the clock and the edge
            for span in ((599, 617), (731, 754)):
                rect, tail = main.chatBubbleLayout("One moment, please", top.y, True, span=span)
                self.assertLessEqual(rect.right, span[1], span)
                self.assertTrue(top.contains(rect), span)
        finally:
            main.setLayout('landscape')

    def test_promotion_picker_on_the_board_surface(self):
        main = self.main
        main.loadImages()
        try:
            layout = main.setLayout('portrait', 1662)
            screen = p.display.set_mode(layout.size)
            board = screen.subsurface(layout.board)
            SQ = main.SQ_SIZE

            async def pick(clickAt):
                async def clicker():
                    await asyncio.sleep(0.1)
                    await self.click(clickAt, 0)
                choice, _ = await asyncio.gather(main.pawnPromotionPopup(board, 'w', 0, 2, False), clicker())
                return choice
            # the rook is the second square down the c-file, on the canvas below the top strip
            self.assertEqual(asyncio.run(pick((layout.board.x + 2 * SQ + 5, layout.board.y + SQ + 5))), 'R')
            self.assertIsNone(asyncio.run(pick((2 * SQ + 5, 5))), "the strip above the board is outside the picker")
        finally:
            main.setLayout('landscape')
            p.display.set_mode(main.WINDOW_SIZE)

    def test_portrait_game_loop(self):
        main = self.main
        restore = self.portrait()
        seen = {}

        def at(pos):
            return tuple(p.display.get_surface().get_at(pos))[:3]

        async def script():
            await asyncio.sleep(1.0)
            layout = main.LAYOUT
            seen['size'] = p.display.get_surface().get_size()
            seen['kind'] = layout.kind
            # e2-e4 by two taps on the board under the top strip
            await self.tap(self.boardPoint(6, 4), 0.1)
            await self.tap(self.boardPoint(4, 4), 1.5)
            seen['moves'] = list(gameMoves)
            # the menu opens upwards from its button, and its Settings item opens the scaled-up window
            rects = main.panelLayout(0, False)
            await self.tap(rects['menu'].center, 0.3)
            await self.tap(main.menuItemRects(rects['menu'])['settings'].center, 0.4)
            box = main.SETTINGS_BOX
            await self.tap(main.fromWindow(main.settingsLayout('board')['tab:game'], box).center, 0.3)
            await self.tap(main.fromWindow(main.settingsLayout('game')['uiTheme:dark'], box).center, 0.3)
            seen['theme'] = self.settings.get('uiTheme')
            await self.tap(main.fromWindow(main.settingsLayout('game')['uiTheme:light'], box).center, 0.3)
            await self.tap(main.fromWindow(main.settingsLayout('game')['close'], box).center, 0.3)
            # How to play: Next, then Close, by their places on the canvas
            await self.key(p.K_h, 'h')
            help = main.helpLayout()
            await self.tap(main.fromWindow(help['next'], help['box']).center, 0.3)
            seen['help page'] = pages[-1]
            await self.tap(main.fromWindow(help['close'], help['box']).center, 0.3)
            seen['help closed'] = pages[-1]
            # resign: the prompt under the player's strip, then the result card on the board
            await self.tap(rects['resign'].center, 0.3)
            await self.tap(main.promptRects()[1].center, 0.6)
            cardRects = main.resultCardLayout("Black wins by resignation", ['new', 'switch'])[2]
            seen['card'] = max(at((cardRects['card'].x + 8, cardRects['card'].centery)))
            newGame = cardRects['new']
            await self.tap(newGame.center, 0.6)
            seen['after new game'] = len(gameMoves)
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        gameMoves = []
        realDraw = main.drawGameState

        def record(screen, gs, *args, **kwargs):
            gameMoves[:] = [m.getCode() for m in gs.moveLog]
            return realDraw(screen, gs, *args, **kwargs)
        main.drawGameState = record
        pages, restorePages = self.recordHelpPages()  # around record
        try:
            self.runGame(script)
        finally:
            restorePages()
            main.drawGameState = realDraw
            restore()
        self.assertEqual(seen['kind'], 'portrait')
        self.assertEqual(seen['size'], (main.PORTRAIT_WIDTH, round(768 * 844 / 390)))
        self.assertEqual(seen['moves'][:1], ['e2e4'], "the taps played the move (the computer may have replied)")
        self.assertEqual(seen['theme'], 'dark', "the scaled-up Settings window took the tap")
        self.assertEqual((seen['help page'], seen['help closed']), (1, None))
        self.assertLess(seen['card'], 100, "the result card is on the board's middle")
        self.assertEqual(seen['after new game'], 0)

    def test_portrait_drag_and_turning_the_window(self):
        main = self.main
        restore = self.portrait((412, 915))
        seen = {}

        async def script():
            await asyncio.sleep(1.0)
            seen['height'] = main.LAYOUT.size[1]
            await self.chooseTwoPlayersHere()
            # a drag from g1 to f3, through canvas points below the strip
            start, end = self.boardPoint(7, 6), self.boardPoint(5, 5)
            await self.click(start, 0.05)
            for i in range(1, 6):
                pos = (round(start[0] + (end[0] - start[0]) * i / 5), round(start[1] + (end[1] - start[1]) * i / 5))
                self.mouse[0] = pos
                p.event.post(p.event.Event(p.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0)))
                await asyncio.sleep(0.04)
            p.event.post(p.event.Event(p.MOUSEBUTTONUP, button=1, pos=self.mouse[0]))
            await asyncio.sleep(0.4)
            seen['after drag'] = list(gameMoves)
            # the phone turns: the game lays itself out in landscape and goes on
            self.viewport[0] = (915, 412)
            await asyncio.sleep(1.2)
            seen['turned'] = (main.LAYOUT.kind, p.display.get_surface().get_size())
            await self.move((1, 4), (3, 4), 0.4)  # landscape squares again
            seen['after turning'] = list(gameMoves)
            self.viewport[0] = (412, 915)
            await asyncio.sleep(1.2)
            seen['back'] = (main.LAYOUT.kind, p.display.get_surface().get_size())
            p.event.post(p.event.Event(p.QUIT))
            await asyncio.sleep(0.3)

        gameMoves = []
        realDraw = main.drawGameState

        def record(screen, gs, *args, **kwargs):
            gameMoves[:] = [m.getCode() for m in gs.moveLog]
            return realDraw(screen, gs, *args, **kwargs)
        main.drawGameState = record
        try:
            self.runGame(script)
        finally:
            main.drawGameState = realDraw
            restore()
        self.assertEqual(seen['height'], main.PORTRAIT_HEIGHTS[1])
        self.assertEqual(seen['after drag'], ['g1f3'])
        self.assertEqual(seen['turned'], ('landscape', main.WINDOW_SIZE))
        self.assertEqual(seen['after turning'], ['g1f3', 'e7e5'], "the game went on in the new layout")
        self.assertEqual(seen['back'], ('portrait', (main.PORTRAIT_WIDTH, main.PORTRAIT_HEIGHTS[1])))
        self.assertEqual(p.display.get_surface().get_size(), seen['back'][1])

    async def chooseTwoPlayersHere(self):
        """Local 2-Player from the mode dropdown, in whatever layout is live."""
        modeRect = self.main.panelLayout(0, False)['mode']
        await self.tap(modeRect.center)
        await self.tap(self.main.dropdownOptionRects(modeRect, len(self.main.MODE_OPTIONS))[1].center, 0.5)


if __name__ == '__main__':
    unittest.main()
