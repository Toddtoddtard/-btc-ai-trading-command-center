import unittest

from research_lab import (
    enrich_rationales,
    ensure_research_lab,
    register_shadow,
    resolve_shadows,
    strategy_leaderboard,
    update_policy_bucket,
    update_lifecycles,
    window_phase,
)


class ResearchLabTests(unittest.TestCase):
    def test_window_phase_boundaries(self):
        self.assertEqual(window_phase(0, 900), "OPEN")
        self.assertEqual(window_phase(300, 900), "MIDDLE")
        self.assertEqual(window_phase(600, 900), "FINAL 5")
        self.assertEqual(window_phase(780, 900), "FINAL 2")

    def test_rationales_include_opposition_and_invalidation(self):
        rows = enrich_rationales({
            "Bull": {"score": 0.5, "reason": "Momentum rising"},
            "Bear": {"score": -0.7, "reason": "Heavy asks"},
        })
        self.assertEqual(rows["Bull"]["evidence"], "Momentum rising")
        self.assertEqual(rows["Bull"]["counterargument"], "Heavy asks")
        self.assertIn("Re-evaluate", rows["Bull"]["invalidation"])

    def test_shadow_is_unique_and_graded_from_official_result(self):
        state = {}
        pending = {
            "ticker": "KXBTC15M-TEST", "opened_at": 100, "expires_at": 1000,
            "master_base_score": 0.6, "master_confidence": 0.8,
            "master_action": "WAIT",
        }
        market = {"yes_bid": 0.59, "yes_ask": 0.61, "no_ask": 0.41}
        self.assertTrue(register_shadow(state, pending, market))
        self.assertFalse(register_shadow(state, pending, market))
        later_phase = dict(pending, opened_at=800)
        self.assertTrue(register_shadow(state, later_phase, market))
        self.assertEqual(resolve_shadows(state, lambda ticker: "yes"), 2)
        lab = state["research_lab"]
        self.assertEqual(lab["calibration"]["samples"], 2)
        self.assertEqual(lab["wait_counterfactual"]["missed_wins"], 2)
        self.assertGreater(lab["history"][0]["paper_pnl"], 0)
        self.assertEqual(lab["pending"], [])

    def test_lifecycle_never_controls_execution(self):
        state = {
            "specialists": {
                "Rare": {"samples": 4, "direction_hits": 4, "brier_ewma": 0.1},
                "Weak": {"samples": 200, "direction_hits": 70, "brier_ewma": 0.4},
                "Good": {"samples": 100, "direction_hits": 60, "brier_ewma": 0.2},
            }
        }
        rows = update_lifecycles(state)
        self.assertEqual(rows["Rare"]["status"], "UNCALIBRATED")
        self.assertEqual(rows["Weak"]["status"], "MUTED")
        self.assertEqual(rows["Good"]["status"], "LIVE")
        self.assertTrue(all(row["affects_execution"] is False for row in rows.values()))
        self.assertTrue(ensure_research_lab(state)["paper_only"])

    def test_eight_policies_learn_in_parallel_from_one_settlement(self):
        state = {}
        pending = {
            "ticker": "KXBTC15M-PARALLEL", "opened_at": 100, "expires_at": 1000,
            "master_base_score": 0.8, "master_confidence": 0.9,
            "master_action": "SCALP UP",
        }
        market = {"yes_bid": 0.49, "yes_ask": 0.50, "no_ask": 0.51}
        self.assertTrue(register_shadow(state, pending, market))
        eligible = [x for x in state["research_lab"]["pending"][0]["policies"].values() if x["eligible"]]
        self.assertEqual(len(eligible), 8)
        self.assertEqual(resolve_shadows(state, lambda ticker: "yes"), 1)
        graded = [row for row in state["research_lab"]["policies"].values() if row["samples"] == 1]
        self.assertEqual(len(graded), 8)

    def test_small_sample_strategy_cannot_become_leader(self):
        lab = ensure_research_lab({})
        bucket = lab["policies"]["Current 75 / 5"]
        for _ in range(20):
            update_policy_bucket(bucket, True, 0.40)
        league = strategy_leaderboard(lab)
        self.assertIsNone(league["leader"])
        current = next(row for row in league["ranking"] if row["name"] == "Current 75 / 5")
        self.assertNotEqual(current["status"], "LEADER")

    def test_mature_profitable_strategy_leads_after_fees_and_drawdown(self):
        lab = ensure_research_lab({})
        steady = lab["policies"]["Value 70 / 5"]
        volatile = lab["policies"]["Explore 80 / 5"]
        for i in range(50):
            update_policy_bucket(steady, i % 3 != 0, 0.30 if i % 3 != 0 else -0.20)
            update_policy_bucket(volatile, i % 2 == 0, 0.55 if i % 2 == 0 else -0.50)
        league = strategy_leaderboard(lab)
        self.assertEqual(league["leader"], "Value 70 / 5")
        self.assertFalse(league["affects_execution"])
        self.assertEqual(league["minimum_samples"], 40)


if __name__ == "__main__":
    unittest.main()
