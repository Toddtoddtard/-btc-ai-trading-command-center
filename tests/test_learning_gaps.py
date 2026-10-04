import unittest
from datetime import datetime, timezone
import pandas as pd
from learner_v31 import record_learning_gap

class LearningGapTests(unittest.TestCase):
    def test_gap_preserves_missing_candles_without_inventing_calls(self):
        state = {}
        now = datetime(2026, 10, 4, 1, tzinfo=timezone.utc)
        frame = pd.DataFrame({'time': pd.date_range('2026-10-04T00:30Z', periods=32, freq='min')})
        record_learning_gap(state, '2026-10-04T00:00:00Z', now, frame)
        gap = state['learning_gap_history'][0]
        self.assertEqual(gap['expected_closed_minutes'], 60)
        self.assertEqual(gap['reloaded_closed_minutes'], 30)
        self.assertEqual(gap['unavailable_closed_minutes'], 30)
        self.assertIsNone(gap['missed_qualifying_calls'])
        self.assertFalse(gap['paper_trades_backfilled'])
        record_learning_gap(state, '2026-10-04T00:00:00Z', now, frame)
        self.assertEqual(len(state['learning_gap_history']), 1)
        record_learning_gap(state, now.isoformat(), now, frame)
        self.assertEqual(len(state['learning_gap_history']), 1)
