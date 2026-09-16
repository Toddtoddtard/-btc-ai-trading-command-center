import unittest

from pro_trade_ticket import build_pro_trade_ticket


def _decision(action="SCALP UP", **updates):
    decision = {
        "action": action,
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
            _decision("LOCK UP", yes_ask_dollars=0.72),
            {"approved": False, "position_pct": 0.02},
            {"cash": 500.0},
        )

        self.assertEqual(ticket["status"], "READY")
        self.assertEqual(ticket["projected_exit_price"], 1.0)
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


if __name__ == "__main__":
    unittest.main()
