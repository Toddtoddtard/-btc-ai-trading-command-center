import unittest
from unittest.mock import patch

import learner
from kalshi_microstructure import orderbook_features


class MarketInputIntegrityTests(unittest.TestCase):
    def test_legacy_one_cent_book_does_not_become_one_dollar(self):
        book = orderbook_features({'orderbook': {'yes': [[1, 20]], 'no': [[98, 30]]}})
        self.assertAlmostEqual(book['yes_bid'], .01)
        self.assertAlmostEqual(book['yes_ask'], .02)
        self.assertAlmostEqual(book['midpoint'], .015)

    def test_invalid_dollar_level_is_not_reinterpreted_as_cents(self):
        book = orderbook_features({'orderbook_fp': {'yes_dollars': [['1.50', '20']]}})
        self.assertFalse(book['available'])

    def test_empty_fixed_point_side_does_not_use_legacy_side(self):
        book = orderbook_features({'orderbook_fp': {'yes_dollars': [], 'yes': [[80, 20]]}})
        self.assertIsNone(book['yes_bid'])

    def test_learner_midpoint_uses_legacy_quotes_when_book_unavailable(self):
        market = {'ticker': 'TEST', 'close_time': '2026-01-01T00:15:00Z',
                  'floor_strike': 100000, 'status': 'active', 'yes_bid': 70, 'yes_ask': 74}
        with patch.object(learner.time, 'time', return_value=1767225600), \
             patch.object(learner, 'kalshi_get', return_value={'markets': [market]}), \
             patch.object(learner, 'exact_market', return_value=market), \
             patch.object(learner, 'orderbook', return_value={}):
            result = learner.market()
        self.assertAlmostEqual(result['prob'], .72)

    def test_learner_rejects_wrong_exact_market(self):
        market = {'ticker': 'TEST', 'close_time': '2026-01-01T00:15:00Z',
                  'floor_strike': 100000, 'status': 'active'}
        with patch.object(learner.time, 'time', return_value=1767225600), \
             patch.object(learner, 'kalshi_get', return_value={'markets': [market]}), \
             patch.object(learner, 'exact_market', return_value={**market, 'ticker': 'OTHER'}), \
             patch.object(learner, 'orderbook', return_value={}):
            self.assertIsNone(learner.market())
