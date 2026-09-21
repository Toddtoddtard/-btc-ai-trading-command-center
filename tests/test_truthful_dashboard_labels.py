import unittest
from pathlib import Path


class TruthfulDashboardLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app.py").read_text(encoding="utf-8")

    def test_top_market_change_is_not_labeled_as_accuracy(self):
        self.assertIn('"BTC 24h Change"', self.source)
        self.assertNotIn('"Lifetime Accuracy"', self.source)

    def test_signal_journal_is_distinct_from_paper_ledger(self):
        self.assertIn('"Signal calls resolved"', self.source)
        self.assertIn('"Signal-call accuracy"', self.source)
        self.assertIn('"Valid closed trades"', self.source)


if __name__ == "__main__":
    unittest.main()
