"""Cash examples checked against Kalshi's published fee-rounding mechanics."""
from decimal import Decimal
import tempfile
import unittest

import background_paper as bg
import kalshi_paper_engine as engine


class KalshiFeeRoundingTests(unittest.TestCase):
    def test_subcent_buy_aligns_total_debit_not_standalone_fee(self):
        self.assertAlmostEqual(engine.kalshi_taker_fee(1, .055), .005)

    def test_background_sale_uses_signed_revenue_and_preserves_entry_cost(self):
        paper = bg.initial_state(now=1000)
        paper.update(starting_cash=500., cash=500., legacy_realized_pnl=0.)
        position = dict(ticker='KXBTC15M-TEST', side='YES', strategy='SCALP',
                        opened_at=1000, contracts=1, entry_price=.50,
                        entry_fee=.02, amount=.52, last_mark=.50, status='OPEN')
        paper['cash'] -= .52
        paper['open_position'] = position
        bg._close(paper, position, .955, 'TEST_SALE', 1010)
        trade = paper['trades'][-1]
        self.assertAlmostEqual(trade['entry_fee'], .02)
        self.assertAlmostEqual(trade['exit_fee'], .005)
        self.assertAlmostEqual(trade['pnl'], .43)
        self.assertEqual(trade['exit_fee_model'], engine.PAPER_FEE_MODEL)
        self.assertAlmostEqual(paper['cash'], 500.43)
        self.assertTrue(bg.reconcile_shared_paper_ledger(paper)['ok'])

    def test_sell_estimates_and_projection_use_sale_cash_alignment(self):
        self.assertAlmostEqual(engine.kalshi_taker_fee(1, .953, action='sell'), .013)
        self.assertAlmostEqual(engine.projected_net_pnl(1, .50, .953), .42)

    def test_cent_price_single_fill_compatibility_and_zero_payout_endpoints(self):
        for count, price, fee in [(1,.5,.02), (100,.5,1.75), (19,.5,.34),
                                  (1,.75,.02), (0,.5,0), (1,0,0), (1,1,0)]:
            with self.subTest(count=count, price=price):
                self.assertAlmostEqual(engine.kalshi_taker_fee(count, price), fee)

    def test_official_example_and_explicit_direct_member_precision(self):
        fill = engine.kalshi_fill_fees(1, '.055')
        self.assertEqual(fill['trade_fee'], Decimal('.003639'))
        self.assertEqual(fill['rounding_fee'], Decimal('.001361'))
        self.assertEqual(fill['cash_change'], Decimal('-.06'))
        self.assertEqual(fill['net_fee'], Decimal('.005'))
        direct = engine.kalshi_fill_fees(1, '.055', balance_precision='.0001')
        self.assertEqual(direct['cash_change'], Decimal('-.0587'))
        self.assertEqual(direct['net_fee'], Decimal('.0037'))

    def test_order_accumulator_rebates_rounding_across_fills(self):
        accumulator = Decimal(0)
        fees = []
        for _ in range(4):
            fill = engine.kalshi_fill_fees(1, '.4', rounding_accumulator=accumulator)
            accumulator = fill['rounding_accumulator']
            fees.append(fill['net_fee'])
        self.assertEqual(fees, [Decimal('.02')]*3+[Decimal('.01')])
        self.assertEqual(accumulator, Decimal('.0028'))
        self.assertEqual(sum(fees), Decimal('.07'))
        # A new order never inherits an unrelated order's rebate.
        self.assertEqual(engine.kalshi_fill_fees(1, '.4')['rebate'], 0)

    def test_equivalent_precision_strings_have_identical_cash_grids(self):
        for precision, debit in [('.0100', '-.06'), ('.0001000', '-.0587')]:
            with self.subTest(precision=precision):
                fill = engine.kalshi_fill_fees(1, '.055', balance_precision=precision)
                self.assertEqual(fill['cash_change'], Decimal(debit))

    def test_sqlite_sale_preserves_legacy_entry_fee_and_closes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            conn = engine._connect(directory+'/paper.db')
            self.addCleanup(conn.close)
            conn.execute('''INSERT INTO kalshi_paper_positions
                (ticker,side,strategy,status,opened_at,entry_price,contracts,entry_fee)
                VALUES ('KXBTC15M-TEST','YES','SCALP','OPEN',1000,.5,1,.012)''')
            conn.execute('UPDATE kalshi_paper_account SET cash=499.488')
            conn.commit()
            row = conn.execute('SELECT * FROM kalshi_paper_positions').fetchone()
            engine._close(conn, row, .955, 'TEST_SALE')
            closed = conn.execute('SELECT * FROM kalshi_paper_positions').fetchone()
            self.assertAlmostEqual(closed['entry_fee'], .012)
            self.assertIsNone(closed['entry_fee_model'])
            self.assertAlmostEqual(closed['exit_fee'], .005)
            self.assertAlmostEqual(closed['pnl'], .438)
            self.assertEqual(closed['exit_fee_model'], engine.PAPER_FEE_MODEL)
            self.assertFalse(engine._close(conn, row, .955, 'TEST_SALE')['event'])
            cash = conn.execute('SELECT cash FROM kalshi_paper_account').fetchone()[0]
            self.assertAlmostEqual(cash, 500.438)

    def test_maker_fill_carries_accumulator_without_negative_fee(self):
        fill = engine.kalshi_fill_fees(1, '.055', fee_rate=0,
                                      rounding_accumulator='.0064')
        self.assertEqual(fill['net_fee'], Decimal('.005'))
        self.assertEqual(fill['rebate'], 0)
        self.assertEqual(fill['rounding_accumulator'], Decimal('.0114'))
        next_fill = engine.kalshi_fill_fees(1, '.4',
                            rounding_accumulator=fill['rounding_accumulator'])
        self.assertEqual(next_fill['rebate'], Decimal('.01'))
        self.assertEqual(next_fill['net_fee'], Decimal('.01'))

    def test_invalid_fill_inputs_are_rejected(self):
        for args, kwargs in [((-1,.5), {}), ((1,'NaN'), {}), ((1,1.1), {}),
                             ((1,.5), {'action':'hold'}),
                             ((1,.5), {'balance_precision':'.001'}),
                             ((1,.5), {'rounding_accumulator':-1}),
                             ((1,.5), {'fee_rate':float('inf')})]:
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    engine.kalshi_fill_fees(*args, **kwargs)


if __name__ == '__main__':
    unittest.main()
