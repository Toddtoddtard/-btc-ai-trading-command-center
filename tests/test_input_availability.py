import unittest
import numpy as np
import pandas as pd
from ai_core import enrich_history_core, run_specialists_core

class InputAvailabilityTests(unittest.TestCase):
    def test_failed_partial_futures_are_unavailable_not_directional_evidence(self):
        close=50000+np.arange(250)
        raw=pd.DataFrame(dict(time=pd.date_range('2026-01-01',periods=250,freq='min',tz='UTC'),
                             open=close, high=close+1, low=close-1, close=close,volume=10))
        result=run_specialists_core(enrich_history_core(raw),pd.DataFrame(),
                                   dict(ok=False,book_imbalance=.9,funding_rate=.01),{'available':False})
        for name in ['Liquidity AI','Derivatives AI']:
            self.assertEqual(result[name]['score'],0)
            self.assertEqual(result[name]['feed_status'],'UNAVAILABLE')
            self.assertIn('unavailable',result[name]['reason'].lower())
