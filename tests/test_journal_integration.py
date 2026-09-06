"""Exercise the real app resolver in isolation from Streamlit and live feeds."""
import ast
import contextlib
from pathlib import Path
import sqlite3
import unittest
from types import SimpleNamespace
import pandas as pd
import numpy as np

class JournalIntegrationTests(unittest.TestCase):
    def test_scalps_grade_direction_and_wait_stays_separate(self):
        tree = ast.parse(Path('app.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_predictions')
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE predictions(id INTEGER PRIMARY KEY, created_ts INTEGER,target_ts INTEGER, price REAL, action TEXT,target_price REAL,resolved INTEGER,correct INTEGER,resolved_price REAL,return_pct REAL)')
        for i, action in enumerate(('SCALP UP','SCALP DOWN','HOLD','WAIT'),1):
            conn.execute('INSERT INTO predictions VALUES(?,0,900,100,?,200,0,NULL,NULL,NULL)',(i,action))
        @contextlib.contextmanager
        def db_conn():
            yield conn
        def safe_float(v, default=np.nan):
            try: return float(v)
            except (TypeError, ValueError): return default
        env = dict(pd=pd,np=np,time=SimpleNamespace(time=lambda:1000),PREDICTION_HORIZON_MIN=15,
                   db_conn=db_conn,safe_float=safe_float,SPOT_BASES=[],SYMBOL='BTCUSDT',
                   try_bases=lambda *a,**kw:([],0))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<app resolver>','exec'),env)
        hist=pd.DataFrame({'time':pd.to_datetime([840,900],unit='s',utc=True),'close':[110,50]})
        env['resolve_predictions'](hist)
        rows=conn.execute('SELECT * FROM predictions ORDER BY id').fetchall()
        self.assertEqual(rows[0]['correct'],1)
        self.assertEqual(rows[1]['correct'],0)
        for row in rows:
            self.assertEqual(row['resolved_price'],110)
        self.assertIsNone(rows[2]['correct'])
        self.assertIsNone(rows[3]['correct'])
