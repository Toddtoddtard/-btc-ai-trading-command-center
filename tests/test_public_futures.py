import unittest
from unittest.mock import patch

import learner
from public_futures import parse_bybit_futures_snapshot


class PublicFuturesFallbackTests(unittest.TestCase):
    def test_parses_public_bybit_derivatives_snapshot(self):
        ticker = {
            "result": {"list": [{
                "fundingRate": "0.0001",
                "markPrice": "86500.5",
                "openInterest": "12345.6",
            }]}
        }
        book = {
            "result": {
                "b": [["86500", "2"], ["86499", "1"]],
                "a": [["86501", "1"], ["86502", "1"]],
            }
        }
        snapshot = parse_bybit_futures_snapshot(ticker, book)
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["source"], "Bybit public BTCUSDT perpetual")
        self.assertAlmostEqual(snapshot["funding_rate"], 0.0001)
        self.assertAlmostEqual(snapshot["mark_price"], 86500.5)
        self.assertAlmostEqual(snapshot["open_interest"], 12345.6)
        self.assertGreater(snapshot["book_imbalance"], 0)

    def test_rejects_incomplete_snapshot_instead_of_inventing_zeroes(self):
        with self.assertRaises(ValueError):
            parse_bybit_futures_snapshot({"result": {"list": []}}, {})

    @patch("learner.get")
    def test_learner_uses_keyless_fallback_when_binance_futures_is_down(self, mocked_get):
        def response(url, _params=None):
            if "fapi.binance.com" in url:
                raise OSError("primary unavailable")
            if url.endswith("/v5/market/tickers"):
                return {
                    "result": {"list": [{
                        "fundingRate": "0.0002",
                        "markPrice": "86600",
                        "openInterest": "25000",
                    }]}
                }
            return {"result": {"b": [["86599", "3"]], "a": [["86601", "1"]]}}

        mocked_get.side_effect = response
        snapshot = learner.futures_snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertIn("Bybit", snapshot["source"])
        self.assertEqual(snapshot["open_interest"], 25000.0)


if __name__ == "__main__":
    unittest.main()
