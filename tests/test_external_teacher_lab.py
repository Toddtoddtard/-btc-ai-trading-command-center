import unittest

from external_teacher_lab import (
    TEACHERS,
    build_teacher_calls,
    ensure_teacher_lab,
    grade_teacher_calls,
    teacher_leaderboard,
)
from research_lab import register_shadow, resolve_shadows


def bullish_specialists():
    names = {
        "Trend AI",
        "Momentum AI",
        "Volume AI",
        "Pattern AI",
        "Support/Resistance AI",
        "Volatility AI",
        "Market Regime AI",
        "Whale AI",
        "Liquidity AI",
        "Derivatives AI",
        "Historical Pattern AI",
        "FVG / MACD AI",
        "Combination AI",
    }
    return {
        name: {"score": 0.80, "confidence": 0.86, "reason": "Verified bullish evidence"}
        for name in names
    }


class ExternalTeacherLabTests(unittest.TestCase):
    def test_five_public_method_teachers_are_shadow_only(self):
        lab = {}
        teacher_lab = ensure_teacher_lab(lab)
        self.assertEqual(len(TEACHERS), 5)
        self.assertEqual(set(teacher_lab["teachers"]), {row["name"] for row in TEACHERS})
        self.assertTrue(teacher_lab["paper_only"])
        self.assertFalse(teacher_lab["affects_execution"])
        self.assertEqual(teacher_lab["minimum_samples"], 100)

    def test_strong_shared_evidence_creates_fee_aware_teacher_calls(self):
        lab = {}
        calls = build_teacher_calls(
            lab,
            {"specialists": bullish_specialists()},
            {"yes_bid": 0.49, "yes_ask": 0.50, "no_ask": 0.51},
        )
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(call["eligible"] for call in calls.values()))
        self.assertTrue(all(call["direction"] == "YES" for call in calls.values()))
        self.assertTrue(all(call["selected_ask"] <= 0.75 for call in calls.values()))

    def test_missing_microstructure_source_forces_wait(self):
        specialists = bullish_specialists()
        specialists["Whale AI"]["reason"] = "Aggregate trade feed unavailable"
        calls = build_teacher_calls(
            {},
            {"specialists": specialists},
            {"yes_bid": 0.49, "yes_ask": 0.50, "no_ask": 0.51},
        )
        micro = calls["Hummingbot-inspired Microstructure Challenger"]
        self.assertFalse(micro["eligible"])
        self.assertEqual(micro["action"], "WAIT")

    def test_official_settlement_grades_each_teacher_independently(self):
        state = {}
        pending = {
            "ticker": "KXBTC15M-TEACHERS",
            "opened_at": 100,
            "expires_at": 1000,
            "master_base_score": 0.8,
            "master_confidence": 0.9,
            "master_action": "SCALP UP",
            "specialists": bullish_specialists(),
        }
        market = {"yes_bid": 0.49, "yes_ask": 0.50, "no_ask": 0.51}
        self.assertTrue(register_shadow(state, pending, market))
        self.assertEqual(resolve_shadows(state, lambda ticker: "yes"), 1)
        teacher_lab = state["research_lab"]["external_teacher_lab"]
        self.assertTrue(all(row["samples"] == 1 for row in teacher_lab["teachers"].values()))
        self.assertTrue(all(row["wins"] == 1 for row in teacher_lab["teachers"].values()))
        self.assertTrue(all(row["net_pnl"] > 0 for row in teacher_lab["teachers"].values()))
        self.assertIsNone(teacher_lab["leader"])

    def test_qualification_streak_only_advances_on_new_evidence(self):
        lab = {}
        teacher_lab = ensure_teacher_lab(lab)
        name = TEACHERS[0]["name"]
        call = {
            "eligible": True,
            "direction": "YES",
            "selected_ask": 0.50,
            "model_yes_probability": 0.80,
        }
        observation = {"external_teachers": {name: call.copy()}}
        for _ in range(100):
            grade_teacher_calls(lab, observation, "yes")
        first = teacher_leaderboard(lab)
        self.assertEqual(first["qualification_streaks"][name], 1)
        unchanged = teacher_leaderboard(lab)
        self.assertEqual(unchanged["qualification_streaks"][name], 1)
        self.assertIsNone(unchanged["leader"])

        grade_teacher_calls(lab, observation, "yes")
        second = teacher_leaderboard(lab)
        self.assertEqual(second["qualification_streaks"][name], 2)
        grade_teacher_calls(lab, observation, "yes")
        final = teacher_leaderboard(lab)
        self.assertEqual(final["leader"], name)
        self.assertFalse(final["affects_execution"])
        self.assertEqual(final["teachers"][name]["samples"], 102)


if __name__ == "__main__":
    unittest.main()
