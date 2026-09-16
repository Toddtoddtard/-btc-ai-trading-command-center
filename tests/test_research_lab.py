import unittest

from research_lab import (
    enrich_rationales,
    ensure_research_lab,
    fit_guarded_calibrator,
    guarded_probability,
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

    def test_guarded_probability_falls_back_to_market_before_validation(self):
        calibration = fit_guarded_calibrator([])
        self.assertFalse(calibration["active"])
        self.assertAlmostEqual(guarded_probability(0.99, 0.62, calibration), 0.62)

    def test_calibrator_activates_only_after_causal_walk_forward_edge(self):
        history = []
        for i in range(180):
            outcome = 1.0 if i % 2 == 0 else 0.0
            history.append({
                "ticker": f"T-{i}",
                "result": "yes" if outcome else "no",
                "market_yes_probability": 0.55 if outcome else 0.45,
                "model_yes_probability": 0.85 if outcome else 0.15,
            })
        calibration = fit_guarded_calibrator(history)
        self.assertTrue(calibration["active"])
        self.assertGreaterEqual(calibration["validation_samples"], 100)
        self.assertGreater(calibration["validation_edge"], 0.0)
        self.assertFalse(calibration["affects_execution"])

    def test_guarded_score_has_separate_post_deployment_evidence(self):
        state = {}
        pending = {
            "ticker": "KXBTC15M-GUARDED", "opened_at": 100, "expires_at": 1000,
            "master_base_score": 1.0, "master_confidence": 0.9,
            "master_action": "WAIT",
        }
        market = {"yes_bid": 0.59, "yes_ask": 0.61, "no_ask": 0.41}
        self.assertTrue(register_shadow(state, pending, market))
        row = state["research_lab"]["pending"][0]
        self.assertAlmostEqual(row["model_yes_probability"], 0.99)
        self.assertAlmostEqual(row["guarded_yes_probability"], 0.60)
        self.assertEqual(resolve_shadows(state, lambda ticker: "no"), 1)
        calibration = state["research_lab"]["calibration"]
        self.assertEqual(calibration["guarded"]["samples"], 1)
        self.assertLess(calibration["guarded"]["model_brier"], calibration["model_brier"])

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

    def test_policy_needs_strict_promotion_evidence_and_three_evaluations(self):
        lab = ensure_research_lab({})
        steady = lab["policies"]["Value 70 / 5"]
        active = lab["policies"]["Current 75 / 5"]
        for i in range(100):
            candidate_pnl = 0.30 if i % 4 else -0.20
            active_pnl = 0.20 if i % 3 else -0.30
            update_policy_bucket(steady, candidate_pnl > 0, candidate_pnl)
            update_policy_bucket(active, active_pnl > 0, active_pnl)
            lab["history"].append({
                "result": "yes", "paper_pnl": candidate_pnl,
                "policies": {
                    "Value 70 / 5": {"eligible": True},
                    "Current 75 / 5": {"eligible": active_pnl == candidate_pnl},
                },
            })
        first = strategy_leaderboard(lab)
        self.assertIsNone(first["leader"])
        self.assertEqual(first["qualification_streaks"]["Value 70 / 5"], 1)
        self.assertIsNone(strategy_leaderboard(lab)["leader"])
        league = strategy_leaderboard(lab)
        self.assertEqual(league["leader"], "Value 70 / 5")
        self.assertFalse(league["affects_execution"])
        self.assertEqual(league["minimum_samples"], 100)
        self.assertEqual(league["required_streak"], 3)

    def test_policy_cannot_lead_without_paired_superiority(self):
        lab = ensure_research_lab({})
        candidate = lab["policies"]["Value 70 / 5"]
        active = lab["policies"]["Current 75 / 5"]
        for _ in range(100):
            update_policy_bucket(candidate, True, 0.20)
            update_policy_bucket(active, True, 0.20)
            lab["history"].append({
                "result": "yes", "paper_pnl": 0.20,
                "policies": {
                    "Value 70 / 5": {"eligible": True},
                    "Current 75 / 5": {"eligible": True},
                },
            })
        for _ in range(3):
            league = strategy_leaderboard(lab)
        self.assertIsNone(league["leader"])
        row = next(row for row in league["ranking"] if row["name"] == "Value 70 / 5")
        self.assertEqual(row["paired_pnl_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
