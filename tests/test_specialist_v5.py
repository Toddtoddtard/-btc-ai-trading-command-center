import unittest

from specialist_knowledge_v5 import specialist_posterior, knowledge_council_vote, precision_gate
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

    def test_precision_gate_does_not_deadlock_bootstrap(self):
        vote = {
            "action": "SCALP UP",
            "consensus": 0.70,
            "confidence": 0.72,
            "source_health": 0.95,
        }
        ok, reason = precision_gate(vote, {}, target_precision=0.90)
        self.assertTrue(ok)
        self.assertIn("PASS", reason)

    def test_precision_gate_blocks_clearly_weak_learned_evidence(self):
        knowledge = {
            f"bot{i}": {
                "mature": True,
                "posterior_accuracy": 0.42,
                "lower95_accuracy": 0.30,
            }
            for i in range(5)
        }
        vote = {
            "action": "SCALP DOWN",
            "consensus": 0.70,
            "confidence": 0.72,
            "source_health": 0.95,
        }
        ok, reason = precision_gate(vote, knowledge)
        self.assertFalse(ok)
        self.assertIn("weak", reason.lower())

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
