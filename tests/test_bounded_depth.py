import ast
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import background_paper as bg
import learner

BOOK={'orderbook_fp':{'yes_dollars':[['.60','10']],'no_dollars':[['.39','12']]}}

class BoundedDepthTests(unittest.TestCase):
    def test_background_requests_only_needed_depth_with_bounded_read_budget(self):
        def read(request,timeout):
            if timeout<4:
                raise TimeoutError('Public host needs its documented bounded latency budget')
            if '/orderbook' in request.full_url:
                if '?depth=5' not in request.full_url or timeout<4:
                    raise TimeoutError('Unbounded response exceeds execution budget')
                return io.BytesIO(json.dumps(BOOK).encode())
            return io.BytesIO(json.dumps({'market':{'ticker':'T','status':'active'}}).encode())
        with patch.object(bg,'urlopen',side_effect=read):
            m=bg._market('T')
        self.assertTrue(m['execution_book']['available'])
        self.assertEqual(m['execution_book']['yes_ask_size'],12)

    def test_learner_uses_same_bounded_depth(self):
        def read(path,params=None):
            self.assertEqual(params,{'depth':5})
            return BOOK
        with patch.object(learner,'kalshi_get',side_effect=read):
            self.assertTrue(learner.orderbook('T')['available'])

    def test_dashboard_uses_same_depth_and_can_recover_invalid_primary_book(self):
        from kalshi_microstructure import orderbook_features
        calls=[]
        def read(url,timeout):
            calls.append(url)
            self.assertIn('?depth=5',url)
            self.assertGreaterEqual(timeout,4)
            return ({'orderbook_fp':{}} if len(calls)==1 else BOOK),0
        namespace=dict(orderbook_features=orderbook_features,http_json=read,
                       KALSHI_BASES=('https://primary','https://backup'),st=type('S',(),{'cache_data':lambda **k:lambda f:f})())
        tree=ast.parse(Path('app.py').read_text());f=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='fetch_kalshi_orderbook');f.decorator_list=[]
        exec(compile(ast.Module(body=[f],type_ignores=[]),'app.py','exec'),namespace)
        self.assertTrue(namespace['fetch_kalshi_orderbook']('T')['available'])
