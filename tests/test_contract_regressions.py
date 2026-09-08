import tempfile
import time
import unittest
import sqlite3
from pathlib import Path
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
                             no_ask_dollars=.52, no_bid_dollars=.50,
                             confidence=.95)
        self.risk = dict(approved=True, position_pct=.1)

    def open(self):
        result = engine.open_position(self.db, 500, self.decision, self.risk, 100)
        self.assertTrue(result)
        return result

    def expire(self):
        with engine._connect(self.db) as conn:
            conn.execute('UPDATE kalshi_paper_positions SET expires_at=1')

    def cycle(self, result=None, spot=100, enabled=True):
        return engine.manage_kalshi_paper_cycle(self.db, 500, self.decision, self.risk,
                                               spot, enabled=enabled, settlement_reader=lambda _: result)

    def test_existing_database_migrates_spot_entry_column(self):
        legacy_db = self.tmp.name + '/legacy.db'
        with sqlite3.connect(legacy_db) as conn:
            conn.execute(
                """CREATE TABLE kalshi_paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT, side TEXT, strategy TEXT, status TEXT,
                    opened_at REAL, entry_price REAL, contracts INTEGER,
                    entry_fee REAL
                )"""
            )
        with engine._connect(legacy_db) as conn:
            columns = {
                row['name'] for row in conn.execute(
                    'PRAGMA table_info(kalshi_paper_positions)'
                )
            }
        self.assertIn('spot_entry_price', columns)

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
        event = self.open()
        summary = engine.paper_summary(self.db)
        self.assertGreaterEqual(summary['cash'], 450)
        self.assertAlmostEqual(summary['open_position']['amount_down'], 500-summary['cash'])
        self.assertIn('Amount: $', event['message'])
        self.assertIn('Kalshi entry: 50%', event['message'])
        self.assertNotIn(self.decision['kalshi_ticker'], event['message'])
        self.assertNotIn(' contracts ', event['message'])
        self.assertNotIn(' @ ', event['message'])

    def test_authoritative_history_matches_open_and_closed_positions(self):
        self.open()
        opened = engine.paper_history(self.db)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]['status'], 'OPEN')
        self.assertEqual(opened[0]['direction'], 'UP')
        self.assertEqual(opened[0]['result'], 'OPEN')
        self.assertAlmostEqual(
            opened[0]['amount'],
            engine.paper_summary(self.db)['open_position']['amount_down'],
        )
        self.assertNotIn('ticker', opened[0])
        marker = engine.paper_chart_entries(
            self.db, self.decision['kalshi_ticker']
        )[0]
        self.assertEqual(marker['direction'], 'UP')
        self.assertEqual(marker['strategy'], 'LOCK')
        self.assertEqual(marker['kalshi_entry_pct'], 50.0)
        self.assertEqual(marker['spot_entry_price'], 100.0)

        self.expire()
        self.cycle('yes')
        closed = engine.paper_history(self.db)[0]
        self.assertEqual(closed['status'], 'CLOSED')
        self.assertEqual(closed['result'], 'WIN')
        self.assertAlmostEqual(closed['pnl'], engine.paper_summary(self.db)['realized_pnl'])

    def test_scalp_requires_projected_fifteen_point_move(self):
        self.decision.update(action='SCALP UP', confidence=.64)
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('15-point minimum move', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

        # At a 50% entry, a 65% selected-side forecast qualifies exactly.
        self.decision['confidence'] = .65
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(engine.paper_summary(self.db)['open_position']['entry_price'], .50)

    def test_scalp_takes_profit_after_fifteen_contract_points(self):
        self.decision.update(action='SCALP UP', confidence=.80)
        self.open()
        self.decision['yes_bid_dollars'] = .64
        self.assertFalse(self.cycle()['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])
        self.decision['yes_bid_dollars'] = .65
        closed = self.cycle()
        self.assertTrue(closed['event'])
        with engine._connect(self.db) as conn:
            reason = conn.execute(
                'SELECT exit_reason FROM kalshi_paper_positions ORDER BY id DESC LIMIT 1'
            ).fetchone()['exit_reason']
        self.assertEqual(reason, 'TAKE_PROFIT_15_POINTS')
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_lock_ignores_normal_opposite_signal(self):
        self.open()
        self.decision.update(
            action='LOCK DOWN',
            score=-.90,
            whale_score=0.0,
            whale_confidence=.99,
        )
        result = self.cycle()
        self.assertFalse(result['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

    def test_lock_holds_through_strong_confirmed_whale_reversal(self):
        self.open()
        self.decision.update(
            action='LOCK DOWN',
            score=-.50,
            whale_score=-.90,
            whale_confidence=.95,
            yes_bid_dollars=.45,
        )
        result = self.cycle()
        self.assertFalse(result['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

    def test_lock_sells_when_its_bid_reaches_ninety_five_percent(self):
        self.open()
        self.decision['yes_bid_dollars'] = .94
        self.assertFalse(self.cycle()['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])
        self.decision['yes_bid_dollars'] = .95
        closed = self.cycle()
        self.assertTrue(closed['event'])
        with engine._connect(self.db) as conn:
            reason = conn.execute(
                'SELECT exit_reason FROM kalshi_paper_positions ORDER BY id DESC LIMIT 1'
            ).fetchone()['exit_reason']
        self.assertEqual(reason, 'LOCK_BID_95_PCT')
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_lock_requires_ninety_five_percent_confidence(self):
        self.decision['confidence'] = .949
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('below the 95% minimum', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

        self.decision['confidence'] = .95
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(engine.paper_summary(self.db)['open_position']['strategy'], 'LOCK')

    def test_only_one_lock_entry_is_allowed_per_market(self):
        self.open()
        self.decision['yes_bid_dollars'] = .95
        self.assertTrue(self.cycle()['event'])
        self.decision['yes_bid_dollars'] = .48
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('1 LOCK already entered', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_at_most_ten_scalps_are_allowed_per_market(self):
        self.decision.update(action='SCALP UP', confidence=.80)
        for _ in range(10):
            self.decision.update(yes_ask_dollars=.50, yes_bid_dollars=.48)
            self.assertTrue(self.cycle()['event'])
            self.decision['yes_bid_dollars'] = .65
            self.assertTrue(self.cycle()['event'])

        self.decision.update(yes_ask_dollars=.50, yes_bid_dollars=.48)
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('10 SCALPs already entered', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_decision_lock_is_independent_immutable_and_expires(self):
        ticker = self.decision['kalshi_ticker']
        expiry = time.time() + 900
        self.assertEqual(
            engine.register_decision_lock(self.db, ticker, 'UP', expiry),
            'YES',
        )
        # A later opposite call for the same window cannot replace the first.
        self.assertEqual(
            engine.register_decision_lock(self.db, ticker, 'DOWN', expiry),
            'YES',
        )
        self.assertEqual(engine.persistent_lock_side(self.db, ticker), 'YES')
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

        with engine._connect(self.db) as conn:
            conn.execute(
                'UPDATE kalshi_decision_locks SET expires_at=1 WHERE ticker=?',
                (ticker,),
            )
        self.assertIsNone(engine.persistent_lock_side(self.db, ticker))

    def test_paper_tab_has_one_authoritative_summary(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'app.py').read_text()
        paper_tab = source.split('    with tab_paper:', 1)[1].split(
            '    with tab_journal:', 1
        )[0]
        canonical_import = (
            'from kalshi_paper_engine import manage_kalshi_paper_cycle, '
            'paper_chart_entries, paper_history, paper_summary, persistent_lock_side'
        )
        legacy_import = (
            'from kalshi_paper_engine import manage_kalshi_paper_cycle, '
            'paper_summary, persistent_lock_side'
        )
        self.assertEqual(paper_tab.count('k1.metric("Contract Equity"'), 1)
        self.assertEqual(paper_tab.count('Automatic Kalshi Paper Trade Log'), 1)
        self.assertNotIn("['contracts']} contracts", paper_tab)
        self.assertNotIn("['ticker']} • entry", paper_tab)
        self.assertEqual(source.count(canonical_import), 1)
        self.assertNotIn(legacy_import + '\n', source)
        self.assertIn('if _lock_was_already_persisted:', source)
        self.assertIn('def _register_window_lock(', source)
        self.assertIn('_persistent_window_lock_side(current_ticker)', source)
        self.assertNotIn('hold this call until Kalshi market expiration', source)
        self.assertNotIn('to the end of the current Kalshi 15-minute market', source)
        self.assertIn('paper position sells at a 95% executable bid', source)
        self.assertIn('paper position sells at a 95% bid', source)
        self.assertIn('[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p', source)
        self.assertIn('a[aria-label="Link to heading"]', source)
        self.assertIn('with ThreadPoolExecutor(max_workers=6', source)
        self.assertEqual(source.count('pool.submit(fetch_'), 6)
        self.assertIn('ticker = ticker_job.result()', source)
        self.assertIn('raw_hist, kline_ms = kline_job.result()', source)
        self.assertIn('agg, agg_ms = agg_job.result()', source)
        self.assertIn('latest_trade_price = (', source)
        self.assertIn('price = latest_trade_price', source)
        self.assertIn('live_close_ts = kalshi_close_timestamp(kctx)', source)
        self.assertIn('live_close_ts - time.time()', source)
        self.assertIn('components.html(_live_countdown_html, height=72', source)
        self.assertIn('setInterval(renderInlineCountdown, 250)', source)
        self.assertIn('function paperEntryTrace()', source)
        self.assertIn('paper_entries=_persistent_paper_entries', source)
        self.assertIn("Entered at {_call_entries[-1]", source)
        self.assertIn(
            'Math.min(TOTAL,Math.max(0,(closeMs-Date.now())/1000))',
            source,
        )
        self.assertIn(
            'Math.min(15 * 60, Math.max(0, Math.floor((closeMs - Date.now()) / 1000)))',
            source,
        )
        self.assertIn(
            'int(min(15 * 60, max(0, live_close_ts - time.time())))',
            source,
        )
        self.assertIn(
            'select_slider("Dashboard refresh", options=[1, 2, 3, 5, 10, 15, 30, 60], value=1',
            source,
        )

        installer = (
            root / 'tools' / 'apply_kalshi_contract_paper_v1.py'
        ).read_text()
        self.assertNotIn('APP_VERSION = "', installer)

    def test_paused_blocks_entry_but_settles_existing(self):
        self.cycle(enabled=False)
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.open()
        self.expire()
        self.cycle('yes', enabled=False)
        self.assertEqual(engine.paper_summary(self.db)['samples'], 1)

    def test_automatic_entries_stop_above_seventy_five_percent(self):
        self.decision['yes_ask_dollars'] = .85
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('85%', skipped['message'])
        self.assertIn('75% maximum', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

        # Exactly 75% remains eligible; only prices above the ceiling are denied.
        self.decision['yes_ask_dollars'] = .75
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(
            engine.paper_summary(self.db)['open_position']['entry_price'],
            .75,
        )

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
