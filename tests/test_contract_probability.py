import unittest

from contract_probability import realized_minute_volatility, terminal_above_probability


class ContractProbabilityTests(unittest.TestCase):
    def test_strike_distance_and_time_change_terminal_probability(self):
        closes = [100000 + value for value in (0, 20, -10, 25, 5, 30, 10, 35)]
        volatility = realized_minute_volatility(closes)
        above = terminal_above_probability(100100, 100000, 900, volatility)
        below = terminal_above_probability(99900, 100000, 900, volatility)
        near_close = terminal_above_probability(100100, 100000, 30, volatility)
        self.assertGreater(above["probability_up"], 0.5)
        self.assertLess(below["probability_up"], 0.5)
        self.assertGreater(near_close["probability_up"], above["probability_up"])

    def test_market_anchor_bounds_model_disagreement(self):
        result = terminal_above_probability(
            100100, 100000, 600, 0.0005,
            market_probability=0.40, model_score=1.0, source_health=1.0,
        )
        self.assertGreater(result["probability_up"], 0.40)
        self.assertLess(result["probability_up"], result["independent_probability_up"])
        self.assertLess(abs(result["edge_vs_market"]), 0.35)

    def test_final_window_stress_is_telemetry_not_a_probability_failure(self):
        result = terminal_above_probability(
            100000, 100000, 20, 0.0005, market_probability=0.5,
            orderbook={
                "spread": 0.10,
                "weighted_depth_imbalance": 0.95,
                "depth_concentration": 0.96,
            },
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["late_window_stress"])


if __name__ == "__main__":
    unittest.main()
