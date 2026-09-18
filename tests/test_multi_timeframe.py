import unittest

from multi_timeframe import TIMEFRAME_SPECS, fetch_multi_timeframe_context, summarize_context


class MultiTimeframeTests(unittest.TestCase):
    def test_uses_latest_completed_candle_not_open_candle(self):
        now_ms = 10_000
        calls = []

        def fake_get(_url, params):
            calls.append(params["interval"])
            return [
                [0, "100", "0", "0", "110", "0", 9_000],
                [9_001, "100", "0", "0", "50", "0", 11_000],
            ]

        context = fetch_multi_timeframe_context(fake_get, "https://example.test", now_ms)
        self.assertEqual(set(calls), {row[1] for row in TIMEFRAME_SPECS})
        self.assertEqual(context["available_timeframes"], 7)
        self.assertTrue(context["all_closed"])
        self.assertTrue(all(row["raw_return"] > 0 for row in context["details"].values()))

    def test_summary_reports_alignment(self):
        context = {
            "available_timeframes": 7,
            "features": {name: .5 for name, _interval, _scale in TIMEFRAME_SPECS},
        }
        summary = summarize_context(context)
        self.assertEqual(summary["direction"], "UP")
        self.assertEqual(summary["agreement"], 1.0)
        self.assertTrue(summary["research_only"])


if __name__ == "__main__":
    unittest.main()
