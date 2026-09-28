import tempfile
import time
import unittest

import background_paper as bg
import kalshi_paper_engine as engine
from lock_focus import evaluate_lock_focus
from pro_trade_ticket import build_pro_trade_ticket


class EntryCapTests(unittest.TestCase):
    def test_strategy_boundaries_match_background_sqlite_and_ticket(self):
        for strategy, ask, allowed in [('LOCK', .85, True), ('LOCK', .93, True),
                                        ('LOCK', .9301, False), ('LOCK', .94, False),
                                        ('SCALP', .75, True), ('SCALP', .76, False)]:
            for direction, side in [('UP', 'yes'), ('DOWN', 'no')]:
                with self.subTest(strategy=strategy, ask=ask, side=side), tempfile.TemporaryDirectory() as tmp:
                    now = time.time()
                    quotes = {f'{side}_ask_dollars': ask, f'{side}_bid_dollars': ask-.01}
                    other = 'no' if side == 'yes' else 'yes'
                    quotes.update({f'{other}_ask_dollars': 1-(ask-.01), f'{other}_bid_dollars': 1-ask})
                    action = f'{strategy} {direction}'
                    decision = dict(action=action, confidence=.95, kalshi_ticker='TEST',
                                    kalshi_close_ts=now+600, scalp_projected_exit_price=.99, **quotes)
                    risk = dict(approved=True, position_pct=.02)
                    opened = engine.open_position(tmp+'/paper.db', 500, decision, risk, 100000)
                    self.assertEqual(bool(opened), allowed)
                    ticket = build_pro_trade_ticket(decision, risk, {'cash':500})
                    self.assertEqual(ticket['status'] == 'READY', allowed)
                    state = {'pending': dict(ticker='TEST', expires_at=now+600,
                             master_action=action, execution_approved=True, master_confidence=.95,
                             start_price=100000, target=100000,
                             predicted_end=101000 if direction=='UP' else 99000)}
                    paper = bg.run_cycle(state, lambda _: dict(ticker='TEST', status='open', **quotes), now=now)
                    self.assertEqual(paper['open_position'] is not None, allowed)
                    if not allowed:
                        self.assertIn('93%' if strategy=='LOCK' else '75%', paper['last_message'])

    def test_master_lock_boundary_in_both_directions(self):
        for direction, side in [('UP','yes'), ('DOWN','no')]:
            for ask in (.93, .9301):
                focus = evaluate_lock_focus(base_score=.4 if direction=='UP' else -.4,
                    confidence=.95, consensus=.9, source_health=1, seconds_remaining=600,
                    target_confirmed=True, direction=direction,
                    market={f'{side}_bid':ask-.01, f'{side}_ask':ask})
                self.assertEqual(focus['eligible'], ask==.93)
