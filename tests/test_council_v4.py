import unittest

from council_v4 import analyze_bot_contributions, council_vote


class CouncilV4Tests(unittest.TestCase):
    def test_combination_ai_is_not_double_counted(self):
        results = {
            "Trend AI": {"score": 0.8, "confidence": 0.8},
            "Momentum AI": {"score": 0.6, "confidence": 0.8},
            "Combination AI": {"score": -1.0, "confidence": 0.99},
        }
        vote = council_vote(results, {}, "TREND_UP")
        self.assertGreater(vote["base_score"], 0)

    def test_learned_weight_changes_council_strength(self):
        results = {
            "Trend AI": {"score": 0.8, "confidence": 0.8},
            "Momentum AI": {"score": -0.8, "confidence": 0.8},
        }
        neutral = council_vote(results, {}, "RANGE")
        state = {
            "specialists": {
                "Trend AI": {"adaptive_weight": 1.7, "regimes": {}},
                "Momentum AI": {"adaptive_weight": 0.4, "regimes": {}},
            }
        }
        learned = council_vote(results, state, "RANGE")
        self.assertGreater(learned["base_score"], neutral["base_score"])

    def test_contribution_analysis_detects_unique_value(self):
        state = {
            "prediction_snapshots": [],
            "master_history": [],
            "specialists": {},
        }
        for i in range(20):
            ticker = f"T{i}"
            actual_up = i % 2 == 0
            good = 0.9 if actual_up else -0.9
            weak_wrong = -0.15 if actual_up else 0.15
            state["prediction_snapshots"].append({
                "ticker": ticker,
                "snapshot": {
                    "regime": "RANGE",
                    "specialists": {
                        "Trend AI": {"score": good, "confidence": 0.9},
                        "Momentum AI": {"score": weak_wrong, "confidence": 0.6},
                    },
                },
            })
            state["master_history"].append({
                "ticker": ticker,
                "direction_correct": 1,
                "realized_return": 0.002 if actual_up else -0.002,
            })
        report = analyze_bot_contributions(state, min_samples=5)
        rows = {row["name"]: row for row in report["ranking"]}
        self.assertIn("Trend AI", rows)
        self.assertGreater(rows["Trend AI"]["standalone_accuracy"], 0.9)


if __name__ == "__main__":
    unittest.main()
