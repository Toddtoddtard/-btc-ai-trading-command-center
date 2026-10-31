import unittest
from unittest.mock import MagicMock,patch

class DecisionDashboardTests(unittest.TestCase):
    def test_blocked_scalp_is_an_outlook_not_an_executable_trade_label(self):
        from decision_dashboard import outlook_label, decision_status
        d={'action':'SCALP UP'}
        self.assertEqual(outlook_label(d),'OUTLOOK UP')
        v=decision_status(d, {'background_paper':{'last_message':'No validated edge'}})
        self.assertEqual(v['paper_action'],'WAIT')
        self.assertEqual(v['reason'],'No validated edge')

    def test_open_lock_remains_visible_separately_from_changed_forecast(self):
        from decision_dashboard import decision_status
        s={'background_paper':{'open_position':{'strategy':'LOCK','direction':'DOWN','ticker':'T'}}}
        self.assertEqual(decision_status({'action':'SCALP UP'},s)['paper_action'],'HOLD LOCK DOWN')

    def test_outlook_badges_keep_direction_colors_and_arrows(self):
        from dashboard_ui import directional_badge_html
        for label in ['OUTLOOK UP','LOCKED OUTLOOK UP']:
            self.assertIn('call-up',directional_badge_html(label))
            self.assertIn('▲',directional_badge_html(label))
        for label in ['OUTLOOK DOWN','LOCKED OUTLOOK DOWN']:
            self.assertIn('call-down',directional_badge_html(label))
            self.assertIn('▼',directional_badge_html(label))
