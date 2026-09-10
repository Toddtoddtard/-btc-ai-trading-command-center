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
                             confidence=.95, scalp_projected_exit_price=.80)
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

    def test_existing_database_migrates_entry_marker_columns(self):
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
        self.assertIn('opposite_since', columns)

    def test_unproven_post_fix_trades_are_capped_at_two_percent(self):
        self.open()
        opened = engine.paper_summary(self.db)['open_position']
        self.assertLessEqual(opened['amount_down'], 500 * .02 + .01)

    def test_post_fix_scorecard_uses_authoritative_kalshi_ledger(self):
        self.open()
        self.expire()
        self.cycle('yes')
        scorecard = engine.paper_performance_since_update(
            self.db, opened_since=0
        )
        self.assertEqual(scorecard['samples'], 1)
        self.assertEqual(scorecard['markets'], 1)
        self.assertGreater(scorecard['total_pnl'], 0)
        self.assertGreater(scorecard['fees'], 0)
        self.assertEqual(scorecard['validation_sample_target'], 100)

    def test_profitability_gate_waits_for_meaningful_sample(self):
        gate = engine.scalp_profitability_gate(self.db)
        self.assertTrue(gate['approved'])
        self.assertEqual(gate['status'], 'COLLECTING EVIDENCE')

    def test_profitability_gate_pauses_losing_scalps_after_fifty(self):
        with engine._connect(self.db) as conn:
            now = time.time()
            for index in range(50):
                conn.execute(
                    """INSERT INTO kalshi_paper_positions(
                           ticker,side,strategy,status,opened_at,entry_price,
                           contracts,entry_fee,closed_at,exit_price,exit_fee,pnl
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f'KXBTC15M-GATE-{index}', 'YES', 'SCALP', 'CLOSED',
                        now + index, .50, 1, .01, now + index + 1,
                        .45, .01, -0.07,
                    ),
                )
        gate = engine.scalp_profitability_gate(self.db)
        self.assertFalse(gate['approved'])
        self.assertEqual(gate['status'], 'SCALPS PAUSED')
        self.assertIn('profit factor', gate['reason'])
        self.decision['action'] = 'SCALP UP'
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('profitability gate is active', skipped['message'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

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

    def test_scalp_rejects_lottery_style_selected_side(self):
        self.decision.update(
            action='SCALP UP',
            yes_ask_dollars=.001,
            yes_bid_dollars=0.0,
            no_ask_dollars=1.0,
            no_bid_dollars=.999,
            scalp_projected_exit_price=.80,
        )
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('below the 20% lottery floor', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

    def test_scalp_requires_projected_ten_percent_gross_return(self):
        self.decision.update(action='SCALP UP', scalp_projected_exit_price=.54)
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('10% gross-return target', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

        # At a 50% entry, a 55% forecast is exactly a 10% gross return.
        self.decision['scalp_projected_exit_price'] = .55
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(engine.paper_summary(self.db)['open_position']['entry_price'], .50)

    def test_scalp_takes_profit_when_ai_sees_no_more_upside(self):
        self.decision.update(
            action='SCALP UP',
            confidence=.80,
            scalp_projected_exit_price=.55,
        )
        self.open()
        self.decision['yes_bid_dollars'] = .54
        self.assertFalse(self.cycle()['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])
        self.decision['yes_bid_dollars'] = .55
        closed = self.cycle()
        self.assertTrue(closed['event'])
        with engine._connect(self.db) as conn:
            reason = conn.execute(
                'SELECT exit_reason FROM kalshi_paper_positions ORDER BY id DESC LIMIT 1'
            ).fetchone()['exit_reason']
        self.assertEqual(reason, 'TAKE_PROFIT_AI_UPSIDE_EXHAUSTED')
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_scalp_holds_beyond_ten_percent_when_ai_sees_more_upside(self):
        self.decision.update(
            action='SCALP UP',
            confidence=.80,
            scalp_projected_exit_price=.70,
        )
        self.open()
        self.decision['yes_bid_dollars'] = .55
        held = self.cycle()
        self.assertFalse(held['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

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
            self.decision.update(
                yes_ask_dollars=.50,
                yes_bid_dollars=.48,
                scalp_projected_exit_price=.80,
            )
            self.assertTrue(self.cycle()['event'])
            self.decision.update(
                yes_bid_dollars=.65,
                scalp_projected_exit_price=.65,
            )
            self.assertTrue(self.cycle()['event'])
            self.decision['action'] = 'HOLD'
            self.assertFalse(self.cycle()['event'])
            self.decision['action'] = 'SCALP UP'

        self.decision.update(yes_ask_dollars=.50, yes_bid_dollars=.48)
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('10 SCALPs already entered', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])

    def test_normal_spread_does_not_trigger_immediate_stop_or_reentry_loop(self):
        self.decision.update(action='SCALP UP', scalp_projected_exit_price=.80)
        self.assertTrue(self.cycle()['event'])

        # A two-point bid/ask spread is transaction cost, not an adverse
        # contract move. The position must remain open.
        held = self.cycle()
        self.assertFalse(held['event'])
        self.assertIn('Holding', held['message'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

        # A five-point adverse move is now tolerated as ordinary contract noise.
        # signal stays disarmed instead of churning ten identical entries.
        self.decision['yes_bid_dollars'] = .45
        self.assertFalse(self.cycle()['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

        # The wider 15-point emergency boundary closes the position once.
        self.decision['yes_bid_dollars'] = .35
        self.assertTrue(self.cycle()['event'])
        self.decision['yes_bid_dollars'] = .48
        blocked = self.cycle()
        self.assertFalse(blocked['event'])
        self.assertIn('fresh signal', blocked['message'])
        self.assertEqual(engine.paper_summary(self.db)['samples'], 1)

        # HOLD rearms the side; a later return of the signal is a new scalp.
        self.decision['action'] = 'HOLD'
        self.assertFalse(self.cycle()['event'])
        self.decision.update(action='SCALP UP', yes_bid_dollars=.48)
        self.assertTrue(self.cycle()['event'])

    def test_confidence_is_not_used_as_projected_contract_price(self):
        self.decision.update(
            action='SCALP UP',
            confidence=.99,
            scalp_projected_exit_price=None,
        )
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('projected exit unavailable', skipped['message'])

    def test_wide_spread_does_not_block_entry(self):
        self.decision.update(
            action='SCALP UP',
            yes_ask_dollars=.50,
            yes_bid_dollars=.40,
            scalp_projected_exit_price=.60,
        )
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

    def test_opposite_signal_must_persist_before_scalp_exit(self):
        self.decision.update(action='SCALP UP', scalp_projected_exit_price=.80)
        self.assertTrue(self.cycle()['event'])
        self.decision.update(action='SCALP DOWN', no_bid_dollars=.50)
        first = self.cycle()
        self.assertFalse(first['event'])
        self.assertIsNotNone(engine.paper_summary(self.db)['open_position'])

        with engine._connect(self.db) as conn:
            conn.execute(
                'UPDATE kalshi_paper_positions SET opposite_since=? WHERE status="OPEN"',
                (time.time() - engine.OPPOSITE_SIGNAL_CONFIRM_SECONDS - 1,),
            )
        confirmed = self.cycle()
        self.assertTrue(confirmed['event'])
        self.assertIn('Closed PAPER SCALP', confirmed['message'])

    def test_two_losses_stop_further_scalps_in_same_market(self):
        self.decision.update(action='SCALP UP', scalp_projected_exit_price=.80)
        for _ in range(2):
            self.decision.update(yes_ask_dollars=.50, yes_bid_dollars=.48)
            self.assertTrue(self.cycle()['event'])
            self.decision['yes_bid_dollars'] = .35
            self.assertTrue(self.cycle()['event'])
            self.decision['action'] = 'HOLD'
            self.assertFalse(self.cycle()['event'])
            self.decision['action'] = 'SCALP UP'

        self.decision['yes_bid_dollars'] = .48
        blocked = self.cycle()
        self.assertFalse(blocked['event'])
        self.assertIn('circuit breaker', blocked['message'])
        self.assertEqual(engine.paper_summary(self.db)['samples'], 2)

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
        legacy_import = (
            'from kalshi_paper_engine import manage_kalshi_paper_cycle, '
            'paper_summary, persistent_lock_side'
        )
        self.assertEqual(paper_tab.count('k1.metric("Contract Equity"'), 1)
        self.assertEqual(paper_tab.count('Automatic Kalshi Paper Trade Log'), 1)
        self.assertNotIn("['contracts']} contracts", paper_tab)
        self.assertNotIn("['ticker']} • entry", paper_tab)
        self.assertEqual(source.count('paper_performance_since_update,'), 1)
        self.assertEqual(source.count('scalp_profitability_gate,'), 1)
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
        self.assertIn('Since Loss-Loop Fix — Kalshi Execution Scorecard', source)
        self.assertIn('_kp = shared_paper_summary(_shared_paper)', source)
        self.assertIn('_contract_history = shared_paper_history(_shared_paper', source)
        self.assertNotIn('auto_result = manage_auto_paper(', source)
        self.assertIn('persistent GitHub learning-state ledger', source)
        self.assertIn('projected 10% gross return', source)
        self.assertIn('15-point emergency adverse contract move', source)
        self.assertIn('Kalshi Execution Validation', source)
        self.assertIn('Every specialist remains active', source)
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

    def test_scalp_entries_stop_above_seventy_five_percent(self):
        self.decision.update(
            action='SCALP UP',
            yes_ask_dollars=.85,
            scalp_projected_exit_price=1.0,
        )
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('85%', skipped['message'])
        self.assertIn('75% maximum', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

        # Exactly 75% remains eligible; its 10% gross-return target is 82.5%.
        self.decision.update(
            yes_ask_dollars=.75,
            scalp_projected_exit_price=.825,
        )
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(
            engine.paper_summary(self.db)['open_position']['entry_price'],
            .75,
        )

    def test_final_lock_may_enter_above_seventy_five_percent(self):
        self.decision.update(
            action='LOCK UP',
            confidence=.95,
            yes_ask_dollars=.85,
            yes_bid_dollars=.84,
        )
        opened = self.cycle()
        self.assertTrue(opened['event'])
        position = engine.paper_summary(self.db)['open_position']
        self.assertEqual(position['strategy'], 'LOCK')
        self.assertEqual(position['entry_price'], .85)

    def test_lock_rejects_fee_loss_at_ninety_five_percent_exit(self):
        self.decision.update(
            action='LOCK UP',
            confidence=.95,
            yes_ask_dollars=.95,
            yes_bid_dollars=.94,
        )
        skipped = self.cycle()
        self.assertFalse(skipped['event'])
        self.assertIn('after estimated Kalshi fees', skipped['message'])
        self.assertIsNone(engine.paper_summary(self.db)['open_position'])
        self.assertIsNone(
            engine.open_position(self.db, 500, self.decision, self.risk, 100)
        )

    def test_lock_accepts_profitable_fee_aware_price(self):
        self.decision.update(
            action='LOCK UP',
            confidence=.95,
            yes_ask_dollars=.94,
            yes_bid_dollars=.93,
        )
        self.assertGreater(engine.lock_target_pnl(10, .94), 0)
        opened = self.cycle()
        self.assertTrue(opened['event'])
        self.assertEqual(
            engine.paper_summary(self.db)['open_position']['entry_price'],
            .94,
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


    def test_chart_prefers_working_kalshi_public_endpoint(self):
        source = Path("app.py").read_text(encoding="utf-8")
        working = "https://api.elections.kalshi.com/trade-api/v2"
        blocked = "https://external-api.kalshi.com/trade-api/v2"
        self.assertGreaterEqual(source.count(working), 2)
        self.assertLess(source.index(working), source.index(blocked))
        self.assertIn("const KALSHI_PUBLIC_BASES", source)
        self.assertIn("async function fetchKalshiJson(path)", source)
        self.assertIn("Kalshi target unavailable — retrying…", source)
        self.assertIn("currentTarget = NaN;", source)
