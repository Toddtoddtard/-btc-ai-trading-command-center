import json
import io
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import historical_backtest as replay


class HistoricalDeadlineTests(unittest.TestCase):
    def test_shared_archive_reader_rejects_bad_bars_and_duplicates(self):
        stamp = 1767225600000
        lines = [f'{stamp},100,102,99,101,10,{stamp+59999},1010,3,5,505,0',
                 f'{stamp},100,102,99,101,10,{stamp+59999},1010,3,5,505,0',
                 f'{stamp+60000},100,98,99,101,10,{stamp+119999},1010,3,5,505,0']
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('test.csv', '\n'.join(lines))
        class Response(io.BytesIO):
            pass
        with patch.object(replay, 'urlopen', return_value=Response(data.getvalue())):
            frame = replay.fetch_month(2026, 1)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.volume.iloc[0], 10.)
        self.assertEqual(frame.tq.iloc[0], 505.)

    def test_missing_deadline_does_not_use_later_price(self):
        stamp = pd.date_range('2026-01-01', periods=76, freq='min', tz='UTC')
        frame = pd.DataFrame({'time': stamp, 'open': 100., 'high': 102.,
                              'low': 99., 'close': 101.})
        frame.loc[61:, 'time'] += pd.Timedelta(hours=1)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(replay, 'OUT', Path(folder)/'report.json'), \
             patch.object(replay, 'month_iter', return_value=[(2026, 1)]), \
             patch.object(replay, 'fetch_month', return_value=frame), \
             patch.object(replay, 'forecast_path_core', return_value={'predicted_end': 102.}):
            with self.assertRaises(RuntimeError):
                replay.main()  # Tiny fixture deliberately fails publication minimum.
            report = json.loads(replay.OUT.read_text())
        self.assertEqual(report['overall']['samples'], 0)
