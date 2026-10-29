# Network message handling, PGN, the daily hint count, the saved settings and the browser helpers
import json
import os
import tempfile
import unittest

import support  # noqa: F401  (puts game/ on the path)
import browser
import hints
import network
import pgn
import settings
from engine import GameState
from network import NetworkManager, roomName


def event(msgId, body, serverTime=None):
    msg = {'id': msgId, 'event': 'message', 'message': body}
    if serverTime is not None:
        msg['time'] = serverTime
    return msg


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.net = NetworkManager()
        self.net._generation = 1

    def test_only_json_objects_are_queued(self):
        for i, body in enumerate(('123', '[]', '"text"', 'not json', None)):
            self.assertFalse(self.net._accept(event('bad%d' % i, body)), body)
        self.assertTrue(self.net._accept(event('ok', json.dumps({'type': 'state'}))))
        self.assertEqual(self.net.get_messages(), [{'type': 'state', '_time': None}])  # no server time given
        self.assertEqual(self.net.get_messages(), [])

    def test_duplicates_and_old_listeners_are_ignored(self):
        self.assertTrue(self.net._accept(event('a', '{}')))
        self.assertFalse(self.net._accept(event('a', '{}')))
        self.assertFalse(self.net._accept(event('b', '{}'), generation=0))

    def test_the_oldest_ids_are_forgotten_first(self):
        for i in range(network.SEEN_IDS_KEPT + 50):
            self.net._accept(event('id%04d' % i, '{}'))
        self.assertEqual(len(self.net.seen_ids), network.SEEN_IDS_KEPT)
        self.assertNotIn('id0000', self.net.seen_ids)
        self.assertIn('id%04d' % (network.SEEN_IDS_KEPT + 49), self.net.seen_ids)

    def test_messages_carry_the_server_time(self):
        # the sender can't fake '_time': it is always ntfy's time of receipt
        self.net._accept(event('a', json.dumps({'type': 'ping', '_time': 5}), serverTime=1000))
        self.net._accept(event('b', json.dumps({'type': 'ping'}), serverTime=900))  # an older one, replayed
        self.net._accept(event('c', json.dumps({'type': 'ping'})))
        self.assertEqual([m['_time'] for m in self.net.get_messages()], [1000, 900, None])
        self.assertEqual(self.net.server_time, 1000)

    def test_room_names_fit_ntfy_topics(self):
        self.assertEqual(roomName(' ab c/1é_- '), 'ABC1_-')


class PgnTest(unittest.TestCase):
    def test_round_trip(self):
        gs = GameState()
        moves = gs.getValidMoves()
        for code in "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1".split():
            moves = gs.makeMoveWithSan(gs.findMoveByCode(code, moves), moves)
        text = pgn.buildPgn(gs.moveLog, [("White", "A"), ("Black", "B"), ("Result", "*")], '*')
        headers, sans = pgn.parsePgn(text)
        self.assertEqual(headers['White'], 'A')
        self.assertEqual(sans, ['e4', 'e5', 'Nf3', 'Nc6', 'Bc4', 'Nf6', 'O-O'])

    def test_comments_variations_and_byte_order_mark(self):
        text = '﻿[Event "x"]\n\n1. e4 {best by test} e5 (1... c5 2. Nf3) 2. Nf3 $1 Nc6 1-0\n'
        headers, sans = pgn.parsePgn(text)
        self.assertEqual(headers.get('Event'), 'x')
        self.assertEqual(sans, ['e4', 'e5', 'Nf3', 'Nc6'])


class HintsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = hints.STORAGE_FILE
        hints.STORAGE_FILE = os.path.join(self.folder.name, 'hints.json')
        hints._saved = None

    def tearDown(self):
        hints.STORAGE_FILE = self.saved
        hints._saved = None
        self.folder.cleanup()

    def test_daily_limit(self):
        self.assertEqual(hints.remaining(), hints.HINTS_PER_DAY)
        for _ in range(hints.HINTS_PER_DAY):
            hints.use()
        self.assertEqual(hints.remaining(), 0)
        hints._saved = None  # as after a restart
        self.assertEqual(hints.remaining(), 0)

    def test_a_new_day_starts_over(self):
        with open(hints.STORAGE_FILE, 'w') as f:
            json.dump({'day': '2000-01-01', 'used': hints.HINTS_PER_DAY}, f)
        self.assertEqual(hints.remaining(), hints.HINTS_PER_DAY)

    def test_a_broken_file_counts_as_unused(self):
        with open(hints.STORAGE_FILE, 'w') as f:
            f.write('garbage')
        self.assertEqual(hints.remaining(), hints.HINTS_PER_DAY)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = settings.STORAGE_FILE
        settings.STORAGE_FILE = os.path.join(self.folder.name, 'settings.json')
        settings._values = None

    def tearDown(self):
        settings.STORAGE_FILE = self.saved
        settings._values = None
        self.folder.cleanup()

    def test_values_are_kept_between_starts(self):
        self.assertEqual(settings.get('board', 'Green'), 'Green')
        settings.put('board', 'Brown')
        settings.put('pieces', 'Classic')
        settings._values = None  # as after a restart
        self.assertEqual((settings.get('board'), settings.get('pieces')), ('Brown', 'Classic'))

    def test_a_broken_file_gives_the_defaults(self):
        with open(settings.STORAGE_FILE, 'w') as f:
            f.write('[1, 2')
        self.assertEqual(settings.get('board'), settings.DEFAULTS['board'])
        self.assertIsNone(settings.get('no such setting'))


class BrowserTest(unittest.TestCase):
    URL = "https://chess.example/play/index.html?room=AB12&x=1#game=e2e4"

    def test_url_helpers(self):
        self.assertEqual(browser.paramFromUrl(self.URL, 'room'), "AB12")
        self.assertEqual(browser.paramFromUrl(self.URL, 'x'), "1")
        self.assertIsNone(browser.paramFromUrl(self.URL, 'none'))
        self.assertEqual(browser.paramFromUrl("https://a.b/?room=", 'room'), "", "present but empty")
        self.assertEqual(browser.paramFromUrl("https://a.b/?name=A%20B", 'name'), "A B")
        self.assertEqual(browser.urlWithoutParam(self.URL, 'room'), "https://chess.example/play/index.html?x=1#game=e2e4")
        self.assertEqual(browser.urlWithoutParam("https://a.b/?room=X", 'room'), "https://a.b/")
        self.assertEqual(browser.hashFromUrl(self.URL), "game=e2e4")
        self.assertEqual(browser.hashFromUrl("https://a.b/"), "")
        self.assertEqual(browser.urlWithoutHash(self.URL), "https://chess.example/play/index.html?room=AB12&x=1")
        self.assertEqual(browser.siteFromUrl(self.URL), "https://chess.example/play/index.html")

    def test_desktop_fallbacks(self):
        self.assertFalse(browser.inBrowser())
        self.assertFalse(browser.pageHidden())
        self.assertIsNone(browser.queryParam('room'))
        self.assertEqual(browser.locationHash(), "")
        browser.removeQueryParam('room')  # nothing to do, and no error
        browser.clearLocationHash()
        self.assertEqual(browser.siteUrl(), browser.SITE_URL)
        self.assertIsNone(browser.takePastedText(), "desktop pastes through clipboardText()")

    def test_desktop_clipboard_tries_pygame_then_tkinter(self):
        calls = []
        saved = browser._scrapCopy, browser._tkCopy, browser._scrapPaste, browser._tkPaste
        try:
            browser._scrapCopy = lambda text: calls.append(('scrap', text)) or False
            browser._tkCopy = lambda text: calls.append(('tk', text)) or True
            self.assertTrue(browser.copyText("1. e4 e5"))
            self.assertEqual(calls, [('scrap', "1. e4 e5"), ('tk', "1. e4 e5")])
            browser._tkCopy = lambda text: False
            self.assertFalse(browser.copyText("x"), "neither worked")
            browser._scrapPaste = lambda: ""
            browser._tkPaste = lambda: "from tk"
            self.assertEqual(browser.clipboardText(), "from tk")
            browser._tkPaste = lambda: ""
            self.assertEqual(browser.clipboardText(), "")
        finally:
            browser._scrapCopy, browser._tkCopy, browser._scrapPaste, browser._tkPaste = saved

    def test_set_title(self):
        import pygame
        browser.setTitle("Your move · Chess Playing AI")
        self.assertEqual(pygame.display.get_caption()[0], "Your move · Chess Playing AI")
        browser.setTitle("Chess Playing AI")


if __name__ == '__main__':
    unittest.main()
