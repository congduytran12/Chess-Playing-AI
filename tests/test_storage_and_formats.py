# Network message handling, PGN, the daily hint count and the saved settings
import json
import os
import tempfile
import unittest

import support  # noqa: F401  (puts game/ on the path)
import hints
import network
import pgn
import settings
from engine import GameState
from network import NetworkManager, roomName


def event(msgId, body):
    return {'id': msgId, 'event': 'message', 'message': body}


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.net = NetworkManager()
        self.net._generation = 1

    def test_only_json_objects_are_queued(self):
        for i, body in enumerate(('123', '[]', '"text"', 'not json', None)):
            self.assertFalse(self.net._accept(event('bad%d' % i, body)), body)
        self.assertTrue(self.net._accept(event('ok', json.dumps({'type': 'state'}))))
        self.assertEqual(self.net.get_messages(), [{'type': 'state'}])
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
        self.assertIsNone(settings.get('board'))


if __name__ == '__main__':
    unittest.main()
