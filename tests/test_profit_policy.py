import tempfile
import time
import unittest
from unittest.mock import patch
import background_paper as bg
import kalshi_paper_engine as engine
from lock_focus import evaluate_lock_focus
from profit_policy import entry_economics
from pro_trade_ticket import build_pro_trade_ticket

class ProfitPolicyTests(unittest.TestCase):
    def test_low_confidence_positive_edge_and_high_confidence_bad_price(self):
        common = dict(base_score=.01, confidence=.55, consensus=.1, source_health=1,
                      seconds_remaining=600, target_confirmed=True, direction='UP')
        self.assertTrue(evaluate_lock_focus(**common, probability_up=.60,
                         market={'yes_bid':.48, 'yes_ask':.50})['eligible'])
        common['confidence'] = .99
        self.assertFalse(evaluate_lock_focus(**common, probability_up=.70,
                          market={'yes_bid':.79, 'yes_ask':.80})['eligible'])
        common['source_health'] = .4
        self.assertFalse(evaluate_lock_focus(**common, probability_up=.9,
                          market={'yes_bid':.48, 'yes_ask':.50})['eligible'])

    def test_fees_margin_and_missing_values(self):
        for value in (None, float('nan'), float('inf'), 1.1):
            self.assertFalse(entry_economics('LOCK', 10, .5, value)['approved'])
        self.assertFalse(entry_economics('LOCK', 1, .5, .52)['approved'])
        self.assertTrue(entry_economics('LOCK', 1, .5, .53)['approved'])
        self.assertFalse(entry_economics('SCALP', 1, .5, .53)['approved'])
        self.assertTrue(entry_economics('SCALP', 1, .5, .55)['approved'])

    def test_both_sides_and_engines_and_ticket(self):
        for strategy, ask, value, allowed in [
            ('LOCK', .94, .98, True), ('LOCK', .85, .70, False),
            ('LOCK', .5, None, False), ('LOCK', .5, .60, True),
            ('SCALP', .80, .84, True), ('SCALP', .80, .81, False)]:
            for direction, side in [('UP', 'YES'), ('DOWN', 'NO')]:
                with self.subTest(strategy=strategy,ask=ask,value=value,side=side), tempfile.TemporaryDirectory() as tmp:
                    now=time.time()
                    p_up = None if value is None else value if side=='YES' else 1-value
                    prefix=side.lower()
                    quotes={prefix+'_ask_dollars':ask, prefix+'_bid_dollars':ask-.01}
                    action=strategy+' '+direction
                    decision=dict(action=action, confidence=.55, execution_approved=True,
                                  contract_probability_up=p_up, kalshi_ticker='T',
                                  kalshi_close_ts=now+600, scalp_projected_exit_price=value, **quotes)
                    risk=dict(approved=True, position_pct=.02)
                    self.assertEqual(bool(engine.open_position(tmp+'/db',500,decision,risk,100000)),allowed)
                    self.assertEqual(build_pro_trade_ticket(decision,risk,{'cash':500})['status']=='READY',allowed)
                    state={'pending':dict(ticker='T',expires_at=now+600,master_action=action,
                                          master_confidence=.55,execution_approved=True,contract_probability_up=p_up)}
                    with patch.object(bg, '_projected_side_value', return_value=value):
                        paper=bg.run_cycle(state,lambda _:dict(ticker='T',status='open',**quotes),now=now)
                    self.assertEqual(paper['open_position'] is not None,allowed)
