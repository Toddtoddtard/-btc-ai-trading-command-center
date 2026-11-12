import unittest
from unittest.mock import MagicMock,patch

class DecisionDashboardTests(unittest.TestCase):
    def test_compact_preview_keeps_open_position_and_stale_warning_visible(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ModuleNotFoundError:
            self.skipTest('UI integration requires application dependencies')
        app = AppTest.from_string('''
from decision_dashboard import render_decision_assessment
state = {'background_paper': {'cash': 500, 'last_cycle_at': '2020-01-01T00:00:00+00:00',
    'open_position': {'strategy': 'LOCK', 'direction': 'DOWN', 'ticker': 'TEST'},
    'last_message': 'Holding the recorded LOCK position'}}
render_decision_assessment({'action': 'SCALP UP'}, {'approved': False}, state, {}, {})
''').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('HOLD LOCK DOWN' in x.value for x in app.markdown))
        self.assertTrue(any('stale or unavailable' in x.value for x in app.warning))
        details = next(x for x in app.expander if x.label == 'Contract details and entry checks')
        self.assertFalse(details.proto.expanded)
        self.assertTrue(any('one paper position is already open' in x.value
                            for x in details.markdown))
        self.assertEqual(len(app.info), 0)

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

    def test_live_outlook_uses_current_market_without_worker_data(self):
        from decision_dashboard import live_outlook
        from decision_snapshot import dashboard_decision
        ticker = 'KXBTC15M-26NOV121900-00'
        preview = dict(kalshi_ticker=ticker, kalshi_close_ts=1600, target_price=71200,
                       action='LOCK DOWN', confidence=.74, consensus=.8, base_score=-.4)
        feed = dict(available=True, timestamp=999, event_ticker='KXBTC15M-26NOV121900')
        self.assertEqual(live_outlook(preview, feed, now=1000),
                         ('LOCK DOWN', 'DOWN', .74, .8))
        worker = dashboard_decision(preview, {}, now=1000)
        self.assertFalse(worker['execution_approved'])
        self.assertEqual(worker['action'], 'WAIT')
        self.assertEqual(live_outlook(dict(preview, action='SCALP DOWN'), feed, now=1000)[0],
                         'OUTLOOK DOWN')

    def test_live_outlook_rejects_expired_market_stale_reference_and_other_event(self):
        from decision_dashboard import live_outlook
        preview = dict(kalshi_ticker='KXBTC15M-26NOV121900-00', kalshi_close_ts=1600,
                       target_price=71200, action='LOCK UP', confidence=.74, consensus=.8)
        feed = dict(available=True, timestamp=999, event_ticker='KXBTC15M-26NOV121900')
        for reference, now in [
            (feed, 1600), (feed, 1030), (dict(feed, event_ticker='KXBTC15M-26NOV121845'), 1000),
        ]:
            with self.subTest(reference=reference, now=now):
                self.assertEqual(live_outlook(preview, reference, now=now),
                                 ('OUTLOOK UNAVAILABLE', None, None, None))
