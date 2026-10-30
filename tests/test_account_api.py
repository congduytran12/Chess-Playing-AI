# api/account.py against an in-memory stand-in for Supabase (no network)
import unittest

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
            return [{'id': 'U1', 'username': 'Duy_T', 'rating': 1200, 'rated_games': 0}]
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
        self.patched = {name: getattr(api, name) for name in ('rest', 'supabase', 'currentUser')}
        api.rest, api.supabase = self.fake.rest, self.fake.supabase
        self.user = 'W'
        api.currentUser = lambda data: self.user

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


    # --- forgot password

    def test_reset_link_is_sent_for_any_email(self):
        for status in (200, 400, 404, 422):  # unknown or refused addresses look the same as known ones
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
        for status in (429, 500, 503):
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

    def test_new_actions_are_routed(self):
        self.assertIs(api.ACTIONS['recover'], api.recover)
        self.assertIs(api.ACTIONS['set_password'], api.setPassword)
        self.assertEqual(api.GAMES_LISTED, 50)


if __name__ == '__main__':
    unittest.main()
