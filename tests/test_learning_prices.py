import unittest
import pandas as pd
from learning_prices import closed_price_at

class LearningPriceTests(unittest.TestCase):
    def test_closed_candle_not_future_candle(self):
        hist = pd.DataFrame({'time': pd.date_range('2026-09-06T12:00Z', periods=2, freq='min'), 'close':[100,200]})
        self.assertEqual(closed_price_at(hist, pd.Timestamp('2026-09-06T12:01Z')), 100)
        self.assertIsNone(closed_price_at(hist, pd.Timestamp('2026-09-06T11:00Z')))
        self.assertIsNone(closed_price_at(hist, pd.Timestamp('2026-09-06T13:00Z')))
