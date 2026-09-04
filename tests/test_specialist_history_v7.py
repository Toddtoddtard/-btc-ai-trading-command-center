import unittest

from specialist_knowledge_v5 import specialist_posterior
from audit_scorecard_v7 import _score


class SpecialistHistoryV7Tests(unittest.TestCase):
    def test_regime_specific_historical_prior_is_used(self):
        state = {
            "historical_specialist_knowledge_v7": {
                "version": 7,
                "walk_forward": True,
                "specialists": {
                    "Trend AI": {
                        "accuracy": 0.55,
                        "directional_calls": 1000,
                        "regimes": {
                            "TREND_UP": {"accuracy": 0.72, "directional_calls": 600},
                            "LOW_VOL_RANGE": {"accuracy": 0.44, "directional_calls": 400},
                        },
                    }
                },
            },
            "specialist_history": {"Trend AI": []},
        }
        up = specialist_posterior(state, "Trend AI", "TREND_UP")
        low = specialist_posterior(state, "Trend AI", "LOW_VOL_RANGE")
        self.assertGreater(up["posterior_accuracy"], low["posterior_accuracy"])
        self.assertEqual(up["historical_samples"], 600)
        self.assertEqual(low["historical_samples"], 400)

    def test_unknown_regime_uses_global_prior(self):
        state = {
            "historical_specialist_knowledge_v7": {
                "version": 7,
                "walk_forward": True,
                "specialists": {
                    "Momentum AI": {"accuracy": 0.61, "directional_calls": 1500, "regimes": {}}
                },
            },
            "specialist_history": {"Momentum AI": []},
        }
        p = specialist_posterior(state, "Momentum AI", "UNKNOWN")
        self.assertEqual(p["historical_samples"], 1500)
        self.assertAlmostEqual(p["historical_accuracy"], 0.61)

    def test_scorecard_metrics(self):
        rows = [
            {"direction_correct": 1, "kalshi_correct": 1, "abs_error": 10, "path_error": 8, "master_confidence": 0.7},
            {"direction_correct": 0, "kalshi_correct": 1, "abs_error": 20, "path_error": 12, "master_confidence": 0.6},
        ]
        s = _score(rows)
        self.assertEqual(s["samples"], 2)
        self.assertEqual(s["direction_accuracy"], 0.5)
        self.assertEqual(s["kalshi_accuracy"], 1.0)
        self.assertEqual(s["avg_abs_error"], 15.0)


if __name__ == "__main__":
    unittest.main()
