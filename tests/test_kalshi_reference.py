import unittest

from kalshi_reference import VENUES, fetch_kalshi_reference


def _payload(url):
    if "coinbase" in url:
        return {"price": "76410.00"}
    if "kraken" in url:
        return {"result": {"XXBTZUSD": {"c": ["76412.00", "1"]}}}
    if "bitstamp" in url:
        return {"last": "76408.00"}
    if "gemini" in url:
        return {"last": "76411.00"}
    raise AssertionError(url)


class KalshiReferenceTests(unittest.TestCase):
    def test_reference_uses_robust_usd_median(self):
        row = fetch_kalshi_reference(fetch_json=_payload)
        self.assertTrue(row["healthy"])
        self.assertEqual(row["samples"], len(VENUES))
        self.assertEqual(row["price"], 76410.5)

    def test_reference_rejects_large_outlier(self):
        def payload(url):
            row = _payload(url)
            if "gemini" in url:
                row = {"last": "80000.00"}
            return row

        result = fetch_kalshi_reference(fetch_json=payload)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["samples"], 3)
        self.assertEqual(result["price"], 76410.0)


if __name__ == "__main__":
    unittest.main()
