import time
import unittest
from unittest.mock import patch
import background_paper as bg
from contract_calibration import BASIS
from pro_trade_ticket import build_pro_trade_ticket

class AssessmentIntegrationTests(unittest.TestCase):
    def call(self, now):
        return dict(ticker='T', master_action='SCALP UP',master_confidence=.8,
                    execution_approved=True, expires_at=now+600,opened_at=now,
                    start_price=50000,predicted_end=50100,target=49950,would_wait=False,
                    contract_probability_basis=BASIS, contract_calibrator_active=True,
                    contract_probability_up=.85,settlement_reference_timestamp=now,
                    decision_schema='settlement-first-v1')

    def market(self,now):
        return dict(ticker='T',status='open',yes_bid_dollars=.49,yes_ask_dollars=.5,
                    quotes_observed_at=now)

    def test_persistent_worker_blocks_terminal_probability_as_scalp_exit(self):
        state={'pending':self.call(1000)}
        paper=bg.run_cycle(state,lambda _:self.market(1000),now=1000)
        self.assertIsNone(paper['open_position'])
        self.assertIn('NO_VALIDATED_SCALP_EXIT_MODEL',paper['last_message'])

    def test_preview_and_engine_share_the_same_blocker(self):
        now=time.time();d=self.call(now);d.update(action='SCALP UP',kalshi_ticker='T',
                    kalshi_close_ts=now+600,scalp_projected_exit_price=.85,**self.market(now))
        ticket=build_pro_trade_ticket(d,{'approved':True,'position_pct':.02},{'cash':500})
        self.assertEqual(ticket['status'],'WAIT')
        self.assertIn('NO_VALIDATED_SCALP_EXIT_MODEL',ticket['blockers'])
        self.assertIsNone(ticket['take_profit_price'])
        self.assertIsNone(ticket['projected_exit_fee'])

    def test_gross_scalp_gain_cannot_be_reported_as_profit_when_fees_make_it_a_loss(self):
        c=self.call(1000);c.pop('decision_schema')
        state={'pending':c}
        p=bg.run_cycle(state,lambda _:self.market(1000),now=1000)
        self.assertIsNotNone(p['open_position'])
        state['pending']['contract_calibrator_active']=False
        m=dict(self.market(1001),yes_bid_dollars=.526,yes_ask_dollars=.536)
        p=bg.run_cycle(state,lambda _:m,now=1001)
        self.assertIsNotNone(p['open_position'])
        self.assertFalse(any(t.get('exit_reason')=='TAKE_PROFIT_AI_UPSIDE_EXHAUSTED' for t in p['trades']))

    def test_current_decisions_cannot_open_a_second_local_sqlite_ledger(self):
        import tempfile
        import kalshi_paper_engine as engine
        now=time.time()
        d=dict(action='LOCK UP',confidence=.95,execution_approved=True,
               kalshi_ticker='T',kalshi_close_ts=now+600,yes_bid_dollars=.49,
               yes_ask_dollars=.5,contract_probability_up=.9,
               contract_probability_basis=BASIS,contract_calibrator_active=True)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNotNone(engine.open_position(tmp+'/legacy.db',500,d,{'position_pct':.02},50000))
            self.assertIsNone(engine.open_position(tmp+'/current.db',500,
                 dict(d,decision_schema='settlement-first-v1'),{'position_pct':.02},50000))
