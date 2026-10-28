"""Standalone regression/HTTP contract checks; stdlib only, never trades."""
import json
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from bot import Handler
from yeno_evaluator.execution import buy, sell

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT / 'yeno-sample-observation.json').read_text())


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, data=None):
        payload = json.dumps(data).encode() if not isinstance(data, bytes) else data
        req = Request(self.url + path, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=1.5) as res:
                return res.status, json.load(res)
        except HTTPError as err:
            return err.code, json.loads(err.read())

    def test_starter_contract(self):
        status, result = self.request('/decide', sample())
        self.assertEqual(status, 200)
        self.assertIn(result['action'], ('BUY', 'SELL', 'HOLD'))
        if result['action'] == 'BUY':
            self.assertIn(result['outcome'], ('YES', 'NO'))
            self.assertTrue(0 < result['maxCashUsd'] <= 5)

    def test_bad_json_and_path(self):
        self.assertEqual(self.request('/decide', b'{invalid')[0], 400)
        self.assertEqual(self.request('/wrong', sample())[0], 404)

    def test_nonobject_rejected_as_hold(self):
        self.assertEqual(self.request('/decide', [1, 2]), (200, {'action': 'HOLD'}))

    def test_malformed_depth_fails_closed(self):
        obs = sample()
        obs['books']['YES']['bids'] = [[]]
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))
        obs['account']['position'] = {'outcome': 'YES', 'shares': 5}
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))

    def test_missing_books_fails_closed(self):
        obs = sample()
        obs['books'] = None
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))
        obs['account']['position'] = {'outcome': 'YES', 'shares': 5}
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'SELL'}))

    def test_invalid_buy_cash_cannot_exceed_available(self):
        obs = sample()
        obs['account']['cashUsd'] = 0.01
        status, answer = self.request('/decide', obs)
        self.assertEqual(status, 200)
        self.assertNotEqual(answer['action'], 'BUY')

    def test_causal_invalid_reference_over_http(self):
        from copy import deepcopy
        obs = deepcopy(sample())
        obs['reference']['observedAt'] = obs['timestamp'] + 1
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))
        obs['reference']['observedAt'] = float('nan')
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))
        obs['account'] = None
        self.assertEqual(self.request('/decide', obs), (200, {'action': 'HOLD'}))

    def test_deep_book_latency(self):
        obs = sample()
        # One-sided 1000-level book; worst-case quantity accumulates slowly.
        obs['books']['YES']['asks'] = [[round(.50 + .0001 * i, 5), .005] for i in range(1000)]
        obs['books']['YES']['bids'] = [[round(.49 - .0001 * i, 5), .005] for i in range(1000)]
        elapsed = []
        for _ in range(12):
            started = time.perf_counter()
            status, answer = self.request('/decide', obs)
            elapsed.append(time.perf_counter() - started)
            self.assertEqual(status, 200)
            self.assertIn(answer['action'], ('BUY', 'HOLD', 'SELL'))
        self.assertLess(sorted(elapsed)[-2], .2, f'second-worst {elapsed}')


class ExecutionTests(unittest.TestCase):
    def test_minimum_share_budget(self):
        asks = [[.50, 5], [.52, 20]]
        fill = buy(asks, 5., max_shares=5)
        self.assertAlmostEqual(fill.shares, 5., places=8)
        self.assertLessEqual(fill.gross + fill.fees, 5.0000001)

    def test_full_affordable_buy_and_unaffordable_fallback(self):
        # Full-book fast path and binary-search fallback must both respect
        # fee-inclusive caps and min-order share semantics.
        asks = [[.50, 5.], [.52, 8.]]
        full = buy(asks, 4.85, max_shares=5.)
        self.assertAlmostEqual(full.shares, 5., places=9)
        self.assertLessEqual(full.gross + full.fees, 4.85 + 1e-9)
        constrained = buy(asks, 2., max_shares=5.)
        self.assertLess(constrained.shares, 5. - 1e-9)
        self.assertLessEqual(constrained.gross + constrained.fees, 2. + 1e-9)

    def test_full_buy_with_adverse_cost(self):
        asks = [[.62, 7.], [.65, 11.]]
        full = buy(asks, 5., max_shares=5., adverse=.01)
        self.assertAlmostEqual(full.shares, 5., places=9)
        self.assertLessEqual(full.gross + full.fees, 5.0000001)
        partial = buy(asks, 2., max_shares=5., adverse=.01)
        self.assertLess(partial.shares, 5. - 1e-9)
        self.assertLessEqual(partial.gross + partial.fees, 2.0000001)

    def test_fee_layers(self):
        fill = sell([[.50, 5]], 5)
        self.assertAlmostEqual(fill.gross, 2.5)
        self.assertAlmostEqual(fill.fees, .1125, places=5)


class CausalReferenceTests(unittest.TestCase):
    def test_reference_future_and_nonfinite_are_hold(self):
        from bot import decide
        from copy import deepcopy
        base = sample()
        self.assertEqual(decide(deepcopy(base))['action'], 'BUY')
        for field, value in [
            ('observedAt', base['timestamp'] + .01),
            ('observedAt', float('nan')),
            ('targetObservedAt', float('nan')),
            ('btcMidUsd', float('nan')),
            ('btcMidUsd', float('inf')),
            ('openingTargetUsd', float('nan')),
            ('openingTargetUsd', -1),
        ]:
            obs = deepcopy(base)
            obs['reference'][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(decide(obs), {'action': 'HOLD'})

    def test_malformed_account_and_cash_fail_closed(self):
        from bot import decide
        from copy import deepcopy
        base = sample()
        for value in (None, [], 'bad'):
            obs = deepcopy(base)
            obs['account'] = value
            with self.subTest(value=value):
                self.assertEqual(decide(obs), {'action': 'HOLD'})
        for value in (float('nan'), float('inf'), float('-inf')):
            obs = deepcopy(base)
            obs['account']['cashUsd'] = value
            with self.subTest(cash=value):
                self.assertEqual(decide(obs), {'action': 'HOLD'})

    def test_invalid_clock_fails_closed(self):
        from bot import decide
        from copy import deepcopy
        base = sample()
        for field, value in [
            ('timestamp', float('nan')),
            ('timestamp', float('inf')),
            ('secondsToClose', float('nan')),
            ('secondsToClose', float('inf')),
        ]:
            obs = deepcopy(base)
            if field == 'secondsToClose':
                obs['market'][field] = value
            else:
                obs[field] = value
            with self.subTest(field=field):
                self.assertEqual(decide(obs), {'action': 'HOLD'})

    def test_zero_cash_does_not_block_forced_sell(self):
        from bot import decide
        from copy import deepcopy
        obs = deepcopy(sample())
        obs['account']['cashUsd'] = 0
        obs['account']['position'] = {'outcome': 'YES', 'shares': 5}
        obs['market']['secondsToClose'] = 20
        self.assertEqual(decide(obs), {'action': 'SELL'})


if __name__ == '__main__':
    unittest.main()
