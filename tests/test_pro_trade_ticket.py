import unittest
import time

from pro_trade_ticket import build_pro_trade_ticket
from contract_calibration import BASIS


def _decision(action="SCALP UP", **updates):
    decision = {
        "action": action,
        "kalshi_close_ts": time.time()+600,
        "yes_bid_dollars": 0.49,
        "yes_ask_dollars": 0.50,
        "no_bid_dollars": 0.50,
        "no_ask_dollars": 0.51,
        "scalp_projected_exit_price": 0.65,
    }
    decision.update(updates)
    return decision


class ProTradeTicketTests(unittest.TestCase):
    def test_scalp_ticket_discloses_complete_fee_aware_economics(self):
        ticket = build_pro_trade_ticket(
            _decision(),
            {"approved": True, "position_pct": 0.08},
            {"cash": 500.0},
        )

        self.assertEqual(ticket["status"], "READY")
        self.assertEqual(ticket["direction"], "UP")
        self.assertAlmostEqual(ticket["allocation_pct"], 0.02)
        self.assertEqual(ticket["contracts"], 19)
        self.assertAlmostEqual(ticket["entry_fee"], 0.34)
        self.assertAlmostEqual(ticket["total_cost"], 9.84)
        self.assertAlmostEqual(ticket["break_even_price"], 0.54)
        self.assertAlmostEqual(ticket["take_profit_price"], 0.525)
        self.assertAlmostEqual(ticket["emergency_stop_price"], 0.35)
        self.assertGreater(ticket["projected_net_pnl"], 0)

    def test_down_ticket_uses_no_side_quote(self):
        ticket = build_pro_trade_ticket(
            _decision("SCALP DOWN"),
            {"approved": True, "position_pct": 0.02},
            {"cash": 500.0},
        )

        self.assertEqual(ticket["side"], "NO")
        self.assertAlmostEqual(ticket["entry_price"], 0.51)
        self.assertAlmostEqual(ticket["current_bid"], 0.50)

    def test_hold_ticket_never_pretends_an_order_is_ready(self):
        ticket = build_pro_trade_ticket(
            _decision("HOLD"),
            {"approved": False, "position_pct": 0.0},
            {"cash": 500.0},
        )

        self.assertEqual(ticket["status"], "WAIT")
        self.assertEqual(ticket["contracts"], 0)
        self.assertIsNone(ticket["entry_price"])
        self.assertIn("waiting for a qualified call", ticket["blockers"][0])

    def test_lock_preview_is_settlement_based_and_not_risk_gate_labeled(self):
        ticket = build_pro_trade_ticket(
            _decision("LOCK UP", yes_ask_dollars=0.72, confidence=.95,
                      contract_probability_up=.85, contract_probability_basis=BASIS,
                      contract_calibrator_active=True),
            {"approved": False, "position_pct": 0.02},
            {"cash": 500.0},
        )

        self.assertEqual(ticket["status"], "READY")
        self.assertEqual(ticket["projected_exit_price"], 1.0)
        self.assertGreater(ticket['expected_settlement_net_pnl'], 0)
        self.assertLess(ticket['expected_settlement_net_pnl'], ticket['projected_net_pnl'])
        self.assertIsNone(ticket["take_profit_price"])
        self.assertIn("official Kalshi settlement", ticket["protection"])

    def test_open_position_blocks_an_additional_ticket(self):
        ticket = build_pro_trade_ticket(
            _decision(),
            {"approved": True, "position_pct": 0.02},
            {"cash": 500.0},
            has_open_position=True,
        )

        self.assertEqual(ticket["status"], "WAIT")
        self.assertIn("one paper position is already open", ticket["blockers"])

    def test_lock_preview_requires_positive_validated_expected_return(self):
        for updates in ({}, {'contract_probability_up': .51},
                        {'contract_probability_up': .8, 'contract_calibrator_active': False},
                        {'contract_probability_up': .8, 'execution_approved': False}):
            with self.subTest(updates=updates):
                fields = dict(confidence=.95, contract_probability_basis=BASIS,
                              contract_calibrator_active=True)
                fields.update(updates)
                ticket = build_pro_trade_ticket(
                    _decision('LOCK UP', **fields),
                    {'approved': True, 'position_pct': .02}, {'cash': 500})
                self.assertEqual(ticket['status'], 'WAIT')

    def test_invalid_book_cannot_show_ready(self):
        for updates in ({'yes_bid_dollars': .6}, {'yes_ask_dollars': -.1},
                        {'yes_ask_dollars': None},
                        {'yes_bid_dollars': -.1}):
            with self.subTest(updates=updates):
                ticket = build_pro_trade_ticket(_decision(**updates),
                    {'approved': True, 'position_pct': .02}, {'cash': 500})
                self.assertEqual(ticket['status'], 'WAIT')

    def test_missing_or_expired_window_cannot_show_ready(self):
        for expiry in (None, time.time()-1):
            ticket = build_pro_trade_ticket(_decision(kalshi_close_ts=expiry),
                {'approved': True, 'position_pct': .02}, {'cash': 500})
            self.assertEqual(ticket['status'], 'WAIT')

    def test_scalp_requires_gross_target_and_positive_after_fee_profit(self):
        for projected in (None, .51, .525):
            ticket = build_pro_trade_ticket(_decision(scalp_projected_exit_price=projected),
                {'approved': True, 'position_pct': .02}, {'cash': 500})
            self.assertEqual(ticket['status'], 'WAIT')


if __name__ == "__main__":
    unittest.main()
