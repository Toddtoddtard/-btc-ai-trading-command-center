import unittest

from lock_focus import (
    AUTO_SCALPING_ENABLED,
    LOCK_EARLIEST_SECONDS,
    evaluate_lock_focus,
)
from learner_v31 import refresh_pending_lock_focus


class LockFocusTests(unittest.TestCase):
    @staticmethod
    def evaluate(**updates):
        values = {
            "base_score": 0.40,
            "confidence": 0.95,
            "consensus": 0.75,
            "source_health": 1.0,
            "seconds_remaining": 600,
            "market": {
                "yes_bid": 0.61,
                "yes_ask": 0.63,
                "no_bid": 0.37,
                "no_ask": 0.39,
            },
            "target_confirmed": True,
            "edge_floor": 0.16,
        }
        values.update(updates)
        return evaluate_lock_focus(**values)

    def test_automatic_scalping_is_disabled(self):
        self.assertFalse(AUTO_SCALPING_ENABLED)

    def test_qualified_lock_can_fire_at_market_open(self):
        row = self.evaluate(seconds_remaining=LOCK_EARLIEST_SECONDS)
        self.assertEqual(row["action"], "LOCK UP")
        self.assertTrue(row["eligible"])

    def test_lock_evaluation_is_not_blocked_before_ten_minutes(self):
        row = self.evaluate(seconds_remaining=LOCK_EARLIEST_SECONDS + 1)
        self.assertEqual(row["action"], "LOCK UP")
        self.assertTrue(row["checks"]["window"])

    def test_lock_stops_in_final_thirty_seconds(self):
        row = self.evaluate(seconds_remaining=30)
        self.assertEqual(row["action"], "WAIT")
        self.assertFalse(row["checks"]["window"])

    def test_lock_requires_top_tail_confidence(self):
        row = self.evaluate(confidence=0.949)
        self.assertEqual(row["action"], "WAIT")
        self.assertFalse(row["checks"]["confidence"])

    def test_lock_rejects_entry_above_seventy_five(self):
        market = {"yes_bid": 0.75, "yes_ask": 0.76, "no_bid": 0.24, "no_ask": 0.25}
        row = self.evaluate(market=market)
        self.assertEqual(row["action"], "WAIT")
        self.assertFalse(row["checks"]["entry_price"])

    def test_lock_requires_market_and_council_alignment(self):
        row = self.evaluate(consensus=0.30)
        self.assertEqual(row["action"], "WAIT")
        self.assertFalse(row["checks"]["consensus"])

    def test_down_lock_uses_no_contract(self):
        market = {"yes_bid": 0.37, "yes_ask": 0.39, "no_bid": 0.61, "no_ask": 0.63}
        row = self.evaluate(base_score=-0.40, market=market)
        self.assertEqual(row["action"], "LOCK DOWN")
        self.assertEqual(row["side"], "NO")

    def test_pending_wait_can_upgrade_once_and_lock_cannot_reverse(self):
        state = {"pending": {"ticker": "T", "master_action": "WAIT"}}
        market = {"ticker": "T"}
        up = {
            "specialists": {}, "master_confidence": 0.70,
            "master_base_score": 0.4, "master_action": "LOCK UP",
            "would_wait": False, "lock_focus": {"seconds_remaining": 598},
        }
        self.assertTrue(refresh_pending_lock_focus(state, up, market))
        self.assertEqual(state["pending"]["master_action"], "LOCK UP")
        self.assertEqual(state["pending"]["lock_called_seconds_remaining"], 598)
        down = dict(up, master_action="LOCK DOWN", master_base_score=-0.4)
        self.assertFalse(refresh_pending_lock_focus(state, down, market))
        self.assertEqual(state["pending"]["master_action"], "LOCK UP")


if __name__ == "__main__":
    unittest.main()
