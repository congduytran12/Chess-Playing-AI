# The game's languages: the tables, the lookup, and that every text the game has a translation for in Vietnamese
import os
import re
import unittest

import support  # noqa: F401  (puts game/ on the path)
import i18n  # noqa: E402
import lang_vi  # noqa: E402

main = None  # the game, imported when a test runs: its sounds and fonts are found from game/ (see setUp)


class LanguageTest(unittest.TestCase):
    def setUp(self):
        global main
        import pygame
        pygame.font.init()
        self.folder = os.getcwd()
        os.chdir(support.GAME)  # the fonts and sounds are found by their relative paths
        import main as game
        main = game
        main.applyLanguage('vi')

    def tearDown(self):
        main.applyLanguage('en')
        os.chdir(self.folder)

    def test_english_is_left_as_it_is(self):
        i18n.setLanguage('en')
        for text in ("Hint (3 left)", "Anything at all", "", "Rematch"):
            self.assertEqual(i18n.tr(text), text)
        i18n.setLanguage('xx')
        self.assertEqual((i18n.language(), i18n.tr("Rematch")), ('en', "Rematch"), "an unknown language is English")

    def test_texts_and_templates(self):
        tr = i18n.tr
        self.assertEqual(tr("Rematch"), "Đấu lại")
        self.assertEqual(tr("Hint (3 left)"), "Gợi ý (còn 3)")
        self.assertEqual(tr("Hint: Nf3 (2 left today)"), "Gợi ý: Nf3 (hôm nay còn 2)", "the longer template wins")
        self.assertEqual(tr("Hint: Nf3"), "Gợi ý: Nf3")
        self.assertEqual(tr("Rematch: you play White"), "Đấu lại: bạn chơi quân Trắng", "a part is translated too")
        self.assertEqual(tr("Mode: Local vs AI"), "Chế độ: Chơi với máy")
        self.assertEqual(tr("Your rating: 1012 (+12)"), "Điểm của bạn: 1012 (+12)")
        self.assertEqual(tr("Solved! Rating -7"), "Đã giải được! Điểm -7")
        self.assertEqual(tr("Blunder: loses 3.2. Best was Qxh7"), "Sai lầm nặng: mất 3.2. Nước tốt nhất là Qxh7")
        self.assertEqual(tr("Looking back: after 3.Nf3 e5  -  tap the board to return"),
                         "Đang xem lại: sau 3.Nf3 e5  -  chạm vào bàn cờ để quay lại", "a template in a template")
        self.assertEqual(tr("Nf3"), "Nf3", "no translation: as it is")
        self.assertEqual(tr(tr("Rematch")), tr("Rematch"), "a translation isn't translated again")
        self.assertEqual(tr("04:59"), "04:59")

    def test_every_template_is_consistent(self):
        for english, vietnamese in lang_vi.TEMPLATES.items():
            with self.subTest(english=english):
                parts = len(re.findall(r'%[+.]?\d?[sdf]', english))
                used = {int(n) for n in re.findall(r'\{(\d+)\}', vietnamese)}
                self.assertEqual(used, set(range(parts)), "the same parts, by their places")
                self.assertTrue(i18n.templateRegex(english).groups == parts)
        for english, vietnamese in lang_vi.EXACT.items():
            with self.subTest(english=english):
                self.assertTrue(vietnamese.strip(), "no empty translation")
                self.assertNotIn('%', english, "a text with a number or a name in it is a template")
                self.assertNotIn('{', vietnamese)
        self.assertFalse(set(lang_vi.EXACT) & set(lang_vi.TEMPLATES))

    def test_the_fonts_have_every_letter(self):
        # a font's metrics answer for a letter it can't draw too: what counts is that something is drawn
        text = "".join(lang_vi.EXACT.values()) + "".join(lang_vi.TEMPLATES.values())
        letters = sorted({ch for ch in text if not ch.isspace() and ch not in '{}0123456789'})
        for label, font in (("regular", main.get_font(20, False)), ("bold", main.get_font(20, True)),
                            ("buttons", main.get_font(20, True, True))):
            blank = [ch for ch in letters if font.render(ch, True, (255, 255, 255)).get_bounding_rect().width == 0]
            self.assertEqual(blank, [], "letters the %s font can't draw" % label)

    def test_the_buttons_font_depends_on_the_language(self):
        i18n.setLanguage('en')
        main.FONT_CACHE.clear()
        english = main.get_font(24, True, True).size("Resign")[0]
        main.applyLanguage('vi')
        self.assertNotIn((24, False, True), main.FONT_CACHE, "the fonts are made again")
        vietnamese = main.get_font(24, True, True).size("Resign")  # Xin thua
        self.assertGreater(vietnamese[0], english * 0.6, "about as big as the English font")
        self.assertLess(vietnamese[0], english * 2)
        main.applyLanguage('en')

    def test_the_texts_of_the_game_are_translated(self):
        texts = set(main.MODE_OPTIONS) | set(main.LEVEL_OPTIONS) | set(main.SIDE_OPTIONS) | set(main.QUICK_CHAT)
        texts |= set(main.TOOLTIPS.values()) | set(main.SETTING_LABELS.values()) | set(main.SETTING_TIPS.values())
        texts |= set(main.RESULT_BUTTONS.values()) | {label for _, label in main.MENU_ITEMS}
        texts |= set(main.ACCOUNT_TITLES.values()) | set(main.ACCOUNT_INTROS.values()) | set(main.ACCOUNT_SUBMITS.values())
        texts |= set(main.ACCOUNT_SWITCHES.values()) | set(main.ACCOUNT_BUTTONS.values())
        texts |= {label for choices in main.SETTING_CHOICES.values() for _, label in choices
                  if choices is not i18n.LANGUAGES}
        for title, items in main.HELP_PAGES:
            texts.add(title)
            for item in items:
                texts |= {part for part in item[1:3] if isinstance(part, str)}
        texts -= {"Email", main.LANGUAGE_MENU_LABEL}  # the same word; and the one in both languages
        missing = sorted(text for text in texts if '%' not in text and i18n.tr(text) == text)
        self.assertEqual(missing, [], "texts with no Vietnamese")

    def test_touch_screens_are_told_to_tap(self):
        self.assertEqual(main.touchWording("Click one of your pieces, then click a square. Clicking twice clicks."),
                         "Tap one of your pieces, then tap a square. Tapping twice taps.")
        self.assertEqual(main.touchWording("nhấp vào quân. Nhấp"), "chạm vào quân. Chạm")
        self.assertEqual(main.touchWording("Right-click or Esc"), "Right-tap or Esc")  # not on a phone's help page
        font = main.get_font(17, False)
        self.assertEqual(main.wrapText("Click here", font, 500, touch=True), ["Tap here"])
        self.assertEqual(main.wrapText("Click here", font, 500), ["Click here"])

    def test_the_account_lists_are_translated_part_by_part(self):
        i18n.setLanguage('vi')
        try:
            self.assertEqual(i18n.tr(main.countGames(3)), "3 ván")
            self.assertEqual(i18n.tr(main.countGames(1)), "1 ván")
            for row, shown in (({'result': '1-0', 'color': 'w'}, "Thắng"), ({'result': '1-0', 'color': 'b'}, "Thua"),
                               ({'result': '1/2-1/2'}, "Hòa")):
                self.assertEqual(i18n.tr(main.gameRowResult(row)), shown)
        finally:
            i18n.setLanguage('en')

    def test_a_long_account_name_does_not_shrink_the_other_labels(self):
        rows = main.panelRows(0, False, False, False, False, False)
        rects = main.panelLayout(0, False, False, False, False, False)
        labels = {'undo': "Undo", 'restart': "Restart", 'account': "Sign in", 'menu': ""}
        normal = main.evenLabelSizes(rows, rects, labels)
        labels['account'] = "VeryLongName"
        long = main.evenLabelSizes(rows, rects, labels)
        self.assertEqual((long['undo'], long['restart']), (normal['undo'], normal['restart']))
        self.assertLessEqual(long['account'], long['undo'])

    def test_the_random_side_label_is_short_in_vietnamese(self):
        i18n.setLanguage('vi')
        try:
            self.assertLessEqual(len(i18n.tr("Play as: Random")), len(i18n.tr("Play as: Black")) + 3)
        finally:
            i18n.setLanguage('en')

    def test_the_help_pages_fit_in_vietnamese(self):
        box, buttonsTop = main.ACCOUNT_BOX, main.helpLayout()['prev'].y
        x, width = box.x + 40, box.width - 80
        font = main.get_font(17, False)
        for page, (title, items) in enumerate(main.HELP_PAGES):
            layout = main.helpPageLayout(page)
            self.assertLessEqual(layout[-1]['bottom'], buttonsTop - 6, "page %d (%s) is too long" % (page, title))
            for item, placed in zip(items, layout):
                right = placed['diagram'].x - main.HELP_DIAGRAM_GAP if placed['diagram'] else x + width
                for line in placed['lines']:
                    self.assertLessEqual(placed['textX'] + font.size(line)[0], right, item[1])
                self.assertLessEqual(placed['textX'] + main.get_font(19, True).size(item[1])[0], right, item[1])

    def test_the_languages_names_draw_in_every_language(self):
        # a button names a language in its own letters, in whichever language the game is showing
        for language in ('en', 'vi'):
            main.applyLanguage(language)
            for _, name in i18n.LANGUAGES:
                for font in (main.get_font(24, True, True), main.get_font(24, True)):
                    blank = [ch for ch in name if not ch.isspace()
                             and font.render(ch, True, (255, 255, 255)).get_bounding_rect().width == 0]
                    self.assertEqual(blank, [], "%s in %s" % (name, language))

    def test_every_puzzle_theme_is_translated(self):
        import puzzles
        themes = {label for puzzle in puzzles.load() for label in puzzle.themeLabels}
        missing = sorted(label for label in themes if i18n.tr(label) == label and label != "Zugzwang")  # the same word
        self.assertEqual(missing, [], "puzzle themes with no Vietnamese")
        self.assertEqual(i18n.tr("Mate in 3"), "Chiếu hết sau 3 nước")

    def test_the_names_of_the_languages_are_not_translated(self):
        for _, name in i18n.LANGUAGES:
            self.assertEqual(i18n.tr(name), name)


if __name__ == '__main__':
    unittest.main()
