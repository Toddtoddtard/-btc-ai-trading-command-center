import unittest
import io
import json
from unittest.mock import patch

import background_paper as bg
from tests import test_background_paper as fixtures


class PaperLiquidityTests(unittest.TestCase):
    def test_live_market_reader_uses_depth_quotes_and_marks_failed_depth(self):
        market = fixtures.BackgroundPaperTests.market()
        book = {'orderbook_fp': {'yes_dollars': [['0.40', '3']], 'no_dollars': [['0.55', '2']]}}
        def read(request, **kwargs):
            return io.BytesIO(json.dumps(book if request.full_url.endswith('/orderbook')
                                         else {'market': market}).encode())
        with patch.object(bg, 'urlopen', side_effect=read):
            result = bg._market(market['ticker'])
        self.assertAlmostEqual(bg._quotes(result, 'YES')[1], .45)
        self.assertEqual(result['execution_book']['yes_ask_size'], 2)
        def failed_depth(request, **kwargs):
            if request.full_url.endswith('/orderbook'):
                raise OSError('depth unavailable')
            return read(request, **kwargs)
        with patch.object(bg, 'urlopen', side_effect=failed_depth):
            result = bg._market(market['ticker'])
        self.assertFalse(result['execution_book']['available'])

    def test_entry_is_capped_at_observed_ask_size(self):
        state = fixtures.BackgroundPaperTests().pending()
        market = fixtures.BackgroundPaperTests.market(execution_book={
            'available': True, 'yes_ask_size': 2.8, 'yes_bid_size': 20},
            quotes_observed_at=1000)
        paper = bg.run_cycle(state, lambda _: market, now=1000)
        self.assertEqual(paper['open_position']['contracts'], 2)
        self.assertEqual(paper['open_position']['fill_basis'], 'OBSERVED_TOP_OF_BOOK')

    def test_missing_depth_or_old_quote_cannot_create_fill(self):
        for book, observed in (({'available': False}, 1000),
                               ({'available': True, 'yes_ask_size': 0}, 1000),
                               ({'available': True, 'yes_ask_size': 20}, 969)):
            state = fixtures.BackgroundPaperTests().pending()
            market = fixtures.BackgroundPaperTests.market(execution_book=book, quotes_observed_at=observed)
            paper = bg.run_cycle(state, lambda _: market, now=1000)
            self.assertIsNone(paper['open_position'])

    def test_bid_depth_cannot_fill_a_larger_exit(self):
        state = fixtures.BackgroundPaperTests().pending()
        market = fixtures.BackgroundPaperTests.market(execution_book={
            'available': True, 'yes_ask_size': 20, 'yes_bid_size': 20},
            quotes_observed_at=1000)
        paper = bg.run_cycle(state, lambda _: market, now=1000)
        self.assertIsNotNone(paper['open_position'])
        state['pending']['would_wait'] = True
        market.update(yes_bid_dollars=.65, yes_ask_dollars=.67, quotes_observed_at=1010,
                      execution_book={'available': True, 'yes_bid_size': 1})
        paper = bg.run_cycle(state, lambda _: market, now=1010)
        self.assertIsNotNone(paper['open_position'])
        self.assertIn('depth', paper['last_message'])
        market['execution_book']['yes_bid_size'] = 100
        paper = bg.run_cycle(state, lambda _: market, now=1011)
        self.assertIsNone(paper['open_position'])
