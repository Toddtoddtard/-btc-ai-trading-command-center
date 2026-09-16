import unittest

from multi_asset_paper import (
    FEE_RATE,
    MARKETS,
    STARTING_CASH,
    decision_from_specialists,
    ensure_multi_asset_state,
    paper_cycle,
)


APPROVED_UP = {
    "action": "SCALP UP",
    "confidence": 0.78,
    "consensus": 0.70,
}


class MultiAssetPaperTests(unittest.TestCase):
    def test_all_four_markets_are_automatic_and_paper_only(self):
        root = {}
        multi = ensure_multi_asset_state(root)
        self.assertEqual(set(multi["assets"]), set(MARKETS))
        self.assertTrue(multi["paper_only"])
        self.assertFalse(multi["real_money_execution"])
        self.assertTrue(multi["enabled"])
        for asset in multi["assets"].values():
            self.assertTrue(asset["enabled"])
            self.assertEqual(asset["cash"], STARTING_CASH)

    def test_existing_disabled_state_is_migrated_to_automatic(self):
        root = {"multi_asset_paper": {"assets": {"gold": {"enabled": False}}}}
        multi = ensure_multi_asset_state(root)
        self.assertTrue(multi["assets"]["gold"]["enabled"])

    def test_approved_signal_opens_then_target_closes_after_fees(self):
        bucket = ensure_multi_asset_state({})["assets"]["gold"]
        action = paper_cycle(bucket, 100.0, APPROVED_UP, 0.004, now=1_000.0)
        self.assertEqual(action, "OPEN")
        self.assertEqual(bucket["side"], "LONG")
        self.assertAlmostEqual(bucket["qty"], 0.25)
        self.assertAlmostEqual(bucket["cash"], STARTING_CASH - 25.0 * FEE_RATE)

        action = paper_cycle(bucket, 100.60, APPROVED_UP, 0.004, now=1_120.0)
        self.assertEqual(action, "CLOSE")
        self.assertEqual(bucket["side"], "NONE")
        self.assertEqual(bucket["trades"], 1)
        self.assertEqual(bucket["wins"], 1)
        self.assertGreater(bucket["history"][0]["net_pnl"], 0.0)

    def test_stale_market_never_opens(self):
        bucket = ensure_multi_asset_state({})["assets"]["wti"]
        action = paper_cycle(
            bucket,
            70.0,
            APPROVED_UP,
            0.005,
            now=2_000.0,
            feed_fresh=False,
        )
        self.assertEqual(action, "STALE")
        self.assertEqual(bucket["side"], "NONE")

    def test_weak_signal_does_not_open(self):
        bucket = ensure_multi_asset_state({})["assets"]["zec"]
        action = paper_cycle(
            bucket,
            50.0,
            {"action": "SCALP UP", "confidence": 0.65, "consensus": 0.80},
            0.01,
            now=3_000.0,
        )
        self.assertEqual(action, "WAIT")
        self.assertEqual(bucket["side"], "NONE")

    def test_specialist_vote_uses_same_approval_floor(self):
        strong = {
            name: {"score": 0.8, "confidence": 0.86}
            for name in (
                "Trend AI",
                "Momentum AI",
                "Volume AI",
                "Pattern AI",
                "Support/Resistance AI",
                "Volatility AI",
                "Market Regime AI",
                "Historical Pattern AI",
                "Combination AI",
            )
        }
        decision = decision_from_specialists(strong, "gold")
        self.assertEqual(decision["action"], "SCALP UP")
        self.assertGreaterEqual(decision["confidence"], 0.66)
        self.assertGreaterEqual(decision["consensus"], 0.60)


if __name__ == "__main__":
    unittest.main()
