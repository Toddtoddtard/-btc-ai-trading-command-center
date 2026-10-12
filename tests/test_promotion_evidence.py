import copy
import unittest
from unittest.mock import patch

import pandas as pd

from learner_v31 import champion_challenger


class PromotionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.state = {"forecast": {
            "w_ret3": .46, "w_ret8": .34, "w_ret15": .20,
            "momentum_scale": 2.2, "target_influence": .18, "bias": 0.0,
            "samples": 41,
        }}
        self.frame = pd.DataFrame({"close": range(100, 600)})

    def score(self, frame, cfg):
        # Isolate promotion policy from forecast math: retrospective winners
        # meet every numeric threshold, but have no prospective evidence.
        accuracy = .5 if cfg["momentum_scale"] == 2.2 and cfg["w_ret3"] == .46 else .8
        return {"samples": 28, "accuracy": accuracy, "median_error": 10.0}

    def test_repeated_identical_history_cannot_promote(self):
        before = copy.deepcopy(self.state["forecast"])
        with patch("learner_v31.evaluate_cfg", side_effect=self.score):
            for _ in range(3):
                champion_challenger(self.state, self.frame)
        self.assertEqual(self.state["forecast"], before)
        self.assertFalse(self.state["champion_challenger"]["promoted"])
        self.assertEqual(self.state["champion_challenger"]["qualification_streak"], 0)

    def test_different_retrospective_winners_cannot_share_a_streak(self):
        before = copy.deepcopy(self.state["forecast"])
        for winner in (1, 2, 3):
            scores = [{"samples": 28, "accuracy": .5, "median_error": 10.0} for _ in range(4)]
            scores[winner]["accuracy"] = .8
            with patch("learner_v31.evaluate_cfg", side_effect=scores):
                champion_challenger(self.state, self.frame)
        self.assertEqual(self.state["forecast"], before)
        self.assertEqual(self.state["champion_challenger"]["qualification_streak"], 0)

    def test_new_rolling_history_is_still_not_untouched_evidence(self):
        before = copy.deepcopy(self.state["forecast"])
        with patch("learner_v31.evaluate_cfg", side_effect=self.score):
            for length in (480, 490, 500):
                champion_challenger(self.state, self.frame.iloc[:length])
        self.assertEqual(self.state["forecast"], before)
        diagnostics = self.state["champion_challenger"]
        self.assertEqual(diagnostics["evaluation_basis"], "HISTORICAL_REPLAY")
        self.assertTrue(diagnostics["shadow_only"])
        self.assertFalse(diagnostics["predictive_improvement_proven"])
        self.assertEqual(diagnostics["independent_evidence_samples"], 0)
        self.assertTrue(diagnostics["historical_thresholds_met"])
        self.assertEqual(diagnostics["best_challenger"]["samples"], 28)

    def test_legacy_streak_is_reset_without_overwriting_learned_forecast(self):
        self.state["champion_challenger"] = {"qualification_streak": 100, "promoted": True}
        before = copy.deepcopy(self.state["forecast"])
        with patch("learner_v31.evaluate_cfg", side_effect=self.score):
            champion_challenger(self.state, self.frame)
        self.assertEqual(self.state["forecast"], before)
        self.assertEqual(self.state["champion_challenger"]["qualification_streak"], 0)
        self.assertFalse(self.state["champion_challenger"]["promoted"])


if __name__ == "__main__":
    unittest.main()
