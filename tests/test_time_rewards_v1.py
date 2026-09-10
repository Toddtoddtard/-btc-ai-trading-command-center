import unittest

from specialist_knowledge_v5 import specialist_posterior
from time_rewards_v1 import time_reward


class TimeRewardsV1Tests(unittest.TestCase):
    def test_earlier_correct_call_gets_larger_reward(self):
        early = time_reward(1000, 1900, True)
        late = time_reward(1840, 1900, True)
        self.assertGreater(early["points"], late["points"])
        self.assertAlmostEqual(early["points"], 2.0)
        self.assertGreaterEqual(late["points"], 1.0)

    def test_early_wrong_call_has_symmetric_penalty(self):
        correct = time_reward(1000, 1900, True)
        wrong = time_reward(1000, 1900, False)
        self.assertAlmostEqual(wrong["points"], -correct["points"])

    def test_neutral_call_has_no_reward(self):
        reward = time_reward(1000, 1900, True, directional=False)
        self.assertEqual(reward["points"], 0.0)

    def test_early_correct_evidence_gets_more_posterior_credit(self):
        base = {
            "specialists": {},
            "historical_specialist_knowledge_v7": {},
        }
        early = dict(base)
        early["specialist_history"] = {
            "Trend AI": [
                {
                    "directional_call": True,
                    "direction_correct": 1,
                    "signed_edge": 0.01,
                    "time_reward": 2.0,
                }
            ]
        }
        late = dict(base)
        late["specialist_history"] = {
            "Trend AI": [
                {
                    "directional_call": True,
                    "direction_correct": 1,
                    "signed_edge": 0.01,
                    "time_reward": 1.0,
                }
            ]
        }
        self.assertGreater(
            specialist_posterior(early, "Trend AI")["posterior_accuracy"],
            specialist_posterior(late, "Trend AI")["posterior_accuracy"],
        )


if __name__ == "__main__":
    unittest.main()
