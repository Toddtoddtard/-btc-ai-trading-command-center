import unittest

import pandas as pd

from forward_outlook import build_next_market_outlooks
from learner_v31 import grade_forward_outlooks


class ForwardOutlookTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [
            {"open": 100 + i, "high": 102 + i, "low": 99 + i, "close": 101 + i}
            for i in range(60)
        ]

    def test_builds_exactly_three_non_executable_future_windows(self):
        rows = build_next_market_outlooks(
            self.rows(), {}, 1800, .72, .70, {}
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["horizon"] for row in rows], [1, 2, 3])
        self.assertEqual([row["expires_at"] for row in rows], [2700, 3600, 4500])
        self.assertTrue(all(row["research_only"] for row in rows))
        self.assertTrue(all(not row["executable"] for row in rows))

    def test_future_outlook_is_graded_against_actual_window_not_projection(self):
        times = pd.date_range("2026-01-01T00:00:00Z", periods=31, freq="1min")
        df = pd.DataFrame({
            "time": times,
            "close": [100.0 + i for i in range(31)],
        })
        start = times[14].timestamp() + 60
        end = times[29].timestamp() + 60
        state = {
            "forward_outlook_history": [{
                "horizon": 1, "window_start": start, "expires_at": end,
                "direction": "UP", "confidence": .70, "resolved": False,
            }],
            "forward_outlook_stats": {},
        }
        graded = grade_forward_outlooks(state, df, now=end + 1)
        self.assertEqual(graded, 1)
        self.assertEqual(state["forward_outlook_history"][0]["correct"], 1)
        self.assertEqual(state["forward_outlook_stats"]["1"]["accuracy"], 1.0)
        self.assertAlmostEqual(state["forward_outlook_stats"]["1"]["brier"], .09)


if __name__ == "__main__":
    unittest.main()
