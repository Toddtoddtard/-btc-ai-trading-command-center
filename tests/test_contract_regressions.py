import tempfile
import time
import unittest
from unittest.mock import patch
import kalshi_paper_engine as engine


class ContractRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = self.tmp.name + '/paper.db'
        self.decision = dict(action='LOCK UP', kalshi_ticker='KXBTC15M-TEST',
                             kalshi_close_ts=time.time()+900, target_price=100,
                             yes_ask_dollars=.50, yes_bid_dollars=.48,
                             no_ask_dollars=.52, no_bid_dollars=.50)
        self.risk = dict(approved=True, position_pct=.1)

    def open(self):
        self.assertTrue(engine.open_position(self.db, 500, self.decision, self.risk, 100))

    def expire(self):
        with engine._connect(self.db) as conn:
            conn.execute('UPDATE kalshi_paper_positions SET expires_at=1')

    def cycle(self, result=None, spot=100, enabled=True):
        return engine.manage_kalshi_paper_cycle(self.db, 500, self.decision, self.risk,
                                               spot, enabled=enabled, settlement_reader=lambda _: result)

    def test_delayed_settlement_ignores_spot(self):
        self.open()
        self.expire()
        self.assertIn('Awaiting', self.cycle(spot=10000)['message'])
        self.assertEqual(engine.paper_summary(self.db)['samples'], 0)
        self.cycle('yes', spot=1)
        summary = engine.paper_summary(self.db)
        self.assertEqual(summary['wins'], 1)
        self.assertAlmostEqual(summary['equity'], summary['cash'])
        self.assertAlmostEqual(summary['total_pnl'], summary['cash']-500)

    def test_no_settles_from_official_result(self):
        self.decision['action'] = 'LOCK DOWN'
        self.open()
        self.expire()
        self.cycle('no', spot=10000)
        self.assertEqual(engine.paper_summary(self.db)['wins'], 1)

    def test_official_loss(self):
        self.open()
        self.expire()
        self.cycle('no', spot=10000)
        self.assertEqual(engine.paper_summary(self.db)['losses'], 1)

    def test_allocation_includes_fees(self):
        self.open()
        self.assertGreaterEqual(engine.paper_summary(self.db)['cash'], 450)

    def test_paused_blocks_entry_but_settles_existing(self):
        self.cycle(enabled=False)
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.open()
        self.expire()
        self.cycle('yes', enabled=False)
        self.assertEqual(engine.paper_summary(self.db)['samples'], 1)

    def test_expired_or_invalid_quote_cannot_open(self):
        self.decision['kalshi_close_ts'] = 1
        self.assertIsNone(engine.open_position(self.db, 500, self.decision, self.risk, 100))
        self.decision['kalshi_close_ts'] = time.time()+900
        for quote in (0, 1, -1, 2, float('nan')):
            self.decision['yes_ask_dollars'] = quote
            self.assertIsNone(engine.open_position(self.db, 500, self.decision, self.risk, 100))

    def test_persistent_lock_and_duplicate_close(self):
        self.open()
        self.assertEqual(engine.persistent_lock_side(self.db, self.decision['kalshi_ticker']), 'YES')
        conn = engine._connect(self.db)
        self.addCleanup(conn.close)
        row = conn.execute('SELECT * FROM kalshi_paper_positions').fetchone()
        engine._close(conn, row, 1, 'TEST', False)
        cash = engine.paper_summary(self.db)['cash']
        self.assertFalse(engine._close(conn, row, 1, 'TEST', False)['event'])
        self.assertEqual(engine.paper_summary(self.db)['cash'], cash)

    def test_open_pnl_reconciles_and_uses_bid(self):
        self.open()
        self.cycle()
        summary = engine.paper_summary(self.db)
        pos = summary['open_position']
        liquidation = pos['contracts']*.48-engine.kalshi_taker_fee(pos['contracts'], .48)
        self.assertAlmostEqual(summary['equity'], summary['cash']+liquidation)
        self.assertLess(summary['unrealized_pnl'], 0)

    def test_zero_bid_is_not_invented_cent(self):
        self.assertEqual(engine._quote({'yes_bid_dollars': 0}, 'YES'), 0)

    def test_official_reader_rejects_unfinalized_or_wrong_ticker(self):
        for market in ({'ticker':'other','status':'settled','result':'yes'},
                       {'ticker':'T','status':'determined','result':'yes'}):
            with patch.object(engine, 'urlopen'), patch.object(engine.json, 'load', return_value={'market': market}):
                self.assertIsNone(engine.fetch_settled_result('T'))
