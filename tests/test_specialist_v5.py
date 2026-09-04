import unittest

from specialist_knowledge_v5 import specialist_posterior, knowledge_council_vote
from profitability_v5 import summarize_trades, profitability_gate


class SpecialistV5Tests(unittest.TestCase):
    def test_posterior_uses_real_history(self):
        state = {
            "specialist_history": {
                "Trend AI": [
                    {"direction_correct": 1, "signed_edge": 0.01, "regime": "TREND_UP"}
                    for _ in range(30)
                ] + [
                    {"direction_correct": 0, "signed_edge": -0.005, "regime": "TREND_UP"}
                    for _ in range(10)
                ]
            }
        }
        p = specialist_posterior(state, "Trend AI", "TREND_UP")
        self.assertGreater(p["posterior_accuracy"], 0.5)
        self.assertEqual(p["live_samples"], 40)
        self.assertTrue(p["mature"])

    def test_precision_gate_abstains_when_immature(self):
        results = {
            "Trend AI": {"score": 0.9, "confidence": 0.95},
            "Momentum AI": {"score": 0.8, "confidence": 0.90},
            "Volume AI": {"score": 0.7, "confidence": 0.88},
        }
        vote = knowledge_council_vote(results, {}, "TREND_UP", target_precision=0.90)
        self.assertEqual(vote["action"], "WAIT")
        self.assertFalse(vote["precision_gate_passed"])

    def test_profitability_metrics_apply_costs(self):
        rows = [
            {"resolved": 1, "action": "SCALP UP", "return_pct": 1.0, "confidence": 0.8},
            {"resolved": 1, "action": "SCALP DOWN", "return_pct": -0.8, "confidence": 0.8},
            {"resolved": 1, "action": "SCALP UP", "return_pct": -0.2, "confidence": 0.7},
        ]
        m = summarize_trades(rows, cost_bps=5.0)
        self.assertEqual(m["samples"], 3)
        self.assertGreater(m["wins"], m["losses"])
        self.assertIsNotNone(m["expectancy"])

    def test_profitability_gate_requires_evidence(self):
        ok, reason = profitability_gate({"samples": 5, "win_rate": 1.0, "expectancy": 0.1, "profit_factor": 9})
        self.assertFalse(ok)
        self.assertIn("LEARNING", reason)


if __name__ == "__main__":
    unittest.main()
