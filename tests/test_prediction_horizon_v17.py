from pathlib import Path
import unittest


class PredictionHorizonV17Tests(unittest.TestCase):
    def test_patcher_contains_stable_overlay_horizons(self):
        text = Path('tools/apply_prediction_horizon_v17.py').read_text()
        self.assertIn('id="prediction-horizon-controls"', text)
        self.assertIn('data-horizon="1"', text)
        self.assertIn('data-horizon="5"', text)
        self.assertIn('data-horizon="15"', text)
        self.assertIn('let selectedPredictionHorizon = 15;', text)
        self.assertIn('predictionPathTrace(rows, selectedPredictionHorizon)', text)
        self.assertNotIn('updatemenus:', text)


if __name__ == '__main__':
    unittest.main()
