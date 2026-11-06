# api/account.py against an in-memory stand-in for Supabase (no network)
import unittest
from datetime import datetime, timedelta, timezone

import support

try:
    api = support.loadApi()
except ImportError as e:  # flask / requests not installed
    api = None
    missing = str(e)


class FakeSupabase:
    """Just enough of GoTrue and PostgREST for sign-in and rating reports."""

    def __init__(self, rpcAnswer='applied'):
        self.reports = []
        self.rpcCalls = []
        self.rpcAnswer = rpcAnswer
        self.authCalls = []  # (method, path, token, kwargs) of the auth requests for a reset link or a new password
        self.authStatus = 200  # the auth service's answer to them
        self.profile = {'id': 'U1', 'username': 'Duy_T', 'rating': 1200, 'rated_games': 0}  # the profiles row
        self.mistakes = []  # the mistakes table's rows
        self.nextId = 1

    def mistakesTable(self, method, params, json):
        """The part of PostgREST the mistakes use: eq and in filters, order, limit, select, and an upsert."""
        def matches(row):
            for key, value in params.items():
                operator, _, operand = value.partition('.')
                if key in ('order', 'limit', 'select', 'on_conflict'):
                    continue
                if operator == 'eq' and str(row[key]) != operand:
                    return False
                if operator == 'in' and str(row[key]) not in operand.strip('()').split(','):
                    return False
            return True
        if method == 'POST':  # merge-duplicates on (user_id, fen, moves, played)
            saved = []
            for new in json:
                old = next((row for row in self.mistakes
                            if all(row[key] == new[key] for key in ('user_id', 'fen', 'moves', 'played'))), None)
                if old is None:
                    old = {'id': self.nextId}
                    self.nextId += 1
                    self.mistakes.append(old)
                old.update(new)
                saved.append(dict(old))
            return saved
        rows = [row for row in self.mistakes if matches(row)]
        if method == 'PATCH':
            for row in rows:
                row.update(json)
            return None
        for part in reversed(params.get('order', '').split(',') if params.get('order') else []):
            key, direction = part.split('.')
            rows.sort(key=lambda row: row[key], reverse=direction == 'desc')
        rows = rows[:int(params['limit'])] if 'limit' in params else rows
        return [{key: row[key] for key in params['select'].split(',')} for row in rows]

    def rest(self, method, path, params=None, json=None, headers=None):
        if path == 'online_reports' and method == 'POST':
            if not any(r['game_hash'] == json['game_hash'] and r['reporter'] == json['reporter'] for r in self.reports):
                self.reports.append(dict(json, applied=False))
            return None
        if path == 'online_reports' and method == 'GET':
            gameHash = params['game_hash'][len('eq.'):]
            return [r for r in self.reports if r['game_hash'] == gameHash]
        if path == 'rpc/apply_rated_game':
            self.rpcCalls.append(json)
            if self.rpcAnswer == 'applied':
                for r in self.reports:
                    if r['game_hash'] == json['p_hash']:
                        r['applied'] = True
            return self.rpcAnswer
        if path == 'profiles' and 'username' in params:
            return [{'id': 'U1'}] if params['username'].lower() == r'ilike.duy\_t' else []
        if path == 'profiles':
            return [dict(self.profile)]
        if path == 'mistakes':
            return self.mistakesTable(method, params or {}, json)
        raise AssertionError((method, path))

    def supabase(self, method, path, token=None, **kwargs):
        if path in ('/auth/v1/recover', '/auth/v1/user') and method in ('POST', 'PUT'):
            self.authCalls.append((method, path, token, kwargs))
            return Response(self.authStatus, {} if self.authStatus < 400 else {'msg': 'refused'})
        if path.startswith('/auth/v1/admin/users/'):
            return Response(200, {'email': 'duy@example.com'})
        if path.startswith('/auth/v1/token'):
            if kwargs['json'] == {'email': 'duy@example.com', 'password': 'secret123'}:
                return Response(200, {'access_token': 't', 'refresh_token': 'r', 'user': {'id': 'U1'}})
            return Response(400, {'msg': 'Invalid login credentials'})
        raise AssertionError(path)


class Response:
    def __init__(self, status, body):
        self.status_code, self.body, self.text = status, body, str(body)

    def json(self):
        return self.body


@unittest.skipIf(api is None, "api/account.py needs flask and requests")
class AccountApiTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSupabase()
        self.patched = {name: getattr(api, name) for name in ('rest', 'supabase', 'currentUser', 'now',
                                                              'ADMIN_USERNAMES')}
        api.rest, api.supabase = self.fake.rest, self.fake.supabase
        self.user = 'W'
        api.currentUser = lambda data: self.user
        self.clock = [datetime(2026, 11, 1, 12, tzinfo=timezone.utc)]
        api.now = lambda: self.clock[0]

    def tearDown(self):
        for name, value in self.patched.items():
            setattr(api, name, value)

    def report(self, user, result, **changes):
        self.user = user
        data = {'white_id': 'W', 'black_id': 'B', 'game_id': 'g1', 'moves': 'e2e4 e7e5 g1f3 b8c6', 'result': result}
        data.update(changes)
        return api.reportOnline(data)

    def test_a_result_counts_once_both_players_report_it(self):
        self.assertTrue(self.report('W', '0-1').get('pending'))  # a concession alone doesn't count
        self.assertEqual(self.fake.rpcCalls, [])
        self.assertTrue(self.report('B', '0-1')['rated'])
        self.assertTrue(self.report('B', '0-1')['rated'])  # reported again: already counted
        self.assertEqual(len(self.fake.rpcCalls), 1)

    def test_disagreeing_reports_never_count(self):
        self.report('W', '1-0')
        self.assertTrue(self.report('B', '0-1').get('pending'))
        self.assertEqual(self.fake.rpcCalls, [])

    def test_daily_limit(self):
        self.fake.rpcAnswer = 'limit'
        self.report('W', '1/2-1/2')
        self.assertEqual(self.report('B', '1/2-1/2').get('reason'), 'daily limit')

    def test_bad_reports_are_rejected(self):
        for changes in ({'moves': 'a b c d nonce'}, {'game_id': ''}, {'white_id': 'X', 'black_id': 'Y'}):
            with self.subTest(changes=changes):
                with self.assertRaises(api.ApiError):
                    self.report('W', '1-0', **changes)

    def test_sign_in_with_email_or_username(self):
        self.assertEqual(api.login({'login': 'duy@example.com', 'password': 'secret123'})['token'], 't')
        self.assertEqual(api.login({'login': 'DUY_t', 'password': 'secret123'})['token'], 't')
        self.assertEqual(api.login({'email': 'duy@example.com', 'password': 'secret123'})['token'], 't')
        for data in ({'login': 'nobody', 'password': 'x'}, {'login': 'bad name!', 'password': 'x'},
                     {'login': 'Duy_T', 'password': 'wrong'}):
            with self.subTest(data=data):
                with self.assertRaises(api.ApiError) as caught:
                    api.login(data)
                self.assertEqual((caught.exception.status, caught.exception.message), (401, api.BAD_LOGIN))


    # --- the games reported for ratings are replayed

    def test_a_reported_game_must_be_a_legal_one(self):
        self.assertIsNotNone(api.engine, "the rules engine is found next to the function")
        self.assertTrue(self.report('W', '1-0', moves='e2e4 e7e5 g1f3 b8c6')['pending'])
        for moves in ('e2e4 e7e5 e2e4 b8c6', 'e2e4 e7e5 g1f3 d8d4', 'e2e4 e7e5 f1b5 b8c6 b5c6 d7c6 c6c7'):
            with self.subTest(moves=moves):
                with self.assertRaises(api.ApiError) as caught:
                    self.report('W', '1-0', moves=moves)
                self.assertEqual(caught.exception.message, 'The moves are not a legal game')
        # the same moves in any language: promotion pieces and castling are the engine's own
        self.assertTrue(self.report('W', '0-1', moves='e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1 f6e4')['pending'])

    def test_a_reported_result_must_fit_a_checkmate_or_a_stalemate(self):
        mate = 'f2f3 e7e5 g2g4 d8h4'  # Black mates in two moves
        self.assertTrue(self.report('W', '0-1', moves=mate)['pending'])
        for result in ('1-0', '1/2-1/2'):
            with self.subTest(result=result):
                with self.assertRaises(api.ApiError) as caught:
                    self.report('W', result, moves=mate)
                self.assertEqual(caught.exception.message, 'The result does not fit the moves')
        stalemate = ('e2e3 a7a5 d1h5 a8a6 h5a5 h7h5 h2h4 a6h6 a5c7 f7f6 c7d7 e8f7 d7b7 d8d3 b7b8 d3h7 b8c8 f7g6 c8e6')
        self.assertTrue(self.report('W', '1/2-1/2', moves=stalemate)['pending'])
        with self.assertRaises(api.ApiError):
            self.report('W', '1-0', moves=stalemate)
        # a game that was still going can end any way: resigned, out of time, a draw agreed
        for result in ('1-0', '0-1', '1/2-1/2'):
            self.assertTrue(self.report('W', result, moves='e2e4 e7e5 g1f3 b8c6')['pending'])

    def test_very_long_reports_are_not_replayed(self):
        moves = ' '.join(['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 160)  # 640 plies, shuffling the knights
        self.assertGreater(len(moves.split()), api.MAX_CHECKED_PLIES)
        self.assertTrue(self.report('W', '1/2-1/2', moves=moves)['pending'], "past the limit: accepted as it was")

    # --- forgot password

    def test_reset_link_is_sent_for_any_email(self):
        # unknown or refused addresses look the same as known ones; so does asking again within a minute (GoTrue
        # answers 429 only for a known address)
        for status in (200, 400, 404, 422, 429):
            with self.subTest(status=status):
                self.fake.authStatus = status
                self.assertEqual(api.recover({'email': 'nobody@example.com'}), {'sent': True})
        method, path, token, kwargs = self.fake.authCalls[0]
        self.assertEqual((method, path, kwargs['json']), ('POST', '/auth/v1/recover', {'email': 'nobody@example.com'}))
        self.assertEqual(kwargs['params'], {}, "no redirect asked for")
        with self.assertRaises(api.ApiError):
            api.recover({'email': 'not an email'})

    def test_reset_link_redirects_to_the_site(self):
        api.recover({'email': 'duy@example.com', 'redirect_to': 'https://chess-playing-ai.vercel.app/'})
        self.assertEqual(self.fake.authCalls[-1][3]['params'], {'redirect_to': 'https://chess-playing-ai.vercel.app/'})
        api.recover({'email': 'duy@example.com', 'redirect_to': 'javascript:alert(1)'})
        self.assertEqual(self.fake.authCalls[-1][3]['params'], {}, "only web addresses")

    def test_reset_link_service_errors(self):
        for status in (500, 503):
            with self.subTest(status=status):
                self.fake.authStatus = status
                with self.assertRaises(api.ApiError) as caught:
                    api.recover({'email': 'duy@example.com'})
                self.assertEqual(caught.exception.status, 503)

    def test_set_password(self):
        self.assertEqual(api.setPassword({'token': 'reset-token', 'password': 'newsecret1'}), {'ok': True})
        method, path, token, kwargs = self.fake.authCalls[-1]
        self.assertEqual((method, path, token, kwargs['json']),
                         ('PUT', '/auth/v1/user', 'reset-token', {'password': 'newsecret1'}))

    def test_set_password_errors(self):
        with self.assertRaises(api.ApiError) as caught:
            api.setPassword({'token': 'reset-token', 'password': 'short'})
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.fake.authCalls, [], "a short password isn't sent")
        for status, expected in ((401, 401), (403, 401), (422, 400), (429, 503), (500, 503)):
            with self.subTest(status=status):
                self.fake.authStatus = status
                with self.assertRaises(api.ApiError) as caught:
                    api.setPassword({'token': 'old-token', 'password': 'newsecret1'})
                self.assertEqual(caught.exception.status, expected)
                if status in (401, 403):
                    self.assertEqual(caught.exception.message, api.RESET_LINK_EXPIRED)

    def test_admin_accounts(self):
        self.assertIs(api.getProfile('U1')['admin'], False)
        saved = api.ADMIN_USERNAMES
        api.ADMIN_USERNAMES = {'duy_t'}  # matched whatever the case
        try:
            self.assertIs(api.getProfile('U1')['admin'], True)
        finally:
            api.ADMIN_USERNAMES = saved
        self.assertIn('congduytran12', api.ADMIN_USERNAMES)

    def test_new_actions_are_routed(self):
        self.assertIs(api.ACTIONS['recover'], api.recover)
        self.assertIs(api.ACTIONS['set_password'], api.setPassword)
        self.assertEqual(api.GAMES_LISTED, 50)
        self.assertIs(api.ACTIONS['save_mistakes'], api.saveMistakes)
        self.assertIs(api.ACTIONS['mistakes'], api.listMistakes)
        self.assertIs(api.ACTIONS['mistake_result'], api.mistakeResult)

    # --- Premium

    def test_premium_comes_from_the_profile(self):
        self.assertIs(api.getProfile('U1')['premium'], False, "a table without the column yet")
        self.fake.profile['premium_until'] = '2026-12-01T12:00:00+00:00'
        profile = api.getProfile('U1')
        self.assertEqual((profile['premium'], profile['premium_until']), (True, '2026-12-01T12:00:00+00:00'))
        self.assertEqual(set(profile), {'id', 'username', 'rating', 'rated_games', 'premium_until', 'admin', 'premium'})
        self.fake.profile['premium_until'] = '2026-11-01T11:59:59.5+00:00'
        self.assertIs(api.getProfile('U1')['premium'], False, "it ended")
        self.fake.profile['premium_until'] = None
        api.ADMIN_USERNAMES = {'duy_t'}
        self.assertIs(api.getProfile('U1')['premium'], True, "an admin has it too")

    def test_times_from_the_database(self):
        for text in ('2026-11-01T12:00:00+00:00', '2026-11-01T12:00:00Z', '2026-11-01T12:00:00.000+00:00',
                     '2026-11-01T19:00:00+07:00'):
            self.assertEqual(api.parseTime(text), self.clock[0], text)
        self.assertEqual(api.parseTime('2026-11-01T12:00:00.1234567+00:00'),
                         self.clock[0] + timedelta(microseconds=123456))
        for value in (None, '', 'soon', 5):
            self.assertIsNone(api.parseTime(value))

    # --- your mistakes: kept from analyzed games, then practised as puzzles

    def mistake(self, **changes):
        """A mistake as the game sends it: after 1. f3 e5, 2. g4?? (2. e4 is best)."""
        item = {'fen': AFTER_F3, 'moves': 'e7e5 e2e4', 'played': 'g2g4', 'score': 0.1, 'loss': 10.1,
                'opponent': 'Computer (Hard)', 'ply': 2}
        item.update(changes)
        return item

    def test_mistakes_are_checked_and_kept_once(self):
        self.user = 'U1'
        kept = api.saveMistakes({'mistakes': [self.mistake(), self.mistake(fen=AFTER_E4, moves='e7e5 g1f3',
                                                                               played='d1h5', score=55)]})['mistakes']
        self.assertEqual([(row['id'], row['played']) for row in kept], [(1, 'g2g4'), (2, 'd1h5')])
        first, second = self.fake.mistakes
        self.assertEqual((first['user_id'], first['solved'], first['opponent']), ('U1', 0, 'Computer (Hard)'))
        self.assertEqual(second['score'], api.MISTAKE_SCORE_CAP, "a mate is kept as a won position")
        self.assertEqual(first['due_at'], first['found_at'], "due at once")
        first['solved'] = 1
        self.clock[0] += timedelta(days=1)
        again = api.saveMistakes({'mistakes': [self.mistake()]})['mistakes']
        self.assertEqual((again[0]['id'], len(self.fake.mistakes)), (1, 2), "made again: kept once")
        self.assertEqual((first['solved'], api.parseTime(first['found_at'])), (0, self.clock[0]), "and it starts over")

    def test_what_isnt_a_mistake_is_refused(self):
        self.user = 'U1'
        for changes in ({'fen': 'nonsense'}, {'fen': '8/8/8/8/8/8/8/8 w - - 0 1'}, {'moves': 'e7e5'},
                        {'moves': 'e7e5 e2e5'}, {'moves': 'e2e4 e7e5'}, {'played': 'e2e4'}, {'played': 'a1a8'},
                        {'score': float('nan')}, {'score': True}, {'loss': '3'}, {'ply': 0}, {'ply': 'two'}):
            with self.subTest(changes=changes):
                with self.assertRaises(api.ApiError):
                    api.saveMistakes({'mistakes': [self.mistake(**changes)]})
        for data in ({}, {'mistakes': []}, {'mistakes': 'all'}, {'mistakes': [self.mistake()] * 31}):
            with self.assertRaises(api.ApiError):
                api.saveMistakes(data)
        self.assertEqual(self.fake.mistakes, [], "nothing kept")

    def test_free_accounts_practise_the_latest_game_premium_every_due_one(self):
        self.user = 'U1'
        api.saveMistakes({'mistakes': [self.mistake()]})  # the first game
        self.clock[0] += timedelta(days=1)
        api.saveMistakes({'mistakes': [self.mistake(fen=AFTER_E4, moves='e7e5 g1f3', played='d1h5'),
                                       self.mistake(fen=AFTER_E4, moves='e7e5 b1c3', played='f2f3')]})
        free = api.listMistakes({})
        self.assertEqual([row['played'] for row in free['mistakes']], ['d1h5', 'f2f3'], "the latest game's")
        self.assertEqual((free['premium'], free['total'], free['locked'], free['next_due']), (False, 3, 1, None))
        self.assertEqual(set(free['mistakes'][0]),
                         {'id', 'fen', 'moves', 'played', 'score', 'loss', 'opponent', 'ply', 'solved'})
        self.fake.profile['premium_until'] = '2027-01-01T00:00:00+00:00'
        premium = api.listMistakes({})
        self.assertEqual([row['played'] for row in premium['mistakes']], ['g2g4', 'd1h5', 'f2f3'],
                         "every game's, the longest due first")
        self.assertEqual((premium['premium'], premium['locked']), (True, 0))
        for row in premium['mistakes']:
            api.mistakeResult({'id': row['id'], 'solved': True})
        later = api.listMistakes({})
        self.assertEqual(later['mistakes'], [], "none is due")
        self.assertEqual(api.parseTime(later['next_due']), self.clock[0] + api.MISTAKE_LATER, "and when one is")
        self.clock[0] += api.MISTAKE_LATER
        self.assertEqual(len(api.listMistakes({})['mistakes']), 3, "they come back")

    def test_practice_until_a_mistake_is_learned(self):
        self.user = 'U1'
        mistakeId = api.saveMistakes({'mistakes': [self.mistake()]})['mistakes'][0]['id']
        result = api.mistakeResult({'id': mistakeId, 'solved': True})
        self.assertEqual((result['solved'], result['learned']), (1, False))
        self.assertEqual(api.parseTime(result['due_at']), self.clock[0] + api.MISTAKE_LATER)
        missed = api.mistakeResult({'id': mistakeId, 'solved': False})
        self.assertEqual((missed['solved'], api.parseTime(missed['due_at'])), (0, self.clock[0] + api.MISTAKE_AGAIN),
                         "a miss starts it over, soon")
        api.mistakeResult({'id': mistakeId, 'solved': True})
        self.assertTrue(api.mistakeResult({'id': mistakeId, 'solved': True})['learned'])
        listed = api.listMistakes({})
        self.assertEqual((listed['mistakes'], listed['total']), ([], 0), "a learned mistake doesn't come back")
        self.user = 'U2'
        with self.assertRaises(api.ApiError) as caught:
            api.mistakeResult({'id': mistakeId, 'solved': True})
        self.assertEqual(caught.exception.status, 404, "another player's")
        for bad in ('1', True, None):
            with self.assertRaises(api.ApiError):
                api.mistakeResult({'id': bad, 'solved': True})


AFTER_F3 = 'rnbqkbnr/pppppppp/8/8/8/5P2/PPPPP1PP/RNBQKBNR b KQkq - 0 1'
AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'


if __name__ == '__main__':
    unittest.main()
