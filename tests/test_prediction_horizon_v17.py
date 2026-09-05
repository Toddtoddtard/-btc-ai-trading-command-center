from pathlib import Path
import unittest


class PredictionHorizonV17Tests(unittest.TestCase):
    def test_patcher_contains_three_horizons(self):
        text = Path('tools/apply_prediction_horizon_v17.py').read_text()
        self.assertIn('predictionPathTrace(rows, 1, false)', text)
        self.assertIn('predictionPathTrace(rows, 5, false)', text)
        self.assertIn('predictionPathTrace(rows, 15, true)', text)
        self.assertIn('label: "1m"', text)
        self.assertIn('label: "5m"', text)
        self.assertIn('label: "15m"', text)


if __name__ == '__main__':
    unittest.main()
