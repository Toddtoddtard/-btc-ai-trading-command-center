import unittest

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core
from council_v4 import specialist_weight
from enrich_learning_state_v5 import resolve_current_regime


class AuditV6Tests(unittest.TestCase):
    def _flat_history(self):
        n = 80
        base = 80000.0
        close = base + np.linspace(0.0, 8.0, n)
        df = pd.DataFrame({
            "open": close - 1.0,
            "high": close + 3.0,
            "low": close - 3.0,
            "close": close,
            "volume": np.full(n, 10.0),
        })
        return enrich_history_core(df)

    def test_trend_tiny_ema_spread_does_not_saturate(self):
        hist = self._flat_history()
        results = run_specialists_core(hist, pd.DataFrame(), {}, {"available": False})
        trend = results["Trend AI"]
        self.assertLess(abs(trend["score"]), 0.50)
        self.assertLess(trend["confidence"], 0.75)

    def test_sparse_whale_print_does_not_force_max_confidence(self):
        hist = self._flat_history()
        agg = pd.DataFrame([
            {"aggressor": "BUY", "notional": 120000.0},
            *[{"aggressor": "SELL", "notional": 10000.0} for _ in range(20)],
            *[{"aggressor": "BUY", "notional": 10000.0} for _ in range(20)],
        ])
        results = run_specialists_core(hist, agg, {}, {"available": False})
        whale = results["Whale AI"]
        self.assertLess(abs(whale["score"]), 0.95)
        self.assertLess(whale["confidence"], 0.94)
        self.assertIn("evidence", whale["reason"].lower())

    def test_harmful_bot_is_downweighted_after_evidence(self):
        state = {
            "specialists": {"Whale AI": {"adaptive_weight": 1.0, "regimes": {}}},
            "bot_intelligence_v4": {
                "ranking": [{
                    "name": "Whale AI",
                    "samples": 20,
                    "contribution_score": -0.30,
                }]
            },
        }
        harmful = specialist_weight("Whale AI", state, "LOW_VOL_RANGE")
        baseline = specialist_weight("Whale AI", {}, "LOW_VOL_RANGE")
        self.assertLess(harmful, baseline * 0.70)

    def test_regime_resolver_prefers_active_pending_window(self):
        state = {
            "pending": {"regime": "LOW_VOL_RANGE"},
            "status": {"current_regime": "TREND_UP"},
            "master_history": [{"regime": "HIGH_VOL"}],
        }
        self.assertEqual(resolve_current_regime(state), "LOW_VOL_RANGE")


if __name__ == "__main__":
    unittest.main()
