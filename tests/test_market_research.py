import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from council_v4 import council_vote
from market_research import COINBASE_CANDLES, KRAKEN_OHLC, _get_json, cross_market_research_result


class CrossMarketResearchTests(unittest.TestCase):
    def history(self, now):
        return pd.DataFrame({"time": [pd.Timestamp(now)], "close": [100_000.0]})

    def snapshot(self, coinbase_return, kraken_return):
        return {
            "sources": {
                "coinbase": {"return_5m": coinbase_return},
                "kraken": {"return_5m": kraken_return},
            },
            "source_health": {"coinbase": "OK", "kraken": "OK"},
        }

    def test_historical_data_never_consumes_current_internet_snapshot(self):
        now = datetime.now(timezone.utc)
        result = cross_market_research_result(
            self.history(now - timedelta(days=2)), self.snapshot(0.01, 0.01), now=now
        )
        self.assertEqual(result["research_status"], "INACTIVE")
        self.assertEqual(result["score"], 0.0)

    def test_two_exchange_agreement_makes_bounded_directional_call(self):
        now = datetime.now(timezone.utc)
        result = cross_market_research_result(self.history(now), self.snapshot(0.0025, 0.0022), now=now)
        self.assertEqual(result["research_status"], "ACTIVE")
        self.assertEqual(result["signal"], "BULLISH")
        self.assertGreater(result["score"], 0.12)
        self.assertLessEqual(abs(result["score"]), 0.55)
        self.assertLessEqual(result["confidence"], 0.72)

    def test_exchange_conflict_is_neutral(self):
        now = datetime.now(timezone.utc)
        result = cross_market_research_result(self.history(now), self.snapshot(0.003, -0.002), now=now)
        self.assertEqual(result["research_status"], "CONFLICT")
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertEqual(result["score"], 0.0)

    def test_one_failed_source_has_no_vote(self):
        now = datetime.now(timezone.utc)
        result = cross_market_research_result(
            self.history(now), {"sources": {"coinbase": {"return_5m": 0.01}}}, now=now
        )
        self.assertEqual(result["research_status"], "PARTIAL")
        self.assertEqual(result["score"], 0.0)

    def test_inactive_research_does_not_dilute_council(self):
        trend = {"name": "Trend AI", "signal": "BULLISH", "score": 0.5, "confidence": 0.8}
        inactive = {
            "name": "Cross-Market Research AI", "signal": "NEUTRAL", "score": 0.0,
            "confidence": 0.0, "research_status": "PARTIAL",
        }
        baseline = council_vote({"Trend AI": trend})
        with_inactive = council_vote({"Trend AI": trend, "Cross-Market Research AI": inactive})
        self.assertEqual(with_inactive["base_score"], baseline["base_score"])
        self.assertEqual(with_inactive["confidence"], baseline["confidence"])

    def test_fetcher_rejects_arbitrary_hosts_before_network(self):
        with self.assertRaises(ValueError):
            _get_json("https://example.com/prompt", {})
        self.assertTrue(COINBASE_CANDLES.startswith("https://api.exchange.coinbase.com/"))
        self.assertTrue(KRAKEN_OHLC.startswith("https://api.kraken.com/"))


if __name__ == "__main__":
    unittest.main()
